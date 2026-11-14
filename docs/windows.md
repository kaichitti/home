# Windows 版（WSL2）

Windows では、WSL2 の中に DroidFork 専用の Linux 環境を作って動かします。インストーラが WSL2 の有効化、binder を組み込んだカーネルの配置、Docker・adb・droidfork の導入までを自動で行います。

## 必要なもの

| 項目 | 内容 |
| --- | --- |
| OS | Windows 11、または Windows 10 バージョン 2004（ビルド 19041）以降 |
| CPU | x64 または ARM64。BIOS/UEFI で仮想化（Intel VT-x / AMD-V）が有効なこと |
| メモリ | 16GB 以上を推奨（台数はメモリで決まります） |
| ディスク | 空き 20GB 以上（ベースイメージと雛形で 10GB 前後） |
| 権限 | 管理者として実行できること |

## インストール

1. リリースから `DroidFork-Setup-<版>.exe` を取得して実行します。
2. 途中で黒い画面（PowerShell）が開き、設定の進み具合が表示されます。数分から十数分かかります。
3. WSL を初めて使う PC では再起動を求められます。再起動してログオンすると、管理者の確認（UAC）が出て、続きの設定が自動で始まります。
4. 終わると、スタートメニューに次の3つができます。

| スタートメニュー | 内容 |
| --- | --- |
| DroidFork | 管理画面をブラウザで開く |
| DroidFork（端末） | DroidFork の Linux 環境を開く（`droidfork` コマンドが使えます） |
| DroidFork のセットアップをやり直す | 設定を最初から確認し直す（途中で失敗したとき用） |

## インストーラが行うこと

| 項目 | 内容 |
| --- | --- |
| WSL2 | 有効にして最新にする（`wsl --install --no-distribution`、`wsl --update`） |
| カーネル | binder・binderfs を組み込んだ WSL2 カーネルを `%LOCALAPPDATA%\DroidFork\kernel\` に置き、`%USERPROFILE%\.wslconfig` の `[wsl2]` に `kernel=` を設定する。元の `.wslconfig` は `.wslconfig.droidfork-backup` に保存する |
| Linux 環境 | Ubuntu 24.04 から「DroidFork」という名前の環境を作る（保存先 `%LOCALAPPDATA%\DroidFork\wsl\`）。systemd を有効にし、Windows のユーザー名に合わせたユーザーを作る |
| ソフト | Linux 環境の中に Docker・adb・scrcpy・droidfork を入れ、Docker と予定の自動実行（`droidfork-scheduler@<ユーザー>.timer`）を有効にする |
| USB | 実機を WSL へ渡すための [usbipd-win](https://github.com/dorssel/usbipd-win) を winget で入れる |

**注意:** `.wslconfig` のカーネルの指定は、その Windows ユーザーのすべての WSL 環境に効きます。Docker Desktop など、ほかの WSL 環境もこのカーネルで動くようになります。このカーネルは Microsoft の WSL2 カーネルと同じ設定に binder などを足したものです。すでに別のカーネルを指定している場合は、置き換える前に確認を求めます。

## 使い方

### 管理画面

スタートメニューの「DroidFork」を開くと、ブラウザに管理画面が出ます。テンプレートの取り込み・作成、台数の追加、起動・停止・リセット、スナップショット、スケジュール、実測まで、画面から操作できます。

### 実機をつなぐ

WSL2 の中からは USB 機器が直接見えないため、usbipd-win で Windows から WSL へ渡します。

1. 実機を USB でつなぎ、端末側で「USB デバッグ」を許可します。
2. 管理画面の「テンプレート」→「実機から取り込む」を開くと、Windows につながった USB 機器が一覧で出ます。
3. 実機の行の「WSLへつなぐ」を押します。初回だけ Windows の権限確認（UAC）が出るので「はい」を選びます。
4. 「取り込み元」に実機が出たら「取り込む」を押します。

コマンドで行う場合は、「DroidFork（端末）」で次を実行します。

```sh
droidfork usb list            # Windows につながった USB 機器
droidfork usb attach 1-4      # BUSID を指定して WSL へつなぐ
droidfork devices             # adb から見えることを確認
droidfork up -n 3
```

### 画面表示

`droidfork screen <ID>`（管理画面の「画面を開く」）は、WSL の中の scrcpy でウィンドウを開きます。Windows 11（または WSLg に対応した Windows 10）が必要です。

Windows 側の adb や Android Studio からは、通常は `adb connect 127.0.0.1:15555` のように接続できます。WSL の localhost 転送（`.wslconfig` の `localhostForwarding`、既定で有効）を使います。

## 困ったとき

| 症状 | 対処 |
| --- | --- |
| 管理画面が開かない | 「DroidFork（端末）」で `droidfork doctor` を実行し、NG の項目を確認する |
| doctor で binder が NG | Windows を再起動するか、PowerShell で `wsl --shutdown` を実行してから開き直す。`.wslconfig` の `kernel=` が `%LOCALAPPDATA%\DroidFork\kernel\` を指しているか確認する |
| 実機が一覧に出ない | Windows の PowerShell で `usbipd list` を実行し、実機が見えるか確認する。端末側の「USB デバッグを許可」を確認する |
| 「WSLへつなぐ」が失敗する | 管理者の PowerShell で `usbipd bind --busid <BUSID>` を実行してから、もう一度押す |
| 設定が途中で止まった | スタートメニューの「DroidFork のセットアップをやり直す」を実行する |

## アンインストール

「設定」→「アプリ」→「DroidFork」からアンインストールします。途中で「仮想端末のデータ（WSL の DroidFork 環境）も削除しますか？」と聞かれます。「いいえ」を選ぶとデータは残ります。

アンインストールでは `.wslconfig` から DroidFork のカーネルの指定だけを外し、ほかの設定は残します。

## インストーラを使わずに入れる

リリースから次のファイルを1つのフォルダに集め、管理者の PowerShell で `install.ps1` を実行します。

- `install.ps1`、`wslconfig.ps1`、`provision.sh`、`DroidFork.ps1`、`uninstall.ps1`（リポジトリの `windows/`）
- `droidfork_<版>_all.deb`
- `droidfork-wsl-kernel-x86_64`（ARM の PC では `-arm64`）と `.sha256`。置かなかった場合は、最新のリリースからダウンロードします

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

## 動作確認の状況

Windows 版は、開発環境に Windows がないため、実機での通しの確認はまだできていません。確認済みなのは次の点です。

- binder を組み込んだ WSL2 カーネル（`linux-msft-wsl-6.18.58.1` ベース）が、設定の確認を含めてビルドできること
- そのカーネルを QEMU で起動し、binderfs をマウントすると `binder`・`hwbinder`・`vndbinder` ができること、overlayfs で差分層が動くこと
- Linux 環境の中で行う設定（deb の導入、Docker・adb・scrcpy）が Ubuntu 24.04 で動くこと
- `.wslconfig` を書き換える処理のテスト（GitHub Actions の Windows で、Windows PowerShell 5.1 と PowerShell 7 の両方で実行）
- インストーラ（Inno Setup）がビルドできること（GitHub Actions の Windows）

最初に使うときは、上の「困ったとき」とあわせて結果を確認してください。
