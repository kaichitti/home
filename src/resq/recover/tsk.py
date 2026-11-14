"""S2 削除エントリ（The Sleuth Kit）。

fls -r -p で全エントリ（削除済み含む）を列挙し、icat -r で 1 件ずつ取り出す。
名前・フォルダ付きで戻る最良の段。生存ファイルも取り出す（起動しない PC からの取り出しを兼ねる）。
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import audit, safety
from .manifest import Candidate, Manifest

FLS_LINE = re.compile(r"^(\S)/(\S)\s+(\*\s+)?([\d-]+)(\(realloc\))?:\t(.*)$")
ORPHAN = "$OrphanFiles/"


def parse_fls(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        m = FLS_LINE.match(line)
        if not m:
            continue
        name_t, meta_t, star, inode, realloc, path = m.groups()
        rows.append({"name_type": name_t, "meta_type": meta_t, "deleted": bool(star),
                     "inode": inode, "realloc": bool(realloc), "path": path})
    return rows


def _is_regular(row: dict) -> bool:
    if "(Volume Label Entry)" in row["path"]:
        return False
    if row["name_type"] in ("v", "V", "d") or row["meta_type"] in ("v", "V", "d"):
        return False
    return row["meta_type"] == "r" or (row["name_type"] in ("r", "-") and row["meta_type"] in ("r", "-"))


def run(case, image_id: int, image: Path, volumes: list[dict], stage_dir: Path) -> Manifest:
    ctx = case.ctx
    man = Manifest(stage="S2", image_id=image_id, method="TSK")
    for vol in volumes:
        off = vol["offset"]
        vdir = stage_dir / f"vol{off}"
        out = audit.run(["fls", "-r", "-p", "-o", str(off), image], op="recover.S2.fls", ctx=ctx, check=False)
        rows = [r for r in parse_fls(out.stdout) if _is_regular(r)]
        for r in rows:
            if r["realloc"]:
                continue  # 再割り当て済み＝中身は別ファイル。旧ファイルとしては戻らない
            path = r["path"]
            orphan = path.startswith(ORPHAN)
            rel = path[len(ORPHAN):] if orphan else path
            dest = safety.safe_join(vdir, rel)
            if dest.exists():
                dest = dest.with_name(f"{dest.name}~{r['inode']}")
            safety.assert_writable_target(dest, case_dir=case.dir, source=image)
            dest.parent.mkdir(parents=True, exist_ok=True)
            audit.run(["icat", "-r", "-o", str(off), image, r["inode"]], op="recover.S2.icat", ctx=ctx,
                      stdout_path=dest, check=False, ok_codes=(0, 1))
            man.candidates.append(Candidate(
                stored=str(dest.relative_to(case.dir)), method="TSK", orig_path=rel,
                path_known=not orphan, deleted=r["deleted"], volume_offset=off,
                extra={"inode": r["inode"], "fstype": vol.get("fstype")}))
    man.write(stage_dir)
    return man
