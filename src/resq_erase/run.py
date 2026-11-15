"""E2 実行ラッパ（企画書 §8.5 の安全装置）。

- 対象はシリアル番号で指定する（/dev/sdX のようなデバイス名では指定できない）
- 台帳に登録済み・承諾書ありの媒体だけが対象
- 復旧案件の媒体・ステーション自身のディスク・マウント中（起動ディスク等）のディスクは拒否
- 既定はドライラン（実行予定コマンドの記録のみ）
- 実行には execute=True と、シリアル下 4 桁の手入力（2 段確認）が必要
- 実行直前にもう一度シリアルとデバイスの対応を確かめる（接続順でデバイス名が変わるため）
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from . import exec as ex
from .errors import EraseRefused
from .ledger import Ledger, now
from .probe import Method, Probe

RUNNABLE_STATUSES = ("保管中", "検証不合格")


@dataclass
class Plan:
    media: dict
    probe: Probe
    method: Method
    device: str
    commands: list[list[str]]
    run_id: int


def _walk(dev: dict):
    yield dev
    for ch in dev.get("children") or []:
        yield from _walk(ch)


def _mounts(dev: dict) -> list[str]:
    out = []
    for d in _walk(dev):
        mps = d.get("mountpoints") or ([d["mountpoint"]] if d.get("mountpoint") else [])
        out += [m for m in mps if m]
    return out


def resolve_device(lsblk: dict, serial: str) -> tuple[str, dict]:
    hits = [d for d in lsblk.get("blockdevices", [])
            if (d.get("serial") or "").strip() == serial.strip() and d.get("type", "disk") == "disk"]
    if not hits:
        raise EraseRefused(f"シリアル {serial} のディスクが接続されていません")
    if len(hits) > 1:
        raise EraseRefused(f"シリアル {serial} のディスクが複数見つかりました（同一シリアルの誤認を避けるため中止）")
    return "/dev/" + hits[0]["name"], hits[0]


def check_target(ledger: Ledger, serial: str, lsblk: dict, station_serials: set[str]) -> tuple[dict, str, dict]:
    media = ledger.media_by_serial(serial)
    if media is None:
        raise EraseRefused(f"シリアル {serial} は消去台帳に登録されていません（受付で登録してから）")
    media = dict(media)
    if not media.get("consent_doc"):
        raise EraseRefused("消去承諾書の記録がありません")
    if media["status"] not in RUNNABLE_STATUSES:
        raise EraseRefused(f"媒体の状態が『{media['status']}』のため消去できません")
    reason = ledger.blocked_reason(serial)
    if reason:
        raise EraseRefused(f"このシリアルは消去禁止です（{reason}）")
    if serial.strip() in station_serials:
        raise EraseRefused("消去ステーション自身のディスクです")
    dev, info = resolve_device(lsblk, serial)
    mounts = _mounts(info)
    if mounts:
        raise EraseRefused(f"マウント中のディスクです（起動ディスク等の可能性）: {', '.join(mounts)}")
    return media, dev, info


def plan(ledger: Ledger, serial: str, probe: Probe, method_for: Callable[[Probe, str], Method], *,
         lsblk: dict, station_serials: set[str] = frozenset(), operator: str = "") -> Plan:
    """ドライラン。安全装置をすべて通し、実行予定のコマンドを記録する（実行はしない）。"""
    media, dev, _info = check_target(ledger, serial, lsblk, station_serials)
    method = method_for(probe, dev)
    run_id = ledger.insert("runs", media_id=media["id"], category=method.category or "-", method=method.name,
                           commands=json.dumps(method.commands, ensure_ascii=False), dry_run=1,
                           started_at=now(), finished_at=now(), completion="dry-run", operator=operator)
    for cmd in method.commands:
        ex.run(cmd, ledger=ledger, op="erase.plan", media_id=media["id"], execute=False)
    for b in method.blockers:
        ledger.event("erase.blocker", b, media_id=media["id"], rc=None)
    return Plan(media, probe, method, dev, method.commands, run_id)


def execute(ledger: Ledger, p: Plan, *, confirm_last4: str, get_lsblk: Callable[[], dict],
            station_serials: set[str] = frozenset(), operator: str = "") -> int:
    serial = p.media["serial"]
    if confirm_last4.strip() != serial[-4:]:
        ledger.event("erase.refused", "シリアル下 4 桁の不一致", media_id=p.media["id"], rc=None)
        raise EraseRefused("シリアル下 4 桁が一致しません（媒体ラベルを確認してください）")
    if not p.method.executable:
        raise EraseRefused("この方式は実行できません: " + " / ".join(p.method.blockers or [p.method.name]))
    # 実行直前の再確認（接続し直し等でデバイス名が変わっていないか）
    _media, dev, _ = check_target(ledger, serial, get_lsblk(), station_serials)
    if dev != p.device:
        raise EraseRefused(f"デバイス名が変わりました（{p.device} → {dev}）。もう一度ドライランからやり直してください")
    if ex.station_id() is None:
        raise EraseRefused("このマシンは消去ステーションとして登録されていません（消去コマンドを実行しません）")
    run_id = ledger.insert("runs", media_id=p.media["id"], category=p.method.category, method=p.method.name,
                           commands=json.dumps(p.commands, ensure_ascii=False), dry_run=0, started_at=now(),
                           operator=operator)
    completion = "commands-ok"
    for cmd in p.commands:
        r = ex.run(cmd, ledger=ledger, op="erase.exec", media_id=p.media["id"], execute=True)
        if r is None or r.returncode != 0:
            completion = f"failed rc={None if r is None else r.returncode}"
            break
    ledger.execute("UPDATE runs SET finished_at=?, completion=? WHERE id=?", now(), completion, run_id)
    return run_id
