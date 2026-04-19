#!/bin/sh
# build.sh — local ISO builder wrapper.
#
# Runs scripts/build-iso.sh inside an alpine:$ALPINE_VERSION Docker
# container so the host only needs docker. For CI, the workflow
# calls scripts/build-iso.sh directly via setup-alpine.
#
# Usage:
#   ./build.sh                    # x86_64 ISO -> ./output/webbrowse-linux.iso
#   ARCH=x86_64 ./build.sh
#   ALPINE_VERSION=3.20 ./build.sh

set -eu

ARCH="${ARCH:-x86_64}"
ALPINE_VERSION="${ALPINE_VERSION:-3.20}"
PRODUCT_NAME="${PRODUCT_NAME:-WebBrowse Linux}"
ISO_NAME="${ISO_NAME:-webbrowse-linux.iso}"

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$PROJECT_DIR/output"

if ! command -v docker >/dev/null 2>&1; then
    echo "error: docker is required for local builds" >&2
    echo "       (CI uses scripts/build-iso.sh directly on an Alpine host)" >&2
    exit 1
fi

echo "==> Running build inside alpine:${ALPINE_VERSION}"
exec docker run --rm --privileged \
    -v "$PROJECT_DIR":/work \
    -w /work \
    -e ARCH="$ARCH" \
    -e ALPINE_VERSION="$ALPINE_VERSION" \
    -e PRODUCT_NAME="$PRODUCT_NAME" \
    -e ISO_NAME="$ISO_NAME" \
    -e PROJECT_DIR=/work \
    "alpine:${ALPINE_VERSION}" \
    sh /work/scripts/build-iso.sh
