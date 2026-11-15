"""案件ごとの暗号化作業領域（LUKS2 コンテナ）。企画書 §3.1-6 / P5。

作業領域は案件ごとの LUKS2 コンテナに置き、案件終了時は「鍵の破棄」で消去する。
  作成: 乱数の鍵ファイル（tmpfs 上）→ コンテナファイル → luksFormat → open → mkfs → mount
  破棄: umount → close → cryptsetup erase（全キースロットを消去＝復号不能）→ 鍵ファイル削除 → コンテナ削除

root が必要なため、このモジュールは「人間が作業機で実行するスクリプト」を生成するだけで、実行しない。
鍵ファイルは RESQ_KEYS（既定 /run/resq-keys：再起動で消える tmpfs）に置く。
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

from .config import Workspace

DEFAULT_KEYS_DIR = "/run/resq-keys"


@dataclass(frozen=True)
class ContainerPaths:
    container: Path
    keyfile: Path
    mapper: str
    mountpoint: Path

    @property
    def mapper_path(self) -> str:
        return f"/dev/mapper/{self.mapper}"


def paths(ws: Workspace, case_id: str) -> ContainerPaths:
    keys = Path(os.environ.get("RESQ_KEYS", DEFAULT_KEYS_DIR))
    return ContainerPaths(container=ws.root / "containers" / f"{case_id}.luks",
                          keyfile=keys / f"{case_id}.key", mapper=f"resq-{case_id}",
                          mountpoint=ws.case_dir(case_id))


def _q(p) -> str:
    return shlex.quote(str(p))


def create_commands(ws: Workspace, case_id: str, size: str) -> list[str]:
    p = paths(ws, case_id)
    return [
        f"install -d -m 700 {_q(p.keyfile.parent)} {_q(p.container.parent)}",
        "umask 077",
        f"head -c 64 /dev/urandom > {_q(p.keyfile)}",
        f"truncate -s {_q(size)} {_q(p.container)}",
        f"cryptsetup luksFormat --type luks2 --batch-mode --key-file {_q(p.keyfile)} {_q(p.container)}",
        f"cryptsetup open --key-file {_q(p.keyfile)} {_q(p.container)} {_q(p.mapper)}",
        f"mkfs.ext4 -q -L {_q(p.mapper[:16])} {_q(p.mapper_path)}",
        f"install -d -m 700 {_q(p.mountpoint)}",
        f"mount {_q(p.mapper_path)} {_q(p.mountpoint)}",
    ]


def destroy_commands(ws: Workspace, case_id: str) -> list[str]:
    p = paths(ws, case_id)
    return [
        f"umount {_q(p.mountpoint)}",
        f"cryptsetup close {_q(p.mapper)}",
        # 全キースロットを消去。鍵ファイルが残っていても、もう復号できない
        f"cryptsetup erase --batch-mode {_q(p.container)}",
        f"rm -f {_q(p.keyfile)}",
        f"rm -f {_q(p.container)}",
    ]


def script(commands: list[str], title: str) -> str:
    body = "\n".join(commands)
    return f"""#!/usr/bin/env bash
# {title}
# resq が生成。作業機で root として人間が実行する（開発機では実行しない）。
set -euo pipefail
{body}
echo "done: {title}"
"""


def write_script(ws: Workspace, case_id: str, kind: str, commands: list[str]) -> Path:
    d = ws.root / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{case_id}-{kind}.sh"
    p.write_text(script(commands, f"{case_id} {kind}"), encoding="utf-8")
    p.chmod(0o700)
    return p


def is_encrypted_workspace(ws: Workspace, case_id: str) -> bool:
    return paths(ws, case_id).container.exists()
