"""商用エンジン（DMDE Professional / R-Studio Technician 等）の書き出し結果の取り込み（P3b）。

書き出しフォルダを案件ディレクトリ内にコピーし、フォルダ構造を元パスとして扱う。
取り込み後は S8 の統合に混ざる。

注意: 顧客向けの復旧に使えるのは、利用規約で業務利用が許可された版のみ（企画書 §3.8）。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import safety
from ..db import now
from ..errors import ResqError
from .manifest import Candidate, Manifest

ALLOWED_ENGINES = {"DMDE": "DMDE Professional", "R-Studio": "R-Studio Technician"}


def ingest(case, folder: Path, *, engine: str, image_id: int | None = None,
           license_note: str | None = None) -> Manifest:
    if engine not in ALLOWED_ENGINES:
        raise ResqError(f"未登録のエンジンです: {engine}（登録済み: {', '.join(ALLOWED_ENGINES)}）")
    folder = folder.resolve()
    if not folder.is_dir():
        raise ResqError(f"フォルダが見つかりません: {folder}")
    base = case.sub("stages") / f"img{image_id or 0}"
    n = len(list(base.glob("COM*"))) + 1 if base.exists() else 1
    stage_dir = base / f"COM{n}"
    files_dir = stage_dir / "files"
    safety.assert_writable_target(files_dir, case_dir=case.dir)
    started = now()
    man = Manifest(stage="COM", image_id=image_id, method=f"商用:{engine}",
                   info={"engine": ALLOWED_ENGINES[engine], "source_folder": str(folder),
                         "license_note": license_note})
    for src in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = src.relative_to(folder).as_posix()
        dest = safety.safe_join(files_dir, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        man.candidates.append(Candidate(stored=str(dest.relative_to(case.dir)), method=f"商用:{engine}",
                                        orig_path=rel, path_known=True))
    man.write(stage_dir)
    case.db.insert("stage_runs", case_id=case.id, image_id=image_id, stage=stage_dir.name,
                   method=man.method, started_at=started, finished_at=now(), found=len(man.candidates),
                   out_dir=str(stage_dir))
    case.db.add_event(case.id, "recover.ingest", f"{engine} {folder} files={len(man.candidates)}", 0)
    return man
