# WebBrowse Linux

[日本語](#日本語) · [English](#english)

---

## 日本語

**WebBrowse Linux** は、Alpine Linux をベースにした **Web 閲覧専用** の超軽量ディストリビューションです。起動直後にフルスクリーン・ランチャーが立ち上がり、Firefox ESR または Chromium を開く以外の操作を一切持ちません。

- ベース: Alpine Linux + OpenRC（systemd は使いません）
- ターゲット: RAM 256MB 以上、ストレージ 1GB 以上
- 目標 ISO サイズ: 600MB 以下
- 配布: GitHub Releases（ISO）、GPL v2

### できること

起動後、下記 4 つだけをボタンで操作できるフルスクリーン・ランチャーが表示されます。

1. **Firefox / Chromium の起動**（ブラウザを閉じると自動でランチャーに戻ります）
2. **ユーザーの切り替え**（X セッションを終了し、自動ログインからやり直し）
3. **再起動**
4. **シャットダウン**

デスクトップ環境、ファイルマネージャ、テキストエディタ、ターミナル、印刷、Bluetooth、オーディオは一切含まれません。

### 仮想マシンで試す

ISO を `output/webbrowse-linux.iso` に用意した状態で：

```sh
# QEMU（KVM を使える環境なら -enable-kvm 推奨）
qemu-system-x86_64 -m 512 -cdrom output/webbrowse-linux.iso -boot d

# VirtualBox: 新規 VM → タイプ Linux / Other Linux (64-bit) → ISO をマウント
```

### ローカルでのビルド

Docker が必要です。ホスト側では何もインストールする必要はありません。

```sh
git clone https://github.com/<owner>/<repo>.git
cd <repo>
./build.sh
# -> output/webbrowse-linux.iso
```

環境変数でカスタマイズできます：

| 変数              | デフォルト           | 意味                        |
|-----------------|-----------------|---------------------------|
| `ARCH`          | `x86_64`        | ターゲットアーキテクチャ              |
| `ALPINE_VERSION`| `3.20`          | Alpine のメジャー.マイナーバージョン   |
| `PRODUCT_NAME`  | `WebBrowse Linux` | 起動ロゴ・ランチャー上の表示名        |
| `ISO_NAME`      | `webbrowse-linux.iso` | 出力 ISO のファイル名       |

### リポジトリ構成

```
.
├── .github/workflows/build.yml   # GitHub Actions（ISO 自動ビルド）
├── scripts/build-iso.sh           # ISO ビルド本体（Alpine ホスト上で実行）
├── rootfs/                        # ISO に焼き込むファイルのオーバーレイ
│   ├── etc/
│   │   ├── inittab
│   │   ├── conf.d/webbrowse
│   │   ├── network/interfaces
│   │   ├── openbox/autostart
│   │   ├── sudoers.d/webbrowse
│   │   └── X11/xorg.conf.d/10-keyboard.conf
│   ├── home/user/
│   │   ├── .profile
│   │   └── .xinitrc
│   └── usr/local/bin/
│       ├── webbrowse-launcher     # Python3 + Tkinter 製のランチャー
│       └── autologin-user
├── packages.list                  # apk でインストールするパッケージ
├── build.sh                       # ローカル用ラッパー（Docker 経由で build-iso.sh を実行）
├── LICENSE                        # GPL v2
└── README.md
```

### 設計上の決定

- **systemd を使わない**: Alpine 標準の OpenRC で完結させます。
- **Node.js を使わない**: ランチャーは標準ライブラリの Tkinter だけで動きます（追加の依存なし）。
- **ウィンドウマネージャは openbox**: 最小限の X セッションを提供します。
- **ブランディングは `PRODUCT_NAME` で差し替え可能**: 将来的な名称変更に備えています。
- **ブートローダは syslinux**: BIOS ブート環境で最小構成の ISO を作れます。

### ライセンス

GPL v2（`LICENSE` を参照）。

---

## English

**WebBrowse Linux** is a web-browsing-only, ultra-light Linux distribution based on Alpine. Boot the ISO and a fullscreen launcher appears immediately — its only actions are launching Firefox ESR / Chromium, switching users, rebooting, or shutting down. No desktop environment, no file manager, no terminal.

- Base: Alpine Linux + OpenRC (no systemd)
- Target: 256 MB RAM / 1 GB storage
- ISO size target: ≤ 600 MB
- Distribution: GitHub Releases, GPL v2

### Build

Docker is the only host requirement.

```sh
./build.sh
# -> output/webbrowse-linux.iso
```

Tweak with env vars: `ARCH`, `ALPINE_VERSION`, `PRODUCT_NAME`, `ISO_NAME`.

### Try it

```sh
qemu-system-x86_64 -m 512 -cdrom output/webbrowse-linux.iso -boot d
```

### Layout

Same as the 日本語 section above.

### License

GPL v2 — see `LICENSE`.
