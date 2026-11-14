; DroidFork の Windows インストーラ（Inno Setup 6）
;
; ビルド（リポジトリのルートで）:
;   packaging/build.sh deb                          … dist/droidfork_<版>_all.deb を作る
;   windows/kernel/build-kernel.sh                  … dist/wsl-kernel/ にカーネルを作る（省略可。無ければ導入時にダウンロード）
;   iscc /DAppVersion=<版> windows\droidfork.iss    … dist/DroidFork-Setup-<版>.exe ができる
;
; 導入の流れ: ファイルを置いたあと install.ps1 を管理者として実行し、WSL2・カーネル・Linux 環境を設定する。

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C1E7F0A-3B52-4D1E-9A57-D20F0E7B5A11}
AppName=DroidFork
AppVersion={#AppVersion}
AppVerName=DroidFork {#AppVersion}
AppPublisher=DroidFork
DefaultDirName={autopf}\DroidFork
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible arm64
ArchitecturesInstallIn64BitMode=x64compatible arm64
MinVersion=10.0.19041
OutputDir=..\dist
OutputBaseFilename=DroidFork-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
UninstallDisplayName=DroidFork
SetupLogging=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
Source: "install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "wslconfig.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "provision.sh"; DestDir: "{app}"; Flags: ignoreversion
Source: "DroidFork.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\droidfork_*_all.deb"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\wsl-kernel\droidfork-wsl-kernel-x86_64"; DestDir: "{app}"; Check: IsX64Compatible; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\dist\wsl-kernel\droidfork-wsl-kernel-x86_64.sha256"; DestDir: "{app}"; Check: IsX64Compatible; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\dist\wsl-kernel\droidfork-wsl-kernel-arm64"; DestDir: "{app}"; Check: IsArm64; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\dist\wsl-kernel\droidfork-wsl-kernel-arm64.sha256"; DestDir: "{app}"; Check: IsArm64; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\windows.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\DroidFork"; Filename: "powershell.exe"; \
  Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\DroidFork.ps1"""; \
  WorkingDir: "{app}"; Comment: "DroidFork の管理画面を開く"
Name: "{autoprograms}\DroidFork（端末）"; Filename: "wsl.exe"; Parameters: "-d DroidFork"; Comment: "DroidFork の Linux 環境を開く（droidfork コマンドが使えます）"
Name: "{autoprograms}\DroidFork のセットアップをやり直す"; Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -NoShortcut"; WorkingDir: "{app}"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""{app}\DroidFork.ps1"""; \
  Description: "DroidFork の管理画面を開く"; Flags: postinstall nowait skipifsilent runasoriginaluser; Check: SetupSucceeded

[Code]
var
  NeedsRestartFlag: Boolean;
  SetupOk: Boolean;

function SetupSucceeded(): Boolean;
begin
  Result := SetupOk;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Params: String;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'WSL2 と DroidFork の環境を設定しています（数分〜十数分かかります）…';
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install.ps1') + '" -NoShortcut -Yes';
    if not Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      MsgBox('設定スクリプトを起動できませんでした。', mbError, MB_OK)
    else if ResultCode = 3010 then
    begin
      NeedsRestartFlag := True;
      MsgBox('WSL を有効にしました。Windows を再起動すると、続きの設定が自動で始まります。', mbInformation, MB_OK);
    end
    else if ResultCode <> 0 then
      MsgBox('設定の途中で問題が起きました（コード ' + IntToStr(ResultCode) + '）。' + #13#10 +
             '表示された内容を確認し、スタートメニューの「DroidFork のセットアップをやり直す」を実行してください。', mbError, MB_OK)
    else
      SetupOk := True;
  end;
end;

function NeedRestart(): Boolean;
begin
  Result := NeedsRestartFlag;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  Params: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\uninstall.ps1') + '"';
    if MsgBox('仮想端末のデータ（WSL の DroidFork 環境）も削除しますか？' + #13#10 +
              '「いいえ」を選ぶとデータは残ります。', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      Params := Params + ' -RemoveDistro';
    Exec('powershell.exe', Params, ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode);
  end;
end;
