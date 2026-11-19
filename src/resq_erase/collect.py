"""識別用の情報を集める（読み取りのみ）。CLI とデスクトップアプリで共用。"""
from __future__ import annotations

import json
from pathlib import Path

from . import exec as ex
from . import run as run_mod
from .ledger import Ledger

LSBLK_COLS = "NAME,SERIAL,MODEL,SIZE,TRAN,ROTA,RM,TYPE,MOUNTPOINTS"


def lsblk_live(lg: Ledger) -> dict:
    r = ex.run(["lsblk", "-J", "-b", "-o", LSBLK_COLS], ledger=lg, op="probe.lsblk")
    return json.loads(r.stdout)


def collect(lg: Ledger, serial: str, mock_dir: Path | None) -> tuple[dict, dict]:
    """識別用の出力を集める（読み取りのみ）。mock_dir があればそこから読む（訓練・テスト用）。"""
    def mock(name: str):
        p = mock_dir / name if mock_dir else None
        if p and p.exists():
            return json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else p.read_text(encoding="utf-8")
        return None

    if mock_dir:
        lsblk = mock("lsblk.json") or {"blockdevices": []}
        return lsblk, {"smartctl": mock("smartctl.json"), "hdparm_i": mock("hdparm_I.txt"),
                       "hdparm_n": mock("hdparm_N.txt"), "nvme_id": mock("nvme_id.json")}
    lsblk = lsblk_live(lg)
    dev, info = run_mod.resolve_device(lsblk, serial)
    outs: dict = {}
    r = ex.run(["smartctl", "-j", "-a", dev], ledger=lg, op="probe.smartctl")
    outs["smartctl"] = json.loads(r.stdout) if r and r.stdout.strip().startswith("{") else None
    if (info.get("tran") or "") == "nvme":
        r = ex.run(["nvme", "id-ctrl", dev, "-o", "json"], ledger=lg, op="probe.nvme")
        outs["nvme_id"] = json.loads(r.stdout) if r and r.returncode == 0 else None
    else:
        r = ex.run(["hdparm", "-I", dev], ledger=lg, op="probe.hdparm")
        outs["hdparm_i"] = r.stdout if r else None
        r = ex.run(["hdparm", "-N", dev], ledger=lg, op="probe.hpa")
        outs["hdparm_n"] = r.stdout if r else None
    return lsblk, outs




def device_size(lg: Ledger, target: str) -> int:
    """検証対象の大きさ。デバイスなら lsblk から、イメージファイルならファイルの大きさ。"""
    if target.startswith("/dev/"):
        return int(next((d.get("size") for d in lsblk_live(lg)["blockdevices"]
                         if "/dev/" + d["name"] == target), 0) or 0)
    return Path(target).stat().st_size
