@echo off
chcp 65001 > nul
rem DetCut のセットアップ（初回のみ）: 仮想環境を作って必要なライブラリを入れます
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe tools\make_sample_media.py --assets-only
echo.
echo 文字起こし（自動テロップ）も使う場合:  .venv\Scripts\python.exe -m pip install faster-whisper
echo GUIへのドラッグ＆ドロップを使う場合: .venv\Scripts\python.exe -m pip install tkinterdnd2
pause
