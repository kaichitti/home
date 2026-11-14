"""S8 統合・検証・ランク付け（企画書 §3.8）。

全段の候補を sha256 で束ね、1 グループから最良版を 1 つ選ぶ。
  優先順: 開ける > 一部破損 / フォルダ付き > 名前のみ > 名前なし / パス情報が多い方 /
          生存ファイル > 削除済み
ランク:
  A 名前付きで開ける / B 名前なしだが開ける / C 開けるが一部破損 / D サムネイルのみ（P11）
  U 種別不明で検証できない（要確認） / X ランク外（ゼロ・空・破損＝復旧扱いにしない）
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .. import validate as V
from ..db import now
from ..hashing import sha256_file
from .manifest import Candidate, Manifest

RANK_ORDER = "ABCDUX"
STATUS_SCORE = {V.OK: 3, V.UNVERIFIED: 2, V.PARTIAL: 1, V.BROKEN: 0, V.ZERO: -1, V.EMPTY: -2}


@dataclass
class Item:
    stage: str
    image_id: int | None
    cand: Candidate
    sha256: str
    size: int
    result: V.Result


def rank_for(item: Item) -> str:
    s = item.result.status
    if s in V.NOT_RECOVERED:
        return "X"
    if s == V.PARTIAL:
        return "C"
    if s == V.UNVERIFIED:
        return "U"
    if item.cand.extra.get("thumbnail"):
        return "D"
    return "A" if item.cand.named else "B"


def _score(item: Item) -> tuple:
    c = item.cand
    return (
        STATUS_SCORE.get(item.result.status, 0),
        1 if c.path_known else 0,
        1 if c.named else 0,
        (c.orig_path or "").count("/"),   # フォルダ階層が深い＝パス情報が多い
        len(c.orig_path or ""),
        1 if c.deleted is False else 0,
    )


def load_manifests(case) -> list[tuple[str, Manifest]]:
    out = []
    for p in sorted((case.dir / "stages").glob("img*/*/manifest.json")):
        out.append((p.parent.name, Manifest.read(p)))
    return out


def merge(case) -> dict:
    items: list[Item] = []
    for stage_dir_name, man in load_manifests(case):
        for c in man.candidates:
            f = case.dir / c.stored
            if not f.is_file():
                continue
            r = V.validate(f, Path(c.orig_path).name if c.orig_path else None)
            items.append(Item(man.stage if man.stage != "COM" else stage_dir_name, man.image_id, c,
                              sha256_file(f), f.stat().st_size, r))

    groups: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        groups[it.sha256].append(it)

    stage_found: dict[str, int] = defaultdict(int)
    stage_unique: dict[str, int] = defaultdict(int)
    rows = []
    for sha, members in groups.items():
        best = max(members, key=_score)
        rank = rank_for(best)
        stages = sorted({m.stage for m in members})
        if rank != "X":
            for st in stages:
                stage_found[st] += 1
            if len(stages) == 1:
                stage_unique[stages[0]] += 1
        c = best.cand
        name = Path(c.orig_path).name if c.orig_path else Path(c.stored).name
        alt = sorted({m.cand.orig_path for m in members if m.cand.orig_path and m.cand.orig_path != c.orig_path})
        rows.append(dict(
            case_id=case.id, image_id=best.image_id, orig_path=c.orig_path if c.path_known else None,
            name=name, size=best.size, kind=best.result.kind, verify=best.result.status, rank=rank,
            sha256=sha, method=c.method, stage=best.stage, stored_path=c.stored,
            deleted=None if c.deleted is None else int(c.deleted), img_offset=c.img_offset,
            all_methods=json.dumps(sorted({m.cand.method for m in members}), ensure_ascii=False),
            alt_names=json.dumps(alt, ensure_ascii=False) if alt else None,
        ))

    rows.sort(key=lambda r: (RANK_ORDER.index(r["rank"]), r["orig_path"] or "~", r["name"]))
    with case.db.tx() as conn:
        conn.execute("DELETE FROM recovered_files WHERE case_id=?", (case.id,))
        for r in rows:
            cols = ", ".join(r)
            conn.execute(f"INSERT INTO recovered_files ({cols}) VALUES ({', '.join('?' * len(r))})",
                         tuple(r.values()))

    ranks = {k: sum(1 for r in rows if r["rank"] == k) for k in RANK_ORDER}
    report = {
        "created_at": now(),
        "groups": len(rows),
        "candidates": len(items),
        "ranks": ranks,
        "stages": {st: {"found": stage_found[st], "unique": stage_unique[st]}
                   for st in sorted(set(stage_found) | {i.stage for i in items})},
    }
    # 段別件数を stage_runs の最新行に反映
    for st, v in report["stages"].items():
        row = case.db.one("SELECT id FROM stage_runs WHERE case_id=? AND stage=? ORDER BY id DESC LIMIT 1",
                          case.id, st)
        if row:
            case.db.execute("UPDATE stage_runs SET found=?, unique_found=? WHERE id=?",
                            v["found"], v["unique"], row["id"])
    (case.sub("stages") / "stage_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    case.db.add_event(case.id, "recover.S8.merge", json.dumps(ranks), 0)
    return report
