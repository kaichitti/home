"""消去ステーションの外部コマンド実行の唯一の窓口。

- 読み取りだけのコマンド（識別・状態確認）はそのまま実行して記録する
- 消去コマンドは、消去ステーションであること（マーカーファイルと環境変数の一致）と
  呼び出し側の明示的な execute=True が揃ったときだけ実行する。それ以外は実行せずに記録だけ残す
開発機・復旧作業機では消去コマンドは決して実行されない。
"""
from __future__ import annotations

import locale
import os
import shlex
import subprocess
from pathlib import Path
from typing import Sequence

from .errors import EraseRefused
from .ledger import Ledger

STATION_MARKER = Path(os.environ.get("RESQ_ERASE_STATION_MARKER", "/etc/resq-erase-station"))
READ_ONLY_PROGRAMS = {"lsblk", "smartctl", "findmnt", "blockdev", "sg_readcap"}
# 消去系。サブコマンド・オプションで読み取りか書き込みかが変わるものは is_destructive で判定
ERASE_PROGRAMS = {"hdparm", "nvme", "nwipe", "sg_sanitize", "sg_format", "blkdiscard"}


def station_id() -> str | None:
    """このマシンが消去ステーションならその ID。マーカーと環境変数の両方が一致したときだけ。"""
    env = os.environ.get("RESQ_ERASE_STATION_ID")
    try:
        marker = STATION_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return env if env and env == marker else None


def is_destructive(argv: Sequence[str]) -> bool:
    prog = os.path.basename(argv[0])
    args = list(argv[1:])
    if prog == "hdparm":
        # 読み取り: -I（識別）/ -N（HPA の表示のみ）/ --sanitize-status / --dco-identify
        for i, a in enumerate(args):
            if a.startswith("--sanitize-") and a != "--sanitize-status":
                return True
            if a.startswith("--security-") and a != "--security-help":
                return True
            if a.startswith("--dco-") and a != "--dco-identify":
                return True
            if a == "-N" and i + 1 < len(args) and not args[i + 1].startswith("/"):
                return True  # -N p<セクタ数> は HPA の変更
        return False
    if prog == "nvme":
        return bool(args) and args[0] in ("sanitize", "format")
    return prog in ERASE_PROGRAMS


def run(argv: Sequence[str], *, ledger: Ledger, op: str, media_id: int | None = None, execute: bool = False,
        timeout: float | None = None) -> subprocess.CompletedProcess | None:
    args = [str(a) for a in argv]
    shown = shlex.join(args)
    destructive = is_destructive(args)
    if destructive:
        if not execute:
            ledger.event(f"{op}.dryrun", shown, media_id=media_id, rc=None)
            return None
        sid = station_id()
        if sid is None:
            ledger.event(f"{op}.refused", f"not an erase station: {shown}", media_id=media_id, rc=None)
            raise EraseRefused("このマシンは消去ステーションとして登録されていません（消去コマンドを実行しません）")
    elif os.path.basename(args[0]) not in READ_ONLY_PROGRAMS | ERASE_PROGRAMS:
        raise EraseRefused(f"許可されていないコマンドです: {args[0]}")
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding=locale.getencoding(),
                           errors="replace", timeout=timeout)
    except FileNotFoundError:
        ledger.event(op, f"not found: {shown}", media_id=media_id, rc=127)
        raise
    ledger.event(op, shown + (f"\n{p.stderr[-300:]}" if p.returncode else ""), media_id=media_id,
                 rc=p.returncode)
    return p
