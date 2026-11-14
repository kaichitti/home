#Requires -Version 5.1
<#
.SYNOPSIS
  DroidFork を Windows（WSL2）に入れる。

.DESCRIPTION
  1. WSL2 を有効にする（初めての場合は再起動が必要。再起動後に自動で続きを行う）
  2. binder を組み込んだ WSL2 カーネルを配置し、.wslconfig の kernel= に設定する
  3. 専用の Linux 環境（既定の名前: DroidFork）を作り、Docker・adb・droidfork を入れる
  4. 実機を USB でつなぐための usbipd-win を入れる
  5. スタートメニューに「DroidFork」を作る（インストーラから呼ばれたときは作らない）

  管理者として実行してください。通常はインストーラ（DroidFork-Setup.exe）から自動で呼ばれます。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1
#>
[CmdletBinding()]
param(
    [string]$Distro = "DroidFork",
    [string]$BaseDistro = "Ubuntu-24.04",
    [string]$PayloadDir = $PSScriptRoot,
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA "DroidFork"),
    [string]$KernelUrl = "",
    [string]$Repo = "kaichitti/home",
    [int]$UiPort = 8765,
    [switch]$SkipUsbipd,
    [switch]$NoShortcut,
    [switch]$Yes,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$RebootRequired = 3010

. (Join-Path $PSScriptRoot "wslconfig.ps1")   # .wslconfig の編集などの関数

function Get-KernelArch {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "AMD64" { return "x86_64" }
        "ARM64" { return "arm64" }
        default { throw "この CPU（$($env:PROCESSOR_ARCHITECTURE)）には対応していません。" }
    }
}

# ---- 実行 ----

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Note([string]$Text) { Write-Host "    $Text" }

function Confirm-Step([string]$Question) {
    if ($Yes) { return $true }
    $answer = Read-Host "$Question [y/N]"
    return ($answer -match '^(y|yes)$')
}

function Invoke-Wsl {
    <# wsl.exe を実行して出力（UTF-8）と終了コードを返す。 #>
    param([string[]]$Arguments)
    $env:WSL_UTF8 = "1"
    $prev = [Console]::OutputEncoding
    $prevPref = $ErrorActionPreference
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    # Windows PowerShell 5.1 では、標準エラーを 2>&1 で受けると Stop 設定のときに例外になるため一時的に緩める
    $ErrorActionPreference = "Continue"
    try {
        $output = & wsl.exe @Arguments 2>&1 | ForEach-Object { "$_" }
        return [pscustomobject]@{ Code = $LASTEXITCODE; Output = (($output -join "`n") -replace "`0", "") }
    } finally {
        $ErrorActionPreference = $prevPref
        [Console]::OutputEncoding = $prev
    }
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Register-Resume {
    <# 再起動後のログオン時に、管理者の確認（UAC）を出してから続きを実行する。
       RunOnce の値は短く保つ必要があるため、続きを起動する小さなスクリプトを置いてそれを登録する。 #>
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $cmdArgs = "-NoProfile -ExecutionPolicy Bypass -File ""$PSCommandPath"" -Resume -Yes -PayloadDir ""$PayloadDir"" -DataDir ""$DataDir"" -Distro ""$Distro"""
    if ($NoShortcut) { $cmdArgs += " -NoShortcut" }
    $resume = Join-Path $DataDir "resume-setup.ps1"
    $body = "Start-Process -FilePath powershell.exe -Verb RunAs -ArgumentList '" + $cmdArgs.Replace("'", "''") + "'"
    [IO.File]::WriteAllText($resume, $body, (New-Object Text.UTF8Encoding($true)))
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "DroidForkSetup" `
        -Value "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""$resume"""
}

function Install-Wsl {
    Write-Step "WSL2 を確認しています"
    $status = Invoke-Wsl @("--status")
    if ($status.Code -ne 0) {
        Write-Note "WSL を有効にします（数分かかります）"
        $r = Invoke-Wsl @("--install", "--no-distribution")
        Write-Note $r.Output
        Register-Resume
        Write-Host ""
        Write-Host "WSL を有効にしました。Windows を再起動すると、続きの設定が自動で始まります。" -ForegroundColor Yellow
        exit $RebootRequired
    }
    Write-Note "WSL を最新にしています"
    $null = Invoke-Wsl @("--update")
    $null = Invoke-Wsl @("--set-default-version", "2")
}

function Install-Kernel {
    $arch = Get-KernelArch
    $name = "droidfork-wsl-kernel-$arch"
    $kernelDir = Join-Path $DataDir "kernel"
    New-Item -ItemType Directory -Force -Path $kernelDir | Out-Null
    $target = Join-Path $kernelDir $name
    $local = Join-Path $PayloadDir $name
    Write-Step "binder を組み込んだ WSL2 カーネルを配置します（$arch）"
    if (Test-Path $local) {
        Copy-Item -Force $local $target
    } else {
        $url = $KernelUrl
        if (-not $url) { $url = "https://github.com/$Repo/releases/latest/download/$name" }
        Write-Note "ダウンロード: $url"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $target
        try { Invoke-WebRequest -UseBasicParsing -Uri "$url.sha256" -OutFile "$target.sha256" } catch { }
    }
    $sum = @("$local.sha256", "$target.sha256") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($sum) {
        $expected = ((Get-Content $sum -Raw).Trim() -split '\s+')[0].ToLower()
        $actual = (Get-FileHash -Algorithm SHA256 $target).Hash.ToLower()
        if ($expected -ne $actual) { throw "カーネルのファイルが壊れています（SHA256 が一致しません）。" }
        Write-Note "SHA256 を確認しました"
    }

    $wslconfig = Join-Path $env:USERPROFILE ".wslconfig"
    $content = ""
    if (Test-Path $wslconfig) { $content = [IO.File]::ReadAllText($wslconfig) }
    $current = Get-WslConfigKernel $content
    if ($current -and ($current -ine $target)) {
        Write-Host "    .wslconfig ではすでに別のカーネルが指定されています: $current" -ForegroundColor Yellow
        if (-not (Confirm-Step "DroidFork のカーネルに置き換えますか？（ほかの WSL 環境もこのカーネルで動きます）")) {
            throw "中止しました。"
        }
    }
    if ($current -ine $target) {
        if ((Test-Path $wslconfig) -and -not (Test-Path "$wslconfig.droidfork-backup")) {
            Copy-Item $wslconfig "$wslconfig.droidfork-backup"
        }
        [IO.File]::WriteAllText($wslconfig, (Set-WslConfigKernel $content $target), (New-Object Text.UTF8Encoding($false)))
        Write-Note ".wslconfig に kernel= を設定しました（すべての WSL 環境に適用されます）"
        Write-Note "反映のため WSL をいったん停止します"
        $null = Invoke-Wsl @("--shutdown")
    } else {
        Write-Note "カーネルは設定済みです"
    }
}

function Get-DistroNames {
    $r = Invoke-Wsl @("--list", "--quiet")
    if ($r.Code -ne 0) { return @() }
    return @($r.Output -split "\r?\n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Install-Distro {
    Write-Step "専用の Linux 環境「$Distro」を用意します"
    if ((Get-DistroNames) -contains $Distro) {
        Write-Note "すでにあります"
        return
    }
    $location = Join-Path $DataDir "wsl"
    New-Item -ItemType Directory -Force -Path $location | Out-Null
    $r = Invoke-Wsl @("--install", $BaseDistro, "--name", $Distro, "--location", $location, "--no-launch")
    if ($r.Code -ne 0 -or -not ((Get-DistroNames) -contains $Distro)) {
        Write-Host $r.Output
        throw "Linux 環境を作れませんでした。'wsl --update' で WSL を最新にしてから、もう一度実行してください。"
    }
    Write-Note "作成しました（$BaseDistro、保存先 $location）"
}

function Invoke-Provision {
    $deb = Get-ChildItem -Path $PayloadDir -Filter "droidfork_*_all.deb" | Sort-Object Name | Select-Object -Last 1
    if (-not $deb) { throw "droidfork の deb が見つかりません: $PayloadDir" }
    $user = Get-LinuxUserName $env:USERNAME
    Write-Step "Linux 環境の中に Docker・adb・droidfork を入れます（ユーザー $user、数分かかります）"
    $toWsl = {
        param($p)
        $r = Invoke-Wsl @("-d", $Distro, "-u", "root", "--", "wslpath", "-a", "-u", $p)
        if ($r.Code -ne 0) { throw "パスを変換できません: $p" }
        return $r.Output.Trim()
    }
    $script = & $toWsl (Join-Path $PayloadDir "provision.sh")
    $debPath = & $toWsl $deb.FullName
    & wsl.exe -d $Distro -u root -- bash $script $debPath $user
    if ($LASTEXITCODE -ne 0) { throw "Linux 環境の初期設定に失敗しました（終了コード $LASTEXITCODE）。" }
    Write-Note "systemd を有効にするため、Linux 環境を再起動します"
    $null = Invoke-Wsl @("--terminate", $Distro)
}

function Test-Setup {
    Write-Step "動作を確認します"
    $r = Invoke-Wsl @("-d", $Distro, "--", "grep", "-cw", "binder", "/proc/filesystems")
    if ($r.Code -ne 0) {
        Write-Host "    binder が使えません。Windows を再起動してから、もう一度確認してください。" -ForegroundColor Yellow
    } else {
        Write-Note "binder: OK"
    }
    & wsl.exe -d $Distro -- droidfork doctor
}

function Install-Usbipd {
    if ($SkipUsbipd) { return }
    Write-Step "実機を WSL へつなぐための usbipd-win を確認します"
    if (Get-Command usbipd -ErrorAction SilentlyContinue) { Write-Note "入っています"; return }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install --id dorssel.usbipd-win -e --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) { Write-Note "入れました"; return }
    }
    Write-Host "    usbipd-win を入れられませんでした。https://github.com/dorssel/usbipd-win/releases から入れてください。" -ForegroundColor Yellow
}

function Save-LauncherConfig {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $config = [ordered]@{ distro = $Distro; port = $UiPort }
    [IO.File]::WriteAllText((Join-Path $DataDir "windows.json"), ($config | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
}

function New-Shortcut {
    if ($NoShortcut) { return }
    $launcher = Join-Path $PayloadDir "DroidFork.ps1"
    $lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "DroidFork.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = "powershell.exe"
    $s.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
    $s.WorkingDirectory = $PayloadDir
    $s.Description = "DroidFork の管理画面を開く"
    $s.Save()
    Write-Note "スタートメニューに「DroidFork」を作りました"
}

function Main {
    if (-not (Test-Admin)) { throw "管理者として実行してください（PowerShell を右クリック →「管理者として実行」）。" }
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt 19041) { throw "Windows 10 バージョン 2004（ビルド 19041）以降が必要です（このPC: $build）。" }
    if ($Resume) { Write-Step "再起動後の設定を続けます" }

    Install-Wsl
    Install-Kernel
    Install-Distro
    Invoke-Provision
    Install-Usbipd
    Save-LauncherConfig
    New-Shortcut
    Test-Setup

    Write-Host ""
    Write-Host "DroidFork の準備ができました。" -ForegroundColor Green
    Write-Host "  ・スタートメニューの「DroidFork」で管理画面を開けます"
    Write-Host "  ・実機は USB でつなぎ、管理画面の「実機から取り込む」→「WSLへつなぐ」を押してください"
    Write-Host "  ・コマンドで使う場合: wsl -d $Distro -- droidfork up -n 3"
}

if ($MyInvocation.InvocationName -ne ".") {
    try {
        Main
    } catch {
        Write-Host ""
        Write-Host "エラー: $($_.Exception.Message)" -ForegroundColor Red
        if (-not $Yes) { Read-Host "Enter キーで閉じます" | Out-Null }
        exit 1
    }
}
