"""納品（P5）：選択されたファイルを納品メディアへコピーし、ハッシュ照合して納品書を出す。

メディア上の構成:
  <案件番号>_復旧データ/
    復旧データ/      ランク A（元のフォルダ構成のまま）・U
    名前不明/        ランク B（カービングで名前が戻らなかったもの）
    一部破損/        ランク C
    サムネイル/      ランク D
    納品ファイル一覧.csv   全ファイルの相対パス・サイズ・SHA-256
    納品書.pdf
"""
from __future__ import annotations

import csv
import hashlib
import io
import shutil
from datetime import datetime
from pathlib import Path

from . import reports, safety
from .cases import Case
from .db import now
from .errors import ResqError
from .hashing import sha256_file
from .recover.manifest import LOST_DIR, PARTIAL_PREFIX

FOLDER = {"A": "復旧データ", "U": "復旧データ", "B": "名前不明", "C": "一部破損", "D": "サムネイル"}
DEFAULT_RANKS = ("A", "B")


def select(case: Case, *, ranks: tuple[str, ...] | None = DEFAULT_RANKS, ids: list[int] | None = None,
           add: bool = False) -> int:
    """納品対象を選ぶ。ランク外（X）は選べない。add=False なら選び直し。"""
    with case.db.tx() as c:
        if not add:
            c.execute("UPDATE recovered_files SET selected=0 WHERE case_id=?", (case.id,))
        if ids:
            qs = ",".join("?" * len(ids))
            c.execute(f"UPDATE recovered_files SET selected=1 WHERE case_id=? AND rank!='X' AND id IN ({qs})",
                      (case.id, *ids))
        if ranks:
            qs = ",".join("?" * len(ranks))
            c.execute(f"UPDATE recovered_files SET selected=1 WHERE case_id=? AND rank!='X' AND rank IN ({qs})",
                      (case.id, *[r for r in ranks if r != "X"]))
    n = case.db.one("SELECT COUNT(*) AS n FROM recovered_files WHERE case_id=? AND selected=1", case.id)["n"]
    case.db.add_event(case.id, "deliver.select", f"ranks={ranks} ids={ids} -> {n}", 0)
    return n


def _rel_dest(row) -> str:
    rank = row["rank"]
    folder = FOLDER.get(rank, "その他")
    if rank in ("A", "U") and row["orig_path"]:
        p = row["orig_path"]
        if p.startswith(PARTIAL_PREFIX):
            p = "上位フォルダ不明/" + p[len(PARTIAL_PREFIX):]
        p = "/".join(seg.replace(LOST_DIR, "フォルダ名不明") for seg in p.split("/"))
        return f"{folder}/{p}"
    return f"{folder}/{row['name']}"


def deliver(case: Case, target: Path, *, operator: str = "", pdf: bool = True) -> dict:
    rows = case.db.all("SELECT * FROM recovered_files WHERE case_id=? AND selected=1 ORDER BY rank, id", case.id)
    if not rows:
        raise ResqError("納品対象が選ばれていません（`resq select`）")
    total = sum(r["size"] for r in rows)
    sources = [r["source"] for r in case.db.all("SELECT source FROM images WHERE case_id=?", case.id)]
    t = safety.assert_delivery_target(target, case_dir=case.dir, sources=sources, required_bytes=total)
    root = t / f"{case.id}_復旧データ"
    if root.exists():
        raise ResqError(f"納品先に同じ案件のフォルダがすでにあります: {root}")
    root.mkdir()

    listing = []
    mismatches = []
    used: set[str] = set()
    for r in rows:
        rel = _rel_dest(r)
        base, n = rel, 1
        while rel.lower() in used:
            rel = f"{Path(base).with_suffix('')}~{n}{Path(base).suffix}"
            n += 1
        used.add(rel.lower())
        dest = safety.safe_join(root, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(case.dir / r["stored_path"], dest)
        got = sha256_file(dest)
        if got != r["sha256"]:
            mismatches.append(rel)
        listing.append({"path": rel, "size": r["size"], "sha256": got, "rank": r["rank"],
                        "ok": got == r["sha256"]})
    if mismatches:
        case.db.add_event(case.id, "deliver.mismatch", ", ".join(mismatches), 1)
        raise ResqError(f"ハッシュ不一致のファイルがあります（メディア不良の可能性）: {mismatches[:5]}")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["相対パス", "サイズ", "SHA-256", "ランク"])
    for it in listing:
        w.writerow([it["path"], it["size"], it["sha256"], it["rank"]])
    csv_bytes = buf.getvalue().encode("utf-8-sig")  # Excel で文字化けしないよう BOM 付き
    (root / "納品ファイル一覧.csv").write_bytes(csv_bytes)
    manifest_sha = hashlib.sha256(csv_bytes).hexdigest()

    by_rank: dict[str, dict] = {}
    for it in listing:
        d = by_rank.setdefault(it["rank"], {"count": 0, "bytes": 0})
        d["count"] += 1
        d["bytes"] += it["size"]
    html, pdf_path = reports.render(
        "delivery_note.html", case.sub("deliver") / "delivery_note.html", pdf=pdf,
        case=case.row, issued=datetime.now().strftime("%Y-%m-%d %H:%M"), operator=operator,
        count=len(listing), total=total, by_rank=by_rank, manifest_sha=manifest_sha,
        folder=root.name, files=listing[:200], more=max(0, len(listing) - 200))
    note = pdf_path or html
    shutil.copyfile(note, root / ("納品書" + note.suffix))
    case.db.insert("deliveries", case_id=case.id, delivered_at=now(), target=str(root), files=len(listing),
                   bytes=total, manifest_sha256=manifest_sha, note_path=str(note))
    case.db.add_event(case.id, "deliver.done", f"files={len(listing)} bytes={total} manifest={manifest_sha}", 0)
    case.advance("納品済")
    return {"root": root, "count": len(listing), "bytes": total, "manifest_sha256": manifest_sha, "note": note}
