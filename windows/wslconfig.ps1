#Requires -Version 5.1
# install.ps1 と uninstall.ps1 が使う、文字列を扱うだけの関数（Windows 以外の PowerShell でもテストできる）。

function ConvertTo-WslConfigPath([string]$Path) {
    # .wslconfig では区切りの \ を \\ と書く
    return $Path.Replace("\", "\\")
}

function Add-BeforeTrailingBlank {
    <# リストの末尾の空行より前に1行入れる。 #>
    param([System.Collections.Generic.List[string]]$List, [string]$Line)
    $at = $List.Count
    while ($at -gt 0 -and $List[$at - 1].Trim() -eq "") { $at-- }
    $List.Insert($at, $Line)
}

function Set-WslConfigKernel {
    <# .wslconfig の内容に kernel= を設定した結果を返す（[wsl2] が無ければ作る。ほかの設定は残す）。 #>
    param([string]$Content, [string]$KernelPath)
    $line = "kernel=" + (ConvertTo-WslConfigPath $KernelPath)
    $lines = @()
    if ($Content) { $lines = $Content -split "\r?\n" }
    $out = New-Object System.Collections.Generic.List[string]
    $inWsl2 = $false; $sawWsl2 = $false; $done = $false
    foreach ($l in $lines) {
        $t = $l.Trim()
        if ($t -match '^\[(.+)\]$') {
            # [wsl2] の終わりまでに kernel= が無かったら、そこに入れる
            if ($inWsl2 -and -not $done) { Add-BeforeTrailingBlank $out $line; $done = $true }
            $inWsl2 = ($Matches[1].Trim().ToLower() -eq "wsl2")
            if ($inWsl2) { $sawWsl2 = $true }
            $out.Add($l)
            continue
        }
        if ($inWsl2 -and $t -match '^kernel\s*=') {
            if (-not $done) { $out.Add($line); $done = $true }
            continue
        }
        $out.Add($l)
    }
    if ($inWsl2 -and -not $done) { Add-BeforeTrailingBlank $out $line; $done = $true }
    if (-not $sawWsl2) {
        while ($out.Count -gt 0 -and $out[$out.Count - 1].Trim() -eq "") { $out.RemoveAt($out.Count - 1) }
        if ($out.Count -gt 0) { $out.Add("") }
        $out.Add("[wsl2]")
        $out.Add($line)
    }
    return (($out -join "`r`n").TrimEnd() + "`r`n")
}

function Get-WslConfigKernel([string]$Content) {
    $inWsl2 = $false
    foreach ($l in ($Content -split "\r?\n")) {
        $t = $l.Trim()
        if ($t -match '^\[(.+)\]$') { $inWsl2 = ($Matches[1].Trim().ToLower() -eq "wsl2"); continue }
        if ($inWsl2 -and $t -match '^kernel\s*=\s*(.*)$') { return $Matches[1].Trim().Replace("\\", "\") }
    }
    return $null
}

function Remove-WslConfigKernel {
    <# kernel= が指定のパスのときだけ取り除いた結果を返す（他の設定は残す）。 #>
    param([string]$Content, [string]$KernelPath)
    $inWsl2 = $false
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($l in ($Content -split "\r?\n")) {
        $t = $l.Trim()
        if ($t -match '^\[(.+)\]$') { $inWsl2 = ($Matches[1].Trim().ToLower() -eq "wsl2") }
        elseif ($inWsl2 -and $t -match '^kernel\s*=\s*(.*)$' -and $Matches[1].Trim().Replace("\\", "\") -ieq $KernelPath) { continue }
        $out.Add($l)
    }
    return (($out -join "`r`n").TrimEnd() + "`r`n")
}

function Get-LinuxUserName([string]$WindowsUser) {
    $name = ($WindowsUser.ToLower() -replace '[^a-z0-9_-]', '')
    if ($name -notmatch '^[a-z_][a-z0-9_-]{0,30}$' -or $name -in @("root", "docker", "daemon", "nobody")) { return "droidfork" }
    return $name
}
