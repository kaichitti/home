"""iPhone：libimobiledevice の idevicebackup2 でバックアップを取り、カメラロールを取り出す。

  idevice_id -l                                 接続中の端末の UDID
  ideviceinfo -u <UDID> -k ProductType          機種
  idevicebackup2 -u <UDID> backup --full <dir>  フルバックアップ（持ち主が端末で信頼を許可）

バックアップは <dir>/<UDID>/ に Manifest.db（SQLite）と、fileID の先頭 2 文字のフォルダに分かれた
実ファイルで構成される。暗号化バックアップの場合は持ち主にバックアップ用パスワードの入力を求める
必要があり、本ツールでは中身を解析しない（手順で案内）。
"""
from __future__ import annotations

import plistlib
import shutil
import sqlite3
from pathlib import Path

from .. import audit, safety
from ..db import now
from ..errors import ResqError
from ..recover.manifest import Candidate, Manifest
from . import next_stage_dir, require_confirmations

STEPS = [
    "持ち主が端末のロックを解除した",
    "持ち主が端末で『このコンピュータを信頼』を許可した",
    "持ち主にバックアップの暗号化の有無を確認した",
]
MEDIA_DOMAINS = ("CameraRollDomain", "MediaDomain")
MEDIA_PREFIXES = ("Media/DCIM/", "Media/PhotoData/Mutations/")


def commands(udid: str, out_dir: Path) -> list[list[str]]:
    return [
        ["idevice_id", "-l"],
        ["ideviceinfo", "-u", udid, "-k", "ProductType"],
        ["idevicebackup2", "-u", udid, "backup", "--full", str(out_dir)],
    ]


def backup(case, udid: str, confirmed: dict[str, bool]) -> Path:
    require_confirmations(STEPS, confirmed)
    stage = next_stage_dir(case)
    out = stage / "backup"
    safety.assert_writable_target(out, case_dir=case.dir)
    out.mkdir()
    for cmd in commands(udid, out):
        audit.run(cmd, op="mobile.ios", ctx=case.ctx, timeout=None)
    return out


def is_encrypted(backup_root: Path) -> bool:
    p = backup_root / "Manifest.plist"
    if not p.exists():
        return False
    with open(p, "rb") as fh:
        return bool(plistlib.load(fh).get("IsEncrypted"))


def find_backup_root(backup_dir: Path) -> Path:
    for p in [backup_dir, *sorted(backup_dir.iterdir())] if backup_dir.is_dir() else []:
        if (p / "Manifest.db").exists():
            return p
    raise ResqError(f"Manifest.db が見つかりません: {backup_dir}")


def extract_camera_roll(case, backup_dir: Path, stage_dir: Path | None = None) -> Manifest:
    root = find_backup_root(backup_dir)
    if is_encrypted(root):
        raise ResqError("暗号化バックアップです。持ち主にバックアップの暗号化を一時的に解除してもらうか、"
                        "パスワードを入力してもらう手順に切り替えてください")
    stage_dir = stage_dir or backup_dir.parent
    files_dir = stage_dir / "files"
    started = now()
    man = Manifest(stage="MOB", image_id=None, method="iOS バックアップ", info={"backup": str(root)})
    con = sqlite3.connect(f"file:{root / 'Manifest.db'}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT fileID, domain, relativePath FROM Files WHERE flags=1").fetchall()
    finally:
        con.close()
    for file_id, domain, rel in rows:
        if domain not in MEDIA_DOMAINS or not rel.startswith(MEDIA_PREFIXES):
            continue
        blob = root / file_id[:2] / file_id
        if not blob.is_file():
            continue
        orig = rel[len("Media/"):]
        dest = safety.safe_join(files_dir, orig)
        safety.assert_writable_target(dest, case_dir=case.dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(blob, dest)
        man.candidates.append(Candidate(stored=str(dest.relative_to(case.dir)), method="iOS バックアップ",
                                        orig_path=orig, path_known=True, deleted=False,
                                        extra={"domain": domain}))
    man.write(stage_dir)
    case.db.insert("stage_runs", case_id=case.id, image_id=None, stage=stage_dir.name, method=man.method,
                   started_at=started, finished_at=now(), found=len(man.candidates), out_dir=str(stage_dir))
    case.db.add_event(case.id, "mobile.ios.extract", f"files={len(man.candidates)}", 0)
    return man
