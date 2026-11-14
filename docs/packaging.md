# 配布物の作り方とリリース

## 配布物

| ファイル | 対象 | 入れ方 |
| --- | --- | --- |
| `droidfork_<版>_all.deb` | Ubuntu / Debian | `sudo apt install ./droidfork_<版>_all.deb`（Docker・adb も一緒に入る） |
| `install.sh` | Ubuntu / Debian | `sudo ./install.sh`（deb の導入に加えて、binder の読み込み・Docker の起動・docker グループへの追加まで行う） |
| `droidfork-<版>-py3-none-any.whl` | Linux 全般 | `pipx install droidfork-<版>-py3-none-any.whl` |
| `droidfork-<版>.pyz` | Linux 全般 | `python3 droidfork-<版>.pyz up -n 3`（1ファイルで動く。インストール不要） |
| `droidfork-<版>.tar.gz` | ソース一式 | `pip install droidfork-<版>.tar.gz` |
| `DroidFork-Setup-<版>.exe` | Windows 10/11 | 実行するだけ（WSL2・カーネル・Linux 環境まで自動で設定。[windows.md](windows.md)） |
| `droidfork-wsl-kernel-x86_64` / `-arm64` | Windows（WSL2） | インストーラが使う、binder 入りの WSL2 カーネル |
| `droidfork-wsl-kernel-*.config`、`droidfork-wsl-kernel-source.txt` | Windows（WSL2） | カーネルのビルドに使った設定と、ソース（GPL v2）の入手先 |
| `SHA256SUMS` | すべて | `sha256sum -c SHA256SUMS` で改ざんがないか確かめる |

`.deb` の中身:

- `/usr/bin/droidfork` と `/usr/lib/python3/dist-packages/droidfork/`
- `/usr/lib/modprobe.d/droidfork.conf`（binder のデバイス名）
- `/usr/lib/systemd/system/droidfork-scheduler@.timer`（予定の自動実行。`sudo systemctl enable --now droidfork-scheduler@$USER.timer` で有効になる）
- 導入時に binder を読み込めた場合だけ、起動時の自動読み込み（`/etc/modules-load.d/droidfork.conf`）を登録する

## 手元で作る

```sh
pip install build                  # sdist を作るときだけ必要
packaging/build.sh                 # dist/ に pyz・deb・wheel・sdist と SHA256SUMS
packaging/build.sh deb pyz         # 指定したものだけ
```

WSL2 カーネル（30〜60分かかります）:

```sh
sudo apt install build-essential flex bison bc libssl-dev libelf-dev dwarves cpio
windows/kernel/build-kernel.sh                       # 最新のタグで x86_64 を作る
ARCH=arm64 windows/kernel/build-kernel.sh            # ARM64（gcc-aarch64-linux-gnu が必要）
CONFIG_ONLY=1 windows/kernel/build-kernel.sh         # 設定の確認だけ（数分）
```

ビルド時に、binder・binderfs・overlayfs・USB/IP が有効になっていることを確かめます。モジュール（`=m`）はすべて本体に組み込むので、配るのはカーネルのファイル1つだけです。

Windows インストーラ（Windows で [Inno Setup 6](https://jrsoftware.org/isinfo.php) を使う）:

```powershell
iscc /DAppVersion=0.2.0 windows\droidfork.iss       # dist\DroidFork-Setup-0.2.0.exe
```

`dist\droidfork_*_all.deb` が必要です。`dist\wsl-kernel\` にカーネルがあれば同梱し、無ければ導入時にリリースからダウンロードします。

## GitHub Actions

| ワークフロー | いつ動くか | 内容 |
| --- | --- | --- |
| `test` | プルリクエスト、master への push | Python のテスト（3.10/3.12/3.13）、Linux 向けパッケージ、Windows のスクリプトのテストとインストーラのビルド |
| `wsl-kernel` | 手動、リリース時 | binder 入りの WSL2 カーネル（x86_64・arm64） |
| `release` | `v` で始まるタグの push | 上のすべてを作り、GitHub のリリースに載せる |

## リリースの手順

1. `droidfork/__init__.py` の `__version__` を上げる（パッケージの版はここから決まる）
2. 変更を master に入れる
3. タグを付けて push する

```sh
git tag v0.2.0
git push origin v0.2.0
```

`release` ワークフローが、タグと `__version__` が一致するかを確かめてから、すべての配布物を作ってリリースを作成します。
