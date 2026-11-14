#Requires -Version 5.1
<#
.SYNOPSIS
  DroidFork の管理画面を開く（スタートメニューの「DroidFork」から呼ばれる）。

.DESCRIPTION
  WSL の DroidFork 環境で `droidfork ui` を起動し、Windows のブラウザで開く。
  すでに起動していれば、ブラウザで開くだけにする。
  URL のトークンはこのユーザーだけが読める場所（%LOCALAPPDATA%\DroidFork）に保存する。
#>
param([int]$Port = 0)

$ErrorActionPreference = "Stop"
$dataDir = Join-Path $env:LOCALAPPDATA "DroidFork"
$distro = "DroidFork"
$configPath = Join-Path $dataDir "windows.json"
if (Test-Path $configPath) {
    $config = Get-Content -Raw -Encoding UTF8 $configPath | ConvertFrom-Json
    if ($config.distro) { $distro = $config.distro }
    if (-not $Port -and $config.port) { $Port = [int]$config.port }
}
if (-not $Port) { $Port = 8765 }

function Show-Error([string]$Text) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($Text, "DroidFork", "OK", "Error") | Out-Null
}

$tokenPath = Join-Path $dataDir "ui-token"
if (Test-Path $tokenPath) {
    $token = (Get-Content -Raw $tokenPath).Trim()
} else {
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $token = [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
    [IO.File]::WriteAllText($tokenPath, $token)
}

function Get-UiStatus {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:$Port/api/state" -Headers @{ "X-DroidFork-Token" = $token }
        return [int]$r.StatusCode
    } catch [System.Net.WebException] {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return 0
    } catch {
        return 0
    }
}

$status = Get-UiStatus
if ($status -eq 401) {
    Show-Error "ポート $Port で別の管理画面が動いています。いったん閉じてから、もう一度開いてください。"
    exit 1
}
if ($status -ne 200) {
    $wslList = (& wsl.exe --list --quiet) -replace "`0", ""
    if (-not ($wslList | Where-Object { $_.Trim() -eq $distro })) {
        Show-Error "WSL の環境「$distro」が見つかりません。DroidFork のセットアップをやり直してください。"
        exit 1
    }
    Start-Process -WindowStyle Hidden -FilePath "wsl.exe" -ArgumentList @("-d", $distro, "--", "droidfork", "ui", "--port", "$Port", "--token", $token)
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-UiStatus) -ne 200) {
        if ((Get-Date) -gt $deadline) {
            Show-Error "管理画面を起動できませんでした。`n端末で次を実行して確認してください:`nwsl -d $distro -- droidfork doctor"
            exit 1
        }
        Start-Sleep -Milliseconds 700
    }
}
Start-Process "http://127.0.0.1:$Port/?token=$token"
