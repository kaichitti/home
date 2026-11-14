"""外部コマンド実行の唯一の窓口。

- すべての外部コマンドはこの run() を通す（直接 subprocess を呼ばない）。
- 実行内容・終了コード・所要時間を監査ログ（JSONL）と案件の events テーブルに残す。
- 原本を破壊しうるプログラムは、復旧ビルドでは呼び出し自体を拒否する。
- 実デバイス（/dev/...）を含む引数は allow_device=True を明示したときだけ許可する。
- secrets に渡した文字列（回復キー等）はログ・例外メッセージから伏字にする。
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Protocol, Sequence

from .errors import CommandError, SafetyError

# 復旧ビルドでは決して呼ばないプログラム（企画書 §3.3 / §4.3 / §8.2）
FORBIDDEN_PROGRAMS = frozenset({
    "dd", "dcfldd", "dc3dd", "wipefs", "fdisk", "sfdisk", "cfdisk", "parted", "gdisk", "sgdisk",
    "blkdiscard", "shred", "hdparm", "nvme", "nwipe", "sg_sanitize", "sg_format", "mount",
    "umount", "losetup", "badblocks", "e2fsck", "fsck", "chkdsk", "ntfsfix", "scrub", "wipe",
})
FORBIDDEN_PREFIXES = ("mkfs", "fsck.", "mkswap")

REDACTED = "***"


class EventSink(Protocol):
    def add_event(self, case_id: str | None, op: str, command: str, rc: int | None,
                  detail: dict | None = None) -> None: ...


@dataclass
class AuditContext:
    """監査ログの出力先。case_id がある場合は案件の events にも記録する。"""
    log_path: Path | None = None
    sink: EventSink | None = None
    case_id: str | None = None
    extra_logs: list[Path] = field(default_factory=list)


def _redact(text: str, secrets: Sequence[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, REDACTED)
    return text


def check_program(argv: Sequence[str]) -> None:
    if not argv:
        raise SafetyError("空のコマンドは実行できません")
    prog = os.path.basename(str(argv[0]))
    if prog in FORBIDDEN_PROGRAMS or prog.startswith(FORBIDDEN_PREFIXES):
        raise SafetyError(f"復旧ビルドでは '{prog}' を実行できません（原本破壊のおそれ）")


def check_device_args(argv: Sequence[str], allow_device: bool) -> None:
    if allow_device:
        return
    for a in argv:
        if "/dev/" in str(a):
            raise SafetyError(
                "実デバイスを参照する引数は allow_device=True を明示した処理でのみ使えます: "
                f"{a}")


def _write_log(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(argv: Sequence[str | os.PathLike], *, op: str, ctx: AuditContext | None = None,
        cwd: Path | None = None, timeout: float | None = None,
        stdout_path: Path | None = None, input_text: str | None = None,
        secrets: Sequence[str] = (), allow_device: bool = False,
        check: bool = True, ok_codes: Sequence[int] = (0,),
        stream: IO[str] | None = None) -> subprocess.CompletedProcess:
    """外部コマンドを実行し、記録する。

    stdout_path を指定した場合、標準出力はファイルに書き出す（大きなバイナリ出力向け）。
    stream を指定した場合、標準出力を逐次 stream に流す（進捗表示向け）。
    """
    args = [str(a) for a in argv]
    check_program(args)
    check_device_args(args, allow_device)
    shown = _redact(shlex.join(args), secrets)

    started = time.monotonic()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rc: int | None = None
    err_text = ""
    try:
        if stdout_path is not None:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            with stdout_path.open("wb") as out:
                proc = subprocess.run(args, cwd=cwd, timeout=timeout, stdout=out,
                                      stderr=subprocess.PIPE, input=input_text.encode() if input_text else None)
            result = subprocess.CompletedProcess(args, proc.returncode, b"", proc.stderr)
            err_text = proc.stderr.decode(errors="replace")
        elif stream is not None:
            proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE if input_text else subprocess.DEVNULL,
                                    text=True, errors="replace")
            if input_text:
                assert proc.stdin
                proc.stdin.write(input_text)
                proc.stdin.close()
            chunks = []
            assert proc.stdout
            for line in proc.stdout:
                chunks.append(line)
                stream.write(_redact(line, secrets))
            proc.wait(timeout=timeout)
            result = subprocess.CompletedProcess(args, proc.returncode, "".join(chunks), "")
        else:
            result = subprocess.run(args, cwd=cwd, timeout=timeout, capture_output=True, text=True,
                                    errors="replace", input=input_text)
            err_text = result.stderr or ""
        rc = result.returncode
    except FileNotFoundError as e:
        rc = 127
        err_text = str(e)
        raise CommandError(f"コマンドが見つかりません: {args[0]}") from None
    except subprocess.TimeoutExpired:
        err_text = "timeout"
        raise CommandError(f"タイムアウト: {shown}") from None
    finally:
        record = {
            "ts": ts, "case_id": ctx.case_id if ctx else None, "op": op, "command": shown,
            "rc": rc, "elapsed_s": round(time.monotonic() - started, 3),
            "stderr_tail": _redact(err_text[-500:], secrets),
        }
        if ctx:
            for p in [ctx.log_path, *ctx.extra_logs]:
                if p:
                    _write_log(p, record)
            if ctx.sink and ctx.case_id:
                ctx.sink.add_event(ctx.case_id, op, shown, rc,
                                   {"elapsed_s": record["elapsed_s"], "stderr_tail": record["stderr_tail"]})

    if check and rc not in ok_codes:
        raise CommandError(f"コマンド失敗 (rc={rc}): {shown}\n{_redact(err_text[-800:], secrets)}")
    if secrets and isinstance(result.stdout, str):
        result.stdout = _redact(result.stdout, secrets)
    if secrets and isinstance(result.stderr, str):
        result.stderr = _redact(result.stderr, secrets)
    return result
