"""共通ユーティリティ：外部コマンドの実行、表示、サイズ表記、JSON保存、ロックなど。"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence, TextIO


class DroidForkError(Exception):
    """利用者に見せるエラー。hint には次に何をすればよいかを書く。"""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


class CommandError(DroidForkError):
    def __init__(self, result: CommandResult) -> None:
        lines = [line for line in result.output.strip().splitlines() if line.strip()]
        message = f"コマンドが失敗しました（終了コード {result.returncode}）: {shlex.join(result.args)}"
        if lines:
            message += "\n" + "\n".join("  " + line for line in lines[-6:])
        super().__init__(message)
        self.result = result


INSTALL_HINTS = {
    "adb": "Android SDK Platform-Tools を入れてください（例: sudo apt install adb）。",
    "docker": "Docker Engine を入れてください（https://docs.docker.com/engine/install/）。",
    "scrcpy": "scrcpy を入れてください（例: sudo apt install scrcpy）。",
}


def not_found_error(binary: str) -> DroidForkError:
    return DroidForkError(
        f"コマンドが見つかりません: {binary}",
        hint=INSTALL_HINTS.get(os.path.basename(binary)),
    )


class Runner:
    """外部コマンドの実行窓口。テストでは同じメソッドを持つ偽物に差し替える。"""

    def __init__(self, console: "Console | None" = None) -> None:
        self.console = console

    def _log(self, argv: list[str]) -> None:
        if self.console is not None:
            self.console.debug("$ " + shlex.join(argv))

    def run(
        self,
        args: Sequence[Any],
        *,
        check: bool = True,
        timeout: float | None = None,
        input: str | None = None,
    ) -> CommandResult:
        argv = [str(a) for a in args]
        self._log(argv)
        # 入力を渡さないときは stdin を閉じる（adb shell が端末の入力を奪わないように）
        stdin_kw: dict[str, Any] = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                **stdin_kw,
            )
        except FileNotFoundError:
            raise not_found_error(argv[0]) from None
        except subprocess.TimeoutExpired:
            raise DroidForkError(
                f"コマンドが {timeout:g} 秒以内に終わりませんでした: {shlex.join(argv)}"
            ) from None
        result = CommandResult(argv, proc.returncode, proc.stdout or "", proc.stderr or "")
        if check and not result.ok:
            raise CommandError(result)
        return result

    def passthrough(self, args: Sequence[Any]) -> int:
        """出力を取り込まずに端末へそのまま流す（docker logs -f など）。"""
        argv = [str(a) for a in args]
        self._log(argv)
        try:
            return subprocess.call(argv)
        except FileNotFoundError:
            raise not_found_error(argv[0]) from None

    def spawn(self, args: Sequence[Any]) -> None:
        """終了を待たずに別プロセスとして起動する（scrcpy の画面など）。"""
        argv = [str(a) for a in args]
        self._log(argv)
        try:
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            raise not_found_error(argv[0]) from None

    def which(self, name: str) -> str | None:
        return shutil.which(name)


class Console:
    """進行状況は標準エラーへ、結果（表など）は標準出力へ書く。"""

    def __init__(
        self,
        out: TextIO | None = None,
        err: TextIO | None = None,
        *,
        verbose: bool = False,
        quiet: bool = False,
    ) -> None:
        self.out = out if out is not None else sys.stdout
        self.err = err if err is not None else sys.stderr
        self.verbose = verbose
        self.quiet = quiet
        self._lock = threading.Lock()

    def _write(self, stream: TextIO, text: str) -> None:
        with self._lock:
            stream.write(text + "\n")
            stream.flush()

    def print(self, text: str = "") -> None:
        self._write(self.out, text)

    def step(self, text: str) -> None:
        if not self.quiet:
            self._write(self.err, f"==> {text}")

    def info(self, text: str) -> None:
        if not self.quiet:
            self._write(self.err, f"    {text}")

    def warn(self, text: str) -> None:
        self._write(self.err, f"警告: {text}")

    def debug(self, text: str) -> None:
        if self.verbose:
            self._write(self.err, text)


# ---- 表の整形（全角文字の幅を考慮する） ----

def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def format_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    cells = [["" if c is None else str(c) for c in row] for row in rows]
    widths = [display_width(h) for h in headers]
    for row in cells:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))
    lines = ["  ".join(_pad(h, widths[i]) for i, h in enumerate(headers)).rstrip()]
    for row in cells:
        lines.append("  ".join(_pad(c, widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(lines)


# ---- サイズ表記 ----

_UNITS = {
    "b": 1,
    "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4, "pb": 1000**5,
    "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4, "pib": 1024**5,
}
_SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)\s*$")


def parse_size(text: str | None) -> int | None:
    """docker が出す "1.2GB" や "512MiB" をバイト数にする。読めなければ None。"""
    if text is None:
        return None
    m = _SIZE_RE.match(text)
    if not m:
        return None
    unit = (m.group(2) or "B").lower()
    if unit not in _UNITS:
        return None
    return int(round(float(m.group(1)) * _UNITS[unit]))


def format_bytes(n: int | float | None) -> str:
    if n is None:
        return "不明"
    n = float(n)
    if abs(n) < 1024:
        return f"{int(n)} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        n /= 1024
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TiB"  # pragma: no cover


# ---- ファイル・時刻・名前 ----

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DroidForkError(f"ファイルを読めません: {path}: {exc}") from None


def write_json(path: Path, data: Any) -> None:
    """途中で落ちても壊れたファイルが残らないよう、一時ファイルに書いてから置き換える。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """同時に複数の droidfork が台数やポートを割り当てないための排他ロック。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")


def validate_name(name: str, what: str = "名前") -> str:
    if not NAME_RE.match(name):
        raise DroidForkError(
            f"{what}「{name}」は使えません。",
            hint="英小文字・数字・「-」「_」「.」で、40文字以内にしてください（先頭は英数字）。",
        )
    return name


def slugify(text: str, fallback: str = "device") -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:32].strip("-") or fallback


# ---- ネットワーク ----

def is_port_free(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())
