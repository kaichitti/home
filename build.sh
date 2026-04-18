#!/bin/sh
# WebBrowse Linux - local ISO builder
#
# Builds a bootable ISO by running the real work inside an Alpine Docker
# container (so the host only needs docker + a POSIX shell).
#
# Usage:
#   ./build.sh                    # build x86_64 ISO to ./output/webbrowse-linux.iso
#   ARCH=x86_64 ./build.sh        # override target arch
#   ALPINE_VERSION=3.20 ./build.sh
#
# Outputs:
#   ./output/webbrowse-linux.iso

set -eu

ARCH="${ARCH:-x86_64}"
ALPINE_VERSION="${ALPINE_VERSION:-3.20}"
PRODUCT_NAME="${PRODUCT_NAME:-WebBrowse Linux}"
ISO_NAME="${ISO_NAME:-webbrowse-linux.iso}"

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$PROJECT_DIR/output"
mkdir -p "$OUTPUT_DIR"

# If we're not already inside the build container, re-exec in Docker.
if [ "${IN_BUILD_CONTAINER:-0}" != "1" ]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "error: docker is required to build on the host" >&2
        echo "       (or set IN_BUILD_CONTAINER=1 when running inside Alpine)" >&2
        exit 1
    fi
    echo "==> Building inside alpine:${ALPINE_VERSION} container"
    exec docker run --rm --privileged \
        -v "$PROJECT_DIR":/work \
        -w /work \
        -e IN_BUILD_CONTAINER=1 \
        -e ARCH="$ARCH" \
        -e ALPINE_VERSION="$ALPINE_VERSION" \
        -e PRODUCT_NAME="$PRODUCT_NAME" \
        -e ISO_NAME="$ISO_NAME" \
        "alpine:${ALPINE_VERSION}" \
        sh /work/build.sh
fi

# --- Below this line: we are inside the container ---

echo "==> Installing build dependencies"
apk add --no-cache \
    alpine-sdk alpine-conf apk-tools \
    bash coreutils findutils grep sed \
    squashfs-tools xorriso syslinux mtools dosfstools \
    rsync tar xz

APK_ARCH="$ARCH"
MIRROR="${MIRROR:-https://dl-cdn.alpinelinux.org/alpine}"
WORK="/tmp/webbrowse-build"
ROOTFS="$WORK/rootfs"
ISOROOT="$WORK/iso"

rm -rf "$WORK"
mkdir -p "$ROOTFS" "$ISOROOT"

echo "==> Bootstrapping Alpine rootfs ($APK_ARCH, $ALPINE_VERSION)"
mkdir -p "$ROOTFS/etc/apk"
echo "$MIRROR/v${ALPINE_VERSION}/main"      >  "$ROOTFS/etc/apk/repositories"
echo "$MIRROR/v${ALPINE_VERSION}/community" >> "$ROOTFS/etc/apk/repositories"

# Read packages.list, stripping comments / blank lines.
PKGS=$(grep -v '^\s*#' /work/packages.list | grep -v '^\s*$' | tr '\n' ' ')

apk --arch "$APK_ARCH" \
    -X "$MIRROR/v${ALPINE_VERSION}/main" \
    -X "$MIRROR/v${ALPINE_VERSION}/community" \
    -U --allow-untrusted --root "$ROOTFS" --initdb \
    add $PKGS

echo "==> Overlaying repo rootfs/"
rsync -a /work/rootfs/ "$ROOTFS/"

echo "==> Creating user 'user' (passwordless)"
chroot "$ROOTFS" /usr/sbin/useradd -m -s /bin/sh -G wheel,audio,video,input user || true
chroot "$ROOTFS" passwd -d user || true
chroot "$ROOTFS" passwd -l root || true
chroot "$ROOTFS" chown -R user:user /home/user
chmod 0440 "$ROOTFS/etc/sudoers.d/webbrowse"
chmod 0755 "$ROOTFS/usr/local/bin/webbrowse-launcher"
chmod 0755 "$ROOTFS/usr/local/bin/autologin-user"
chmod 0755 "$ROOTFS/etc/openbox/autostart"
chmod 0755 "$ROOTFS/home/user/.xinitrc"
chmod 0644 "$ROOTFS/home/user/.profile"

echo "==> Enabling OpenRC services"
chroot "$ROOTFS" rc-update add devfs     sysinit || true
chroot "$ROOTFS" rc-update add dmesg     sysinit || true
chroot "$ROOTFS" rc-update add mdev      sysinit || true
chroot "$ROOTFS" rc-update add hwclock   boot    || true
chroot "$ROOTFS" rc-update add modules   boot    || true
chroot "$ROOTFS" rc-update add sysctl    boot    || true
chroot "$ROOTFS" rc-update add hostname  boot    || true
chroot "$ROOTFS" rc-update add bootmisc  boot    || true
chroot "$ROOTFS" rc-update add syslog    boot    || true
chroot "$ROOTFS" rc-update add mount-ro  shutdown || true
chroot "$ROOTFS" rc-update add killprocs shutdown || true
chroot "$ROOTFS" rc-update add savecache shutdown || true
chroot "$ROOTFS" rc-update add dhcpcd    default || true
chroot "$ROOTFS" rc-update add wpa_supplicant default || true

echo "==> Building squashfs"
KERNEL=$(ls "$ROOTFS"/boot/vmlinuz-* 2>/dev/null | head -n1 || true)
INITRAMFS=$(ls "$ROOTFS"/boot/initramfs-* 2>/dev/null | head -n1 || true)

if [ -z "$KERNEL" ] || [ -z "$INITRAMFS" ]; then
    echo "error: kernel/initramfs not found under $ROOTFS/boot/" >&2
    ls -la "$ROOTFS/boot" || true
    exit 1
fi

mkdir -p "$ISOROOT/boot" "$ISOROOT/boot/syslinux"
cp "$KERNEL"    "$ISOROOT/boot/vmlinuz"
cp "$INITRAMFS" "$ISOROOT/boot/initramfs"

mksquashfs "$ROOTFS" "$ISOROOT/boot/rootfs.squashfs" -comp xz -noappend

echo "==> Installing syslinux bootloader"
cp /usr/share/syslinux/isolinux.bin   "$ISOROOT/boot/syslinux/"
cp /usr/share/syslinux/ldlinux.c32    "$ISOROOT/boot/syslinux/" 2>/dev/null || true
cp /usr/share/syslinux/libcom32.c32   "$ISOROOT/boot/syslinux/" 2>/dev/null || true
cp /usr/share/syslinux/libutil.c32    "$ISOROOT/boot/syslinux/" 2>/dev/null || true
cp /usr/share/syslinux/menu.c32       "$ISOROOT/boot/syslinux/" 2>/dev/null || true
cp /usr/share/syslinux/vesamenu.c32   "$ISOROOT/boot/syslinux/" 2>/dev/null || true

cat > "$ISOROOT/boot/syslinux/syslinux.cfg" <<CFG
DEFAULT webbrowse
TIMEOUT 30
PROMPT 0

LABEL webbrowse
    MENU LABEL ${PRODUCT_NAME}
    KERNEL /boot/vmlinuz
    APPEND initrd=/boot/initramfs root=live:CDLABEL=WEBBROWSE rd.live.image quiet
CFG

echo "==> Creating ISO"
xorriso -as mkisofs \
    -o "/work/output/${ISO_NAME}" \
    -V WEBBROWSE \
    -J -r -l \
    -b boot/syslinux/isolinux.bin \
    -c boot/syslinux/boot.cat \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    "$ISOROOT"

echo "==> Done"
ls -lh "/work/output/${ISO_NAME}"
