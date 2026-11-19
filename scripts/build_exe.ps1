# Windows 向けの実行ファイル（resq.exe / resq-gui.exe）を作る。
# 使い方（PowerShell）: .\scripts\build_exe.ps1 [-Fixtures <フィクスチャのフォルダ>]
param([string]$Fixtures = "fixtures")
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$version = (Select-String -Path src/resq/__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
python -m PyInstaller packaging/resq.spec --distpath dist/bin --workpath build/pyi --noconfirm --log-level WARN
if (Test-Path (Join-Path $Fixtures "expected.json")) {
  python scripts/smoke_exe.py dist/bin $Fixtures
  if ($LASTEXITCODE -ne 0) { throw "smoke test failed" }
} else {
  Write-Host "フィクスチャがないため動作確認を省略（Linux で ./scripts/make_fixtures.sh を実行して用意）"
}
$stage = "build/pkg/resq-$version-windows-x64"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item dist/bin/resq.exe, dist/bin/resq-gui.exe, packaging/README-windows.txt $stage
Compress-Archive -Path "$stage/*" -DestinationPath "dist/resq-$version-windows-x64.zip" -Force
Get-FileHash "dist/resq-$version-windows-x64.zip" -Algorithm SHA256 | Format-List
