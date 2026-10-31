"""
古物台帳管理システム（Python版）

同梱ライブラリ（lib/ の PyMySQL）を最優先で読み込めるようにする。
"""
import sys

from . import paths

if paths.LIB_DIR not in sys.path:
    sys.path.insert(0, paths.LIB_DIR)
