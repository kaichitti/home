#!/usr/bin/env bash
# binder を有効にした WSL2 カーネルをビルドする。
#
#   windows/kernel/build-kernel.sh [タグ]
#
# タグ（例: linux-msft-wsl-6.6.87.2）を省略すると最新を使う。
# 環境変数:
#   ARCH=x86_64|arm64   ビルドする CPU（既定 x86_64）
#   OUT=<dir>           出力先（既定 ./dist/wsl-kernel）
#   WORK=<dir>          作業場所（既定 ./build/wsl-kernel）
#
# 出力: $OUT/droidfork-wsl-kernel-<ARCH> と .sha256、.config（ビルドに使った設定）、
#       droidfork-wsl-kernel-source.txt（GPL v2 のソースの入手先）
#
# Microsoft の WSL 用設定（config-wsl）をもとに binder・binderfs を追加し、
# モジュール（=m）はすべて本体に組み込む。こうすると .wslconfig の kernel= に
# このファイルを1つ指定するだけで動き、モジュール用の VHD を配らなくて済む。
set -euo pipefail

REPO="${REPO:-https://github.com/microsoft/WSL2-Linux-Kernel}"
TAG="${1:-}"
ARCH="${ARCH:-x86_64}"
OUT="$(mkdir -p "${OUT:-$PWD/dist/wsl-kernel}" && cd "${OUT:-$PWD/dist/wsl-kernel}" && pwd)"
WORK="${WORK:-$PWD/build/wsl-kernel}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$TAG" ]; then
  TAG="$(git ls-remote --tags --refs "$REPO" 'linux-msft-wsl-*' | sed 's#.*refs/tags/##' | sort -V | tail -1)"
fi
echo "==> WSL2 カーネル $TAG（$ARCH）"

case "$ARCH" in
  x86_64) KARCH=x86;   IMAGE=arch/x86/boot/bzImage;  CONFIGS="arch/x86/configs/config-wsl Microsoft/config-wsl" ;;
  arm64)  KARCH=arm64; IMAGE=arch/arm64/boot/Image;  CONFIGS="arch/arm64/configs/config-wsl-arm64 Microsoft/config-wsl-arm64"
          if [ "$(uname -m)" != "aarch64" ]; then export CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}"; fi ;;
  *) echo "ARCH は x86_64 か arm64 です: $ARCH" >&2; exit 2 ;;
esac

SRC="$WORK/$TAG"
if [ ! -d "$SRC/.git" ]; then
  mkdir -p "$WORK"
  git clone --depth 1 --branch "$TAG" "$REPO" "$SRC"
fi
cd "$SRC"

BASE=""
for c in $CONFIGS; do [ -f "$c" ] && BASE="$c" && break; done
[ -n "$BASE" ] || { echo "WSL 用の設定ファイルが見つかりません" >&2; exit 1; }
echo "==> 設定: $BASE + $HERE/binder.config"

cp "$BASE" .config
scripts/kconfig/merge_config.sh -m .config "$HERE/binder.config" >/dev/null
make ARCH="$KARCH" olddefconfig >/dev/null
# モジュールをすべて本体に組み込む（依存関係で組み込めないものは olddefconfig が調整する）
sed -i 's/=m$/=y/' .config
make ARCH="$KARCH" olddefconfig >/dev/null

missing=0
for opt in CONFIG_ANDROID_BINDER_IPC=y CONFIG_ANDROID_BINDERFS=y CONFIG_OVERLAY_FS=y CONFIG_VETH=y CONFIG_BRIDGE=y CONFIG_USBIP_VHCI_HCD=y; do
  if ! grep -qx "$opt" .config; then echo "設定が入っていません: $opt" >&2; missing=1; fi
done
grep -q '^CONFIG_ANDROID_BINDER_DEVICES="binder,hwbinder,vndbinder"' .config || { echo "binder のデバイス名が違います" >&2; missing=1; }
[ "$missing" = 0 ] || exit 1
echo "==> 設定を確認しました（binder・binderfs・overlayfs・USB/IP）"
NAME="droidfork-wsl-kernel-$ARCH"
[ "${CONFIG_ONLY:-0}" = 1 ] && { cp .config "$OUT/$NAME.config"; echo "CONFIG_ONLY=1 のため設定だけ出力しました: $OUT/$NAME.config"; exit 0; }

make ARCH="$KARCH" LOCALVERSION="-droidfork" -j"$(nproc)" "$(basename "$IMAGE")"

cp "$IMAGE" "$OUT/$NAME"
cp .config "$OUT/$NAME.config"
(cd "$OUT" && sha256sum "$NAME" > "$NAME.sha256")
cat > "$OUT/droidfork-wsl-kernel-source.txt" <<SRC
DroidFork の WSL2 カーネルのソース（GPL v2）
  元のソース: $REPO タグ $TAG
  追加した設定: windows/kernel/binder.config（DroidFork のリポジトリ）
  ビルドに使った設定の全体: droidfork-wsl-kernel-<CPU>.config
  モジュール（=m）はすべて本体に組み込んでいます（windows/kernel/build-kernel.sh）。
SRC
echo "==> できました: $OUT/$NAME"
