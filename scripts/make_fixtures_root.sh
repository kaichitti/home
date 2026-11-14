#!/usr/bin/env bash
# NTFS / exFAT のフィクスチャを作る（root が必要）。
#
# ★ 開発機では実行しない。作業機（検証環境）で人間が実行する。★
# loop デバイスを使うため、必ず「空きの loop デバイス」であることを確認してから実行すること。
# 顧客媒体を接続した状態では絶対に実行しないこと。
#
# 生成物: fixtures/ntfs_deleted.img, fixtures/exfat_deleted.img と expected_root.json
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(id -u)" -eq 0 ] || { echo "root で実行してください（作業機の検証環境のみ）"; exit 1; }
for t in mkfs.ntfs mkfs.exfat losetup mount python3; do
  command -v "$t" >/dev/null || { echo "missing: $t (apt install ntfs-3g exfatprogs)"; exit 1; }
done

OUT=fixtures
MNT=$(mktemp -d)
mkdir -p "$OUT"
SRC=$(mktemp -d)
# 既知の内容を作る（FAT 版と同じ生成器を使う）
python3 - "$SRC" <<'PY'
import sys, json, hashlib
sys.path.insert(0, "scripts")
import fixturegen as g
out = sys.argv[1]
files = g.content_set("root")
man = {}
for rel, data in files.items():
    p = f"{out}/{rel.replace('/', '__')}"
    open(p, "wb").write(data)
    man[rel] = hashlib.sha256(data).hexdigest()
json.dump(man, open(f"{out}/manifest.json", "w"), indent=1)
PY

make_one() {  # $1=fstype(ntfs|exfat) $2=image
  local fs=$1 img=$2
  rm -f "$img"; truncate -s 64M "$img"
  local dev; dev=$(losetup --find --show "$img")
  if [ "$fs" = ntfs ]; then mkfs.ntfs -Q -F -L RESQFIX "$dev"; else mkfs.exfat -L RESQFIX "$dev"; fi
  mount "$dev" "$MNT"
  mkdir -p "$MNT/DCIM" "$MNT/DOCS"
  for f in "$SRC"/*__* "$SRC"/KEEP.PDF; do
    [ -f "$f" ] || continue
    rel=$(basename "$f" | sed 's|__|/|')
    cp "$f" "$MNT/$rel"
  done
  sync
  rm -f "$MNT/DCIM/IMG_0002.JPG" "$MNT/DOCS/REPORT.PDF"
  sync; umount "$MNT"; losetup -d "$dev"
}
make_one ntfs  "$OUT/ntfs_deleted.img"
make_one exfat "$OUT/exfat_deleted.img"
cp "$SRC/manifest.json" "$OUT/expected_root.json"
rm -rf "$SRC"; rmdir "$MNT"
echo "done: $OUT/ntfs_deleted.img $OUT/exfat_deleted.img"
