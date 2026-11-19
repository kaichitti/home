"""Android：adb で共有ストレージ（写真・動画・ダウンロード等）を吸い出す。

  adb devices -l                                     接続中の端末（持ち主が USB デバッグを許可済み）
  adb -s <シリアル> pull -a /sdcard/DCIM <dir>/DCIM   タイムスタンプを保ったままコピー

アプリの内部データ（LINE のトーク等）は対象外（端末側のバックアップ機能を案内する）。
"""
from __future__ import annotations

from pathlib import Path

from .. import audit, safety
from ..db import now
from ..recover.manifest import Candidate, Manifest
from . import next_stage_dir, require_confirmations

STEPS = [
    "持ち主が端末のロックを解除した",
    "持ち主が開発者向けオプションで USB デバッグを有効にした",
    "持ち主が端末で『この PC からの USB デバッグを許可』した",
    "作業後に USB デバッグを無効に戻すことを持ち主に案内した",
]
DEFAULT_PATHS = ("/sdcard/DCIM", "/sdcard/Pictures", "/sdcard/Movies", "/sdcard/Download", "/sdcard/Documents")


def commands(serial: str, out_dir: Path, paths: tuple[str, ...] = DEFAULT_PATHS) -> list[list[str]]:
    cmds = [["adb", "devices", "-l"]]
    for p in paths:
        cmds.append(["adb", "-s", serial, "pull", "-a", p, str(out_dir / Path(p).name)])
    return cmds


def pull(case, serial: str, confirmed: dict[str, bool], paths: tuple[str, ...] = DEFAULT_PATHS) -> Manifest:
    require_confirmations(STEPS, confirmed)
    stage = next_stage_dir(case)
    out = stage / "files"
    safety.assert_writable_target(out, case_dir=case.dir)
    out.mkdir()
    started = now()
    for cmd in commands(serial, out, paths):
        # 存在しないフォルダは adb が非 0 を返すが、他のフォルダの吸い出しは続ける
        audit.run(cmd, op="mobile.android", ctx=case.ctx, check=False, timeout=None)
    man = Manifest(stage="MOB", image_id=None, method="Android adb", info={"serial": serial, "paths": list(paths)})
    for f in sorted(p for p in out.rglob("*") if p.is_file()):
        rel = f.relative_to(out).as_posix()
        man.candidates.append(Candidate(stored=str(f.relative_to(case.dir)), method="Android adb",
                                        orig_path=f"sdcard/{rel}", path_known=True, deleted=False))
    man.write(stage)
    case.db.insert("stage_runs", case_id=case.id, image_id=None, stage=stage.name, method=man.method,
                   started_at=started, finished_at=now(), found=len(man.candidates), out_dir=str(stage))
    case.db.add_event(case.id, "mobile.android.pull", f"files={len(man.candidates)}", 0)
    return man
