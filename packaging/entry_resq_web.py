"""resq-web（管理画面を起動してブラウザで開く）の実行ファイル用エントリ。"""
import sys

if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from resq.web import launch_main  # noqa: E402

launch_main()
