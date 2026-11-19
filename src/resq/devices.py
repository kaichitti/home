"""接続中のディスクの一覧（読み取りのみ。Linux の作業機用）。

lsblk の出力を読むだけで、デバイスには一切書き込まない。Windows では空の一覧を返す
（Windows 版は媒体からのイメージ化を行わないため）。
"""
from __future__ import annotations

import json
import sys

from . import audit, tools

LSBLK_COLS = "NAME,PATH,SIZE,MODEL,SERIAL,TRAN,ROTA,RO,RM,TYPE,MOUNTPOINTS"


def list_disks(ctx: audit.AuditContext | None = None) -> list[dict]:
    if not sys.platform.startswith("linux") or not tools.available("lsblk"):
        return []
    r = audit.run(["lsblk", "-J", "-b", "-o", LSBLK_COLS], op="devices.list", ctx=ctx, check=False)
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    out = []
    for d in data.get("blockdevices", []):
        if d.get("type") != "disk":
            continue
        mounts = []
        stack = [d]
        while stack:
            x = stack.pop()
            mounts += [m for m in (x.get("mountpoints") or []) if m]
            stack += x.get("children") or []
        out.append({"path": d.get("path") or f"/dev/{d['name']}", "size": int(d.get("size") or 0),
                    "model": (d.get("model") or "").strip(), "serial": (d.get("serial") or "").strip(),
                    "tran": d.get("tran") or "", "ro": d.get("ro") in (True, 1, "1"), "mounts": mounts})
    return out
