#!/bin/sh
# scripts/build-iso.sh — assembles the WebBrowse Linux ISO.
#
# Runs inside an Alpine host (native Alpine, a chroot via
# jirutka/setup-alpine, or an alpine:VERSION Docker container).
# Uses apk --root to install the target system into a staging dir,
# then packs it into a squashfs and wraps it in a syslinux-bootable ISO.
#
# Env vars (with defaults):
#   ARCH=x86_64          target apk arch
#   ALPINE_VERSION=3.20  Alpine version (major.minor)
#   PRODUCT_NAME="WebBrowse Linux"
#   ISO_NAME=webbrowse-linux.iso
#   PROJECT_DIR          absolute path to the repo root (auto-detected)
#   WORK_DIR=/tmp/webbrowse-build
#
# Output:
#   $PROJECT_DIR/output/$ISO_NAME

set -eux

ARCH="${ARCH:-x86_64}"
ALPINE_VERSION="${ALPINE_VERSION:-3.20}"
PRODUCT_NAME="${PRODUCT_NAME:-WebBrowse Linux}"
ISO_NAME="${ISO_NAME:-webbrowse-linux.iso}"
MIRROR="${MIRROR:-https://dl-cdn.alpinelinux.org/alpine}"
WORK_DIR="${WORK_DIR:-/tmp/webbrowse-build}"

if [ -z "${PROJECT_DIR:-}" ]; then
    PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

OUTPUT_DIR="$PROJECT_DIR/output"
ROOTFS="$WORK_DIR/rootfs"
ISOROOT="$WORK_DIR/iso"

mkdir -p "$OUTPUT_DIR"

# --- Build host deps --------------------------------------------------------
echo "==> Installing build host dependencies"
apk update
apk add --no-cache \
    alpine-sdk apk-tools \
    coreutils findutils grep sed \
    squashfs-tools xorriso syslinux \
    rsync tar xz

# --- Stage target rootfs ----------------------------------------------------
echo "==> Staging Alpine rootfs at $ROOTFS ($ARCH / $ALPINE_VERSION)"
rm -rf "$WORK_DIR"
mkdir -p "$ROOTFS/etc/apk" "$ISOROOT"

printf '%s\n' \
    "$MIRROR/v${ALPINE_VERSION}/main" \
    "$MIRROR/v${ALPINE_VERSION}/community" \
    > "$ROOTFS/etc/apk/repositories"

# Build the package list (strip comments / blanks).
PKGS=$(sed -e 's/#.*$//' -e '/^[[:space:]]*$/d' "$PROJECT_DIR/packages.list" | tr '\n' ' ')
echo "Packages: $PKGS"

apk --arch "$ARCH" \
    -X "$MIRROR/v${ALPINE_VERSION}/main" \
    -X "$MIRROR/v${ALPINE_VERSION}/community" \
    -U --allow-untrusted \
    --root "$ROOTFS" --initdb \
    add $PKGS

# --- Overlay repo-provided files -------------------------------------------
echo "==> Overlaying rootfs/"
rsync -a "$PROJECT_DIR/rootfs/" "$ROOTFS/"

# --- User and permissions ---------------------------------------------------
echo "==> Creating passwordless 'user' account"
# Use the target system's chroot tools (shadow was installed above).
chroot "$ROOTFS" /usr/sbin/useradd -m -s /bin/sh -G wheel,audio,video,input user
chroot "$ROOTFS" passwd -d user
chroot "$ROOTFS" chown -R user:user /home/user

chmod 0440 "$ROOTFS/etc/sudoers.d/webbrowse"
chmod 0755 "$ROOTFS/usr/local/bin/webbrowse-launcher"
chmod 0755 "$ROOTFS/usr/local/bin/autologin-user"
chmod 0755 "$ROOTFS/etc/openbox/autostart"
chmod 0755 "$ROOTFS/home/user/.xinitrc"
chmod 0644 "$ROOTFS/home/user/.profile"

# --- OpenRC services --------------------------------------------------------
echo "==> Enabling OpenRC services"
for svc_runlevel in \
    "devfs sysinit" "dmesg sysinit" "mdev sysinit" \
    "hwclock boot" "modules boot" "sysctl boot" "hostname boot" "bootmisc boot" "syslog boot" \
    "mount-ro shutdown" "killprocs shutdown" "savecache shutdown" \
    "dhcpcd default" "wpa_supplicant default"; do
    # shellcheck disable=SC2086
    set -- $svc_runlevel
    svc="$1"; rl="$2"
    if [ -e "$ROOTFS/etc/init.d/$svc" ]; then
        chroot "$ROOTFS" rc-update add "$svc" "$rl" || true
    else
        echo "  (skip) $svc not installed"
    fi
done

# --- Build initramfs --------------------------------------------------------
# apk installs under --root do not fire post-install triggers, so mkinitfs
# must be invoked manually to produce /boot/initramfs-lts.
echo "==> Building initramfs"
KVER=$(ls "$ROOTFS/lib/modules" | head -n1)
if [ -z "$KVER" ]; then
    echo "error: no kernel modules under $ROOTFS/lib/modules" >&2
    ls -la "$ROOTFS/lib/modules" || true
    exit 1
fi
# Need resolv.conf for network-free mkinitfs; mkinitfs itself does not need it,
# but chroot execution of some packages does. Provide an empty one.
: > "$ROOTFS/etc/resolv.conf"
chroot "$ROOTFS" /sbin/mkinitfs -o "/boot/initramfs-lts" "$KVER"

# --- Assemble ISO tree ------------------------------------------------------
echo "==> Building squashfs"
KERNEL=$(ls "$ROOTFS"/boot/vmlinuz-* 2>/dev/null | head -n1 || true)
INITRAMFS=$(ls "$ROOTFS"/boot/initramfs-* 2>/dev/null | head -n1 || true)
if [ -z "$KERNEL" ] || [ -z "$INITRAMFS" ]; then
    echo "error: kernel or initramfs missing under $ROOTFS/boot" >&2
    ls -la "$ROOTFS/boot" || true
    exit 1
fi

mkdir -p "$ISOROOT/boot/syslinux"
cp "$KERNEL"    "$ISOROOT/boot/vmlinuz"
cp "$INITRAMFS" "$ISOROOT/boot/initramfs"
mksquashfs "$ROOTFS" "$ISOROOT/boot/rootfs.squashfs" -comp xz -noappend

echo "==> Installing syslinux bootloader files"
for f in isolinux.bin ldlinux.c32 libcom32.c32 libutil.c32 menu.c32 vesamenu.c32; do
    if [ -f "/usr/share/syslinux/$f" ]; then
        cp "/usr/share/syslinux/$f" "$ISOROOT/boot/syslinux/"
    fi
done

cat > "$ISOROOT/boot/syslinux/syslinux.cfg" <<CFG
DEFAULT webbrowse
TIMEOUT 30
PROMPT 0

LABEL webbrowse
    MENU LABEL ${PRODUCT_NAME}
    KERNEL /boot/vmlinuz
    APPEND initrd=/boot/initramfs quiet
CFG

# --- ISO --------------------------------------------------------------------
echo "==> Creating ISO"
xorriso -as mkisofs \
    -o "$OUTPUT_DIR/$ISO_NAME" \
    -V WEBBROWSE \
    -J -r -l \
    -b boot/syslinux/isolinux.bin \
    -c boot/syslinux/boot.cat \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    "$ISOROOT"

echo "==> Done"
ls -lh "$OUTPUT_DIR/$ISO_NAME"
