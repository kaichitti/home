@echo off
chcp 65001 > nul
rem 動画をこの .bat にドラッグ＆ドロップすると、既定プリセットで .aup2 を書き出します
cd /d "%~dp0"
.venv\Scripts\python.exe -m detcut run %* -p presets\gadget_review.yaml
pause
