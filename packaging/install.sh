#!/usr/bin/env bash
# DroidFork を Ubuntu / Debian に入れる。
#
#   sudo ./install.sh                              GitHub の最新リリースから入れる
#   sudo ./install.sh ./droidfork_0.2.0_all.deb    手元の deb から入れる
#
# 行うこと:
#   1. droidfork と依存パッケージ（Docker・adb・scrcpy）を入れる
#   2. Ubuntu ではカーネルの追加モジュール（binder を含む）を入れて読み込む
#   3. Docker を起動し、実行したユーザーを docker グループに入れる
#   4. droidfork doctor で確認する
set -euo pipefail

REPO="${DROIDFORK_REPO:-kaichitti/home}"
say() { printf '==> %s\n' "$*"; }
warn() { printf '警告: %s\n' "$*" >&2; }

if [ "$(id -u)" -ne 0 ]; then
    echo "root で実行してください: sudo $0 $*" >&2
    exit 1
fi
if [ ! -r /etc/os-release ]; then
    echo "対応していない OS です（Ubuntu / Debian 向け）。" >&2
    exit 1
fi
. /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
    *" ubuntu "*|*" debian "*) ;;
    *) echo "対応していない OS です: ${PRETTY_NAME:-不明}。1ファイル版（droidfork-*.pyz）を python3 で実行してください。" >&2; exit 1 ;;
esac

DEB="${1:-}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -z "$DEB" ]; then
    command -v curl >/dev/null || { apt-get update -qq && apt-get install -y -qq curl ca-certificates; }
    say "最新のリリースを確認しています（$REPO）"
    URL="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" |
        grep -o '"browser_download_url": *"[^"]*_all\.deb"' | head -1 | cut -d'"' -f4)"
    [ -n "$URL" ] || { echo "リリースに deb が見つかりません。deb のパスを指定してください。" >&2; exit 1; }
    DEB="$TMP/$(basename "$URL")"
    curl -fL --progress-bar -o "$DEB" "$URL"
fi
case "$DEB" in /*) ;; *) DEB="$PWD/$DEB" ;; esac
[ -f "$DEB" ] || { echo "ファイルがありません: $DEB" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
say "パッケージを入れています"
apt-get update -qq
apt-get install -y "$DEB"

if ! grep -qi microsoft /proc/version 2>/dev/null; then
    if [ "${ID:-}" = "ubuntu" ] && ! modinfo binder_linux >/dev/null 2>&1; then
        say "binder を含むカーネルの追加モジュールを入れています"
        apt-get install -y "linux-modules-extra-$(uname -r)" || warn "linux-modules-extra-$(uname -r) を入れられませんでした"
    fi
    if modprobe binder_linux 2>/dev/null; then
        [ -e /etc/modules-load.d/droidfork.conf ] || printf '# DroidFork\nbinder_linux\noverlay\n' > /etc/modules-load.d/droidfork.conf
    else
        warn "binder を読み込めませんでした。カーネルが binder に対応しているか確認してください（droidfork doctor）。"
    fi
    modprobe overlay 2>/dev/null || true
fi

if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    systemctl enable --now docker >/dev/null 2>&1 || warn "Docker を起動できませんでした"
fi

TARGET_USER="${SUDO_USER:-}"
if [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ]; then
    if ! id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx docker; then
        usermod -aG docker "$TARGET_USER"
        say "$TARGET_USER を docker グループに入れました（反映には再ログインが必要です）"
    fi
fi

say "環境を確認します"
if [ -n "$TARGET_USER" ] && [ "$TARGET_USER" != "root" ]; then
    sudo -u "$TARGET_USER" -g docker droidfork doctor || true
else
    droidfork doctor || true
fi

cat <<'EOF'

インストールが終わりました。次の手順:
  1. いったんログアウトしてログインし直す（docker グループを反映するため）
  2. 実機を USB でつなぎ、端末側で「USB デバッグ」を許可する
  3. droidfork up -n 3        または  droidfork ui --open（ブラウザの管理画面）
EOF
