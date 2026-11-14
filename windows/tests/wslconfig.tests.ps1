#Requires -Version 5.1
# Windows 用スクリプトのテスト（GitHub Actions の Windows で、Windows PowerShell 5.1 と PowerShell 7 の両方で実行する）。
#   powershell -NoProfile -ExecutionPolicy Bypass -File windows\tests\wslconfig.tests.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $root "wslconfig.ps1")
$script:failures = 0

function Assert-Equal($Expected, $Actual, [string]$Name) {
    if ($Expected -cne $Actual) {
        Write-Host "NG: $Name"
        Write-Host ("  期待: " + ($Expected -replace "`r", "\r" -replace "`n", "\n"))
        Write-Host ("  実際: " + ($Actual -replace "`r", "\r" -replace "`n", "\n"))
        $script:failures++
    } else {
        Write-Host "OK: $Name"
    }
}

# すべての .ps1 が構文エラーなく読めること
foreach ($f in Get-ChildItem -Path $root -Filter *.ps1 -Recurse) {
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors -and $errors.Count) {
        Write-Host "NG: 構文エラー $($f.Name): $($errors[0].Message)"; $script:failures++
    } else {
        Write-Host "OK: 構文 $($f.Name)"
    }
    $bytes = [IO.File]::ReadAllBytes($f.FullName)
    if (-not ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)) {
        Write-Host "NG: BOM がありません $($f.Name)（Windows PowerShell 5.1 で日本語が化けます）"; $script:failures++
    }
}

$k = "C:\Users\kai\AppData\Local\DroidFork\kernel\droidfork-wsl-kernel-x86_64"
$kk = "kernel=C:\\Users\\kai\\AppData\\Local\\DroidFork\\kernel\\droidfork-wsl-kernel-x86_64"
$nl = "`r`n"

Assert-Equal ("[wsl2]" + $nl + $kk + $nl) (Set-WslConfigKernel "" $k) "空の .wslconfig"
Assert-Equal ("[wsl2]" + $nl + "memory=8GB" + $nl + $kk + $nl) (Set-WslConfigKernel "[wsl2]`nmemory=8GB`n" $k) "既存の [wsl2] に追加"
Assert-Equal ("[wsl2]" + $nl + $kk + $nl + "memory=8GB" + $nl) (Set-WslConfigKernel "[wsl2]`r`nkernel=C:\\old\\bzImage`r`nmemory=8GB" $k) "既存の kernel= を置き換え"
Assert-Equal ("[experimental]" + $nl + "autoMemoryReclaim=gradual" + $nl + $nl + "[wsl2]" + $nl + $kk + $nl) `
    (Set-WslConfigKernel "[experimental]`nautoMemoryReclaim=gradual`n" $k) "[wsl2] が無いときは作る"
Assert-Equal ("[wsl2]" + $nl + "memory=8GB" + $nl + $kk + $nl + $nl + "[experimental]" + $nl + "x=1" + $nl) `
    (Set-WslConfigKernel "[wsl2]`nmemory=8GB`n`n[experimental]`nx=1" $k) "[wsl2] の終わりに入れる"
Assert-Equal ("[WSL2]" + $nl + $kk + $nl) (Set-WslConfigKernel "[WSL2]`nkernel = C:\\x" $k) "大文字の [WSL2] と空白入りの kernel ="

Assert-Equal $k (Get-WslConfigKernel (Set-WslConfigKernel "[wsl2]`nmemory=8GB" $k)) "設定した kernel を読み戻す"
Assert-Equal $null (Get-WslConfigKernel "[experimental]`nkernel=C:\\x") "[wsl2] 以外の kernel= は見ない"

$withOther = "[wsl2]`r`nmemory=8GB`r`n" + $kk + "`r`n"
Assert-Equal ("[wsl2]" + $nl + "memory=8GB" + $nl) (Remove-WslConfigKernel $withOther $k) "自分のカーネルの指定だけ外す"
Assert-Equal ("[wsl2]" + $nl + "kernel=C:\\other" + $nl) (Remove-WslConfigKernel "[wsl2]`nkernel=C:\\other" $k) "他のカーネルの指定は外さない"

Assert-Equal "kai" (Get-LinuxUserName "Kai") "ユーザー名: 英字"
Assert-Equal "johndoe" (Get-LinuxUserName "John.Doe") "ユーザー名: 記号を除く"
Assert-Equal "droidfork" (Get-LinuxUserName "山田") "ユーザー名: 日本語のみ"
Assert-Equal "droidfork" (Get-LinuxUserName "root") "ユーザー名: 予約語"
Assert-Equal "droidfork" (Get-LinuxUserName "1user") "ユーザー名: 数字始まり"

if ($script:failures) { Write-Host "$($script:failures) 件失敗しました"; exit 1 }
Write-Host "すべて成功しました"
