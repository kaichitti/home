"""resq-erase（消去ステーション専用 CLI）の実行ファイル用エントリ。Linux のみ。"""
import sys

if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from resq_erase.cli import app  # noqa: E402

app(prog_name="resq-erase")
