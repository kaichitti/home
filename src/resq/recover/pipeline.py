"""多段復旧の実行制御（S1 → S2 → S5 → S8）。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .. import safety
from ..db import now
from ..image import get_image
from . import merge as merge_mod
from . import partitions, photorec, tsk

DEFAULT_STAGES = ("S1", "S2", "S5")


def run(case, *, image_id: int | None = None, stages: tuple[str, ...] = DEFAULT_STAGES,
        use_testdisk: bool = True, on_stage: Callable[[str], None] | None = None) -> dict:
    row = get_image(case, image_id)
    image = Path(row["path"])
    iid = row["id"]
    safety.assert_source_readonly(image, case.ctx)  # 以降イメージは読むだけ
    base = case.sub("stages") / f"img{iid}"

    def stage_dir(name: str) -> Path:
        d = base / name
        safety.assert_writable_target(d, case_dir=case.dir, source=image)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def record(stage: str, method: str, started: str, found: int, out: Path, note: str = "") -> None:
        case.db.insert("stage_runs", case_id=case.id, image_id=iid, stage=stage, method=method,
                       started_at=started, finished_at=now(), found=found, out_dir=str(out), note=note)

    volumes: list[dict] = []
    if "S1" in stages or "S2" in stages:
        on_stage and on_stage("S1")
        d, t = stage_dir("S1"), now()
        volumes = partitions.find_volumes(image, d, case.ctx, use_testdisk=use_testdisk)
        record("S1", "mmls+TestDisk+bootscan", t, len(volumes), d,
               ", ".join(f"{v['fstype']}@{v['offset']}" for v in volumes))
    if "S2" in stages:
        on_stage and on_stage("S2")
        d, t = stage_dir("S2"), now()
        m = tsk.run(case, iid, image, volumes, d)
        record("S2", "TSK", t, len(m.candidates), d)
    if "S5" in stages:
        on_stage and on_stage("S5")
        d, t = stage_dir("S5"), now()
        m = photorec.run(case, iid, image, d)
        record("S5", "PhotoRec", t, len(m.candidates), d)

    on_stage and on_stage("S8")
    report = merge_mod.merge(case)
    report["volumes"] = volumes
    case.advance("復旧済")
    return report
