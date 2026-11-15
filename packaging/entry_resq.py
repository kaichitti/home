"""resq（復旧 CLI）の実行ファイル用エントリ。"""
import sys

if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from resq.cli import app  # noqa: E402

app(prog_name="resq")
