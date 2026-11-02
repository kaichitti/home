@echo off
chcp 65001 > nul
rem DetCut GUI を起動します。動画ファイルをこの .bat にドラッグ＆ドロップしても開けます
cd /d "%~dp0"
start "" .venv\Scripts\pythonw.exe -m detcut gui %*
