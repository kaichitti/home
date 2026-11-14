#!/usr/bin/env bash
# root 不要で作れるフィクスチャ（FAT32）を fixtures/ に生成する。
# 実デバイスには触れない。すべて通常ファイルに対する操作。
set -euo pipefail
cd "$(dirname "$0")/.."
for t in mkfs.vfat mcopy mdel mmd python3; do
  command -v "$t" >/dev/null || { echo "missing: $t (apt install dosfstools mtools)"; exit 1; }
done
exec python3 scripts/fixturegen.py "$@"
