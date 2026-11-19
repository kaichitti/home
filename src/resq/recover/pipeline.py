"""多段復旧の実行制御（企画書 §3.8）。

  S1 パーティション探索 → S2 削除エントリ(TSK) → S3 残骸スキャン → S4 シャドウコピー
  → S5 カービング(PhotoRec) → S6 名前の付け直し → S7 サムネイル → S8 統合・検証
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .. import safety, tools
from ..db import now
from ..image import get_image
from . import merge as merge_mod
from . import partitions, photorec, remnants, rename, thumbs, tsk, vss
from .manifest import Manifest

DEFAULT_STAGES = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
NEEDS_VOLUMES = {"S1", "S2", "S3", "S4"}


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

    def step(name: str) -> bool:
        if name not in stages:
            return False
        missing = tools.missing_for_stage(name)
        if missing:
            # Windows 版など、ツールが入っていない環境ではその段を省略して記録する
            t = now()
            record(name, "（省略）", t, 0, base, "未インストールのため省略: " + ", ".join(missing))
            case.db.add_event(case.id, f"recover.{name}.skipped", ", ".join(missing), None)
            return False
        if on_stage:
            on_stage(name)
        return True

    volumes: list[dict] = []
    if NEEDS_VOLUMES & set(stages):
        if on_stage:
            on_stage("S1")
        d, t = stage_dir("S1"), now()
        volumes = partitions.find_volumes(image, d, case.ctx, use_testdisk=use_testdisk)
        record("S1", "mmls+TestDisk+bootscan", t, len(volumes), d,
               ", ".join(f"{v['fstype']}@{v['offset']}" for v in volumes))
    if step("S2"):
        d, t = stage_dir("S2"), now()
        m = tsk.run(case, iid, image, volumes, d)
        record("S2", "TSK", t, len(m.candidates), d)
    if step("S3"):
        d, t = stage_dir("S3"), now()
        m = remnants.run(case, iid, image, volumes, d)
        record("S3", "残骸スキャン", t, len(m.candidates), d)
    if step("S4"):
        d, t = stage_dir("S4"), now()
        m = vss.run(case, iid, image, volumes, d)
        record("S4", "VSS", t, len(m.candidates), d, str(m.info))
    s5: Manifest | None = None
    if step("S5"):
        d, t = stage_dir("S5"), now()
        s5 = photorec.run(case, iid, image, d)
        record("S5", "PhotoRec", t, len(s5.candidates), d)
    if step("S6"):
        d, t = stage_dir("S6"), now()
        if s5 is None and (base / "S5" / "manifest.json").exists():
            s5 = Manifest.read(base / "S5" / "manifest.json")
        m = rename.run(case, iid, base / "S3", s5 or Manifest("S5", iid, "PhotoRec"), d)
        record("S6", "名前の付け直し", t, len(m.candidates), d)
    if step("S7"):
        d, t = stage_dir("S7"), now()
        m = thumbs.run(case, iid, thumbs.collect_sources(case), d)
        record("S7", "サムネイル", t, len(m.candidates), d)

    if on_stage:
        on_stage("S8")
    report = merge_mod.merge(case)
    report["volumes"] = volumes
    case.advance("復旧済")
    return report
