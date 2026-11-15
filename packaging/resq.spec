# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller ビルド定義（1 ファイルの実行ファイル）。

  Linux  : dist/bin/resq, resq-web, resq-erase
  Windows: dist/bin/resq.exe, resq-web.exe（消去ステーションは Linux 専用のため作らない）

復旧の実行ファイルには resq_erase を含めない（企画書 §8.2）。
使い方: python -m PyInstaller packaging/resq.spec --distpath dist/bin --workpath build/pyi --noconfirm
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
PKG = ROOT / "packaging"
IS_WIN = sys.platform == "win32"

RESQ_DATAS = [
    (str(SRC / "resq" / "reports" / "templates"), "resq/reports/templates"),
    (str(SRC / "resq" / "web" / "templates"), "resq/web/templates"),
]
ERASE_DATAS = [(str(SRC / "resq_erase" / "templates"), "resq_erase/templates")]

HIDDEN = collect_submodules("uvicorn") + ["python_multipart", "multipart", "olefile"]
EXCLUDES = ["tkinter", "pytest", "IPython"]

if IS_WIN:
    # WeasyPrint は Windows では GTK/Pango の DLL が必要なため同梱しない（帳票は HTML で出力）
    PDF_DATAS, PDF_HIDDEN, PDF_EXCLUDES = [], [], ["weasyprint"]
else:
    PDF_DATAS = collect_data_files("weasyprint") + collect_data_files("pyphen")
    PDF_HIDDEN = collect_submodules("weasyprint")
    PDF_EXCLUDES = []


def build(name, entry, datas, hidden, excludes):
    a = Analysis(
        [str(PKG / entry)],
        pathex=[str(SRC)],
        datas=datas,
        hiddenimports=hidden,
        excludes=excludes,
        noarchive=False,
    )
    pyz = PYZ(a.pure)
    return EXE(pyz, a.scripts, a.binaries, a.datas, [], name=name, console=True, upx=False,
               strip=False, debug=False)


build("resq", "entry_resq.py", RESQ_DATAS + PDF_DATAS, HIDDEN + PDF_HIDDEN,
      EXCLUDES + PDF_EXCLUDES + ["resq_erase"])
build("resq-web", "entry_resq_web.py", RESQ_DATAS + PDF_DATAS, HIDDEN + PDF_HIDDEN,
      EXCLUDES + PDF_EXCLUDES + ["resq_erase"])
if not IS_WIN:
    build("resq-erase", "entry_resq_erase.py", RESQ_DATAS + ERASE_DATAS + PDF_DATAS,
          HIDDEN + PDF_HIDDEN + ["qrcode", "qrcode.image.pil"], EXCLUDES)
