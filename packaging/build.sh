#!/usr/bin/env bash
# 配布物を dist/ に作る。
#
#   packaging/build.sh            すべて（pyz・deb・wheel・sdist）
#   packaging/build.sh deb pyz    指定したものだけ
#
# 環境変数: MAINTAINER（deb の管理者欄）、HOMEPAGE（deb のホームページ欄）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="$(python3 -c 'import droidfork; print(droidfork.__version__)')"
DIST="$ROOT/dist"
BUILD="$ROOT/build/packaging"
MAINTAINER="${MAINTAINER:-DroidFork <droidfork@example.invalid>}"
HOMEPAGE="${HOMEPAGE:-https://github.com/kaichitti/home}"
TARGETS=("$@")
[ ${#TARGETS[@]} -eq 0 ] && TARGETS=(pyz deb wheel sdist)

mkdir -p "$DIST"
rm -rf "$BUILD"
mkdir -p "$BUILD"

copy_package() {  # $1: コピー先（droidfork パッケージを置くディレクトリ）
    mkdir -p "$1"
    (cd "$ROOT" && find droidfork -name '__pycache__' -prune -o -type f \( -name '*.py' -o -name '*.html' \) -print) |
        while read -r f; do install -D -m 0644 "$ROOT/$f" "$1/$f"; done
}

build_pyz() {
    local stage="$BUILD/pyz"
    copy_package "$stage"
    python3 -m zipapp "$stage" -m "droidfork.cli:main" -p "/usr/bin/env python3" -c -o "$DIST/droidfork-$VERSION.pyz"
    chmod 0755 "$DIST/droidfork-$VERSION.pyz"
    echo "==> $DIST/droidfork-$VERSION.pyz"
}

build_deb() {
    command -v dpkg-deb >/dev/null || { echo "dpkg-deb がないため deb は作れません" >&2; return 1; }
    local root="$BUILD/deb/droidfork_${VERSION}_all"
    copy_package "$root/usr/lib/python3/dist-packages"
    install -D -m 0755 packaging/deb/droidfork "$root/usr/bin/droidfork"
    install -D -m 0644 packaging/deb/modprobe.conf "$root/usr/lib/modprobe.d/droidfork.conf"
    install -D -m 0644 "packaging/systemd/droidfork-scheduler@.service" "$root/usr/lib/systemd/system/droidfork-scheduler@.service"
    install -D -m 0644 "packaging/systemd/droidfork-scheduler@.timer" "$root/usr/lib/systemd/system/droidfork-scheduler@.timer"
    install -D -m 0644 README.md "$root/usr/share/doc/droidfork/README.md"
    install -D -m 0644 docs/poc.md "$root/usr/share/doc/droidfork/poc.md"
    install -D -m 0644 LICENSE "$root/usr/share/doc/droidfork/copyright"
    mkdir -p "$root/DEBIAN"
    sed -e "s|@VERSION@|$VERSION|" -e "s|@MAINTAINER@|$MAINTAINER|" -e "s|@HOMEPAGE@|$HOMEPAGE|" \
        packaging/deb/control.in > "$root/DEBIAN/control"
    echo "Installed-Size: $(du -sk "$root" | cut -f1)" >> "$root/DEBIAN/control"
    install -m 0755 packaging/deb/postinst "$root/DEBIAN/postinst"
    install -m 0755 packaging/deb/prerm "$root/DEBIAN/prerm"
    install -m 0755 packaging/deb/postrm "$root/DEBIAN/postrm"
    dpkg-deb --root-owner-group -Zxz --build "$root" "$DIST/droidfork_${VERSION}_all.deb" >/dev/null
    install -m 0755 packaging/install.sh "$DIST/install.sh"
    echo "==> $DIST/droidfork_${VERSION}_all.deb（と install.sh）"
}

build_wheel() {
    python3 -m pip wheel --no-deps --no-build-isolation -q -w "$DIST" "$ROOT" 2>/dev/null ||
        python3 -m pip wheel --no-deps -q -w "$DIST" "$ROOT"
    rm -rf "$ROOT/build/lib" "$ROOT/build/bdist."* "$ROOT"/*.egg-info
    echo "==> $DIST/droidfork-$VERSION-py3-none-any.whl"
}

build_sdist() {
    if python3 -c 'import build' 2>/dev/null; then
        python3 -m build --sdist --outdir "$DIST" "$ROOT" >/dev/null
        rm -rf "$ROOT"/*.egg-info
        echo "==> $DIST/droidfork-$VERSION.tar.gz"
    else
        echo "python3 -m build がないため sdist は作りません（pip install build で入ります）" >&2
    fi
}

for t in "${TARGETS[@]}"; do
    case "$t" in
        pyz) build_pyz ;;
        deb) build_deb ;;
        wheel) build_wheel ;;
        sdist) build_sdist ;;
        *) echo "不明な対象: $t（pyz / deb / wheel / sdist）" >&2; exit 2 ;;
    esac
done
(cd "$DIST" && sha256sum -- * 2>/dev/null | grep -v SHA256SUMS > SHA256SUMS || true)
