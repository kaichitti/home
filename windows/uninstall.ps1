#Requires -Version 5.1
<#
.SYNOPSIS
  DroidFork の Windows 側の設定を元に戻す。

.DESCRIPTION
  - .wslconfig から DroidFork のカーネルの指定を外す（ほかの設定はそのまま）
  - スタートメニューの「DroidFork」を消す
  - -RemoveDistro を付けると、WSL の DroidFork 環境（仮想端末のデータを含む）も削除する
#>
[CmdletBinding()]
param(
    [string]$Distro = "DroidFork",
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA "DroidFork"),
    [switch]$RemoveDistro
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wslconfig.ps1")   # .wslconfig を編集する関数

$env:WSL_UTF8 = "1"
$kernelDir = Join-Path $DataDir "kernel"
$wslconfig = Join-Path $env:USERPROFILE ".wslconfig"
if (Test-Path $wslconfig) {
    $content = [IO.File]::ReadAllText($wslconfig)
    $current = Get-WslConfigKernel $content
    if ($current -and $current.ToLower().StartsWith($kernelDir.ToLower())) {
        [IO.File]::WriteAllText($wslconfig, (Remove-WslConfigKernel $content $current), (New-Object Text.UTF8Encoding($false)))
        Write-Host "==> .wslconfig から DroidFork のカーネルの指定を外しました"
    }
}
& wsl.exe --shutdown | Out-Null

if ($RemoveDistro) {
    & wsl.exe --unregister $Distro | Out-Null
    Write-Host "==> WSL の環境「$Distro」を削除しました"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $DataDir
} else {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $kernelDir
    Write-Host "==> WSL の環境「$Distro」は残しました（削除するには: wsl --unregister $Distro）"
}
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath("Programs")) "DroidFork.lnk")
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "DroidForkSetup" -ErrorAction SilentlyContinue
