#!/usr/bin/env bash
# WSL の DroidFork 環境の中で、root として実行する初期設定。
# Windows 側の install.ps1 から呼ばれる。
#
#   provision.sh <droidfork の deb> <ユーザー名>
set -euo pipefail

DEB="$1"
USERNAME="${2:-droidfork}"
export DEBIAN_FRONTEND=noninteractive
say() { printf '==> %s\n' "$*"; }

say "WSL の設定（systemd を有効にし、既定のユーザーを $USERNAME にする）"
cat > /etc/wsl.conf <<CONF
[boot]
systemd=true

[user]
default=$USERNAME

[interop]
enabled=true
appendWindowsPath=true
CONF

if ! id "$USERNAME" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$USERNAME"
    passwd -d "$USERNAME" >/dev/null
fi
# sudo をパスワードなしで使えるようにする（専用環境のため）
echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/droidfork
chmod 0440 /etc/sudoers.d/droidfork

say "パッケージを入れています（Docker・adb・scrcpy・droidfork）"
apt-get update -qq
apt-get install -y -qq ca-certificates curl >/dev/null
apt-get install -y "$DEB" scrcpy android-sdk-platform-tools-common
usermod -aG docker,plugdev "$USERNAME"

say "Docker とスケジュール実行を自動で起動するようにします"
systemctl enable docker.service >/dev/null 2>&1 || true
systemctl enable "droidfork-scheduler@$USERNAME.timer" >/dev/null 2>&1 || true
DATA="/home/$USERNAME/.local/share/droidfork"
install -d -o "$USERNAME" -g "$USERNAME" "$DATA"
echo "system: droidfork-scheduler@$USERNAME.timer" > "$DATA/.timer-installed"
chown "$USERNAME:$USERNAME" "$DATA/.timer-installed"

if grep -qw binder /proc/filesystems; then
    say "binder が使えます"
else
    echo "警告: このカーネルでは binder が使えません。.wslconfig の kernel= を確認してください。" >&2
fi
say "初期設定が終わりました"
