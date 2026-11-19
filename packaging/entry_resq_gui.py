"""resq-gui（復旧のデスクトップアプリ）の実行ファイル用エントリ。ブラウザもネットワークも使わない。"""
import sys

from resq.gui.app import main

sys.exit(main())
