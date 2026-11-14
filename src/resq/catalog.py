"""一覧化・検証（P4）。顧客向けの復旧ファイル一覧（HTML → PDF）を作る。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import reports
from . import validate as V
from .recover import STAGES

RANK_LABEL = {
    "A": "名前・フォルダ付きで開けるファイル",
    "B": "名前は戻らなかったが開けるファイル",
    "C": "開けるが一部破損しているファイル",
    "D": "サムネイル・低解像度版のみ",
    "U": "自動確認できなかったファイル（要確認）",
}
VERIFY_LABEL = {V.OK: "開ける", V.PARTIAL: "一部破損", V.UNVERIFIED: "未確認", V.BROKEN: "破損",
                V.ZERO: "中身なし", V.EMPTY: "0 バイト"}
THUMB_PX = 120


def _thumbnail(src: Path, dest: Path) -> bool:
    from PIL import Image, ImageFile

    prev = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        with Image.open(src) as im:
            im.thumbnail((THUMB_PX, THUMB_PX))
            im.convert("RGB").save(dest, "JPEG", quality=70)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = prev


def build(case, *, pdf: bool = True, revalidate: bool = True) -> dict:
    out_dir = case.sub("catalog")
    thumbs = out_dir / "thumbs"
    thumbs.mkdir(exist_ok=True)
    rows = case.db.all("SELECT * FROM recovered_files WHERE case_id=? ORDER BY id", case.id)

    files_by_rank: dict[str, list[dict]] = {k: [] for k in RANK_LABEL}
    excluded = 0
    for r in rows:
        stored = case.dir / r["stored_path"]
        verify, kind = r["verify"], r["kind"]
        if revalidate and stored.is_file():
            res = V.validate(stored, r["name"])
            if res.status != verify or res.kind != kind:
                verify, kind = res.status, res.kind
                from .recover.merge import Item, rank_for  # 再判定（ランクの整合を保つ）
                from .recover.manifest import Candidate

                rank = rank_for(Item(r["stage"], r["image_id"],
                                     Candidate(stored=r["stored_path"], method=r["method"],
                                               orig_path=None if r["method"] == "PhotoRec" else r["name"]),
                                     r["sha256"], r["size"], res))
                case.db.execute("UPDATE recovered_files SET verify=?, kind=?, rank=? WHERE id=?",
                                verify, kind, rank, r["id"])
                r = dict(r, verify=verify, kind=kind, rank=rank)
        if r["rank"] == "X":
            excluded += 1
            continue
        thumb = None
        if kind in V.IMAGE_KINDS and stored.is_file():
            t = thumbs / f"{r['id']}.jpg"
            if t.exists() or _thumbnail(stored, t):
                thumb = f"thumbs/{t.name}"
        files_by_rank[r["rank"]].append(dict(
            id=r["id"], name=r["name"], orig_path=r["orig_path"], size=r["size"],
            kind_label=V.KIND_LABEL.get(kind or "bin", kind or "不明"),
            verify_label=VERIFY_LABEL.get(verify, verify), thumb=thumb))

    rank_rows = [dict(rank=k, label=RANK_LABEL[k], count=len(v), size=sum(f["size"] for f in v))
                 for k, v in files_by_rank.items()]
    sections = [dict(rank=k, label=RANK_LABEL[k], files=v) for k, v in files_by_rank.items()]

    stages = []
    rep_path = case.dir / "stages" / "stage_report.json"
    if rep_path.exists():
        rep = json.loads(rep_path.read_text())
        for st, v in rep.get("stages", {}).items():
            key = "COM" if st.startswith("COM") else st
            stages.append(dict(stage=st, label=STAGES.get(key, st), **v))

    html, pdf_path = reports.render(
        "catalog.html", out_dir / "list.html", pdf=pdf,
        case=case.row, created=datetime.now().strftime("%Y-%m-%d %H:%M"), rank_rows=rank_rows, sections=sections, excluded=excluded,
        stages=stages)
    case.advance("一覧提示")
    case.db.add_event(case.id, "catalog.build", f"html={html.name} pdf={pdf_path.name if pdf_path else '-'}", 0)
    return {"html": html, "pdf": pdf_path, "ranks": {r["rank"]: r["count"] for r in rank_rows},
            "excluded": excluded}
