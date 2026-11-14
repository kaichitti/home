"""FAT12/16/32 のディレクトリエントリ残骸スキャナ。

データ領域の全クラスタを走査し、ディレクトリとして解釈できるクラスタを集める。
  - 先頭が "." ".." のクラスタ＝サブディレクトリの先頭。自分と親のクラスタ番号が分かる
  - 直前のクラスタの続き（連続配置を仮定）として解釈できるクラスタ＝同じディレクトリの続き
  - 長いファイル名（LFN）は削除済みでも文字が残る。チェックサムで短い名前と照合し、
    削除で失われた短い名前の先頭 1 文字も復元する
クイックフォーマット後は FAT（クラスタの連結情報）が消えているため、データは連続配置を仮定して取り出す。
"""
from __future__ import annotations

import struct
from pathlib import Path

from .common import Entry, VolumeGeometry, iter_clusters

INVALID_83 = set(b'"*+,./:;<=>?[\\]|')
LFN_ATTR = 0x0F
DIR_ATTR = 0x10
VOL_ATTR = 0x08


def parse_boot(boot: bytes, volume_offset: int) -> tuple[VolumeGeometry, dict] | None:
    if len(boot) < 512 or boot[510:512] != b"\x55\xaa":
        return None
    bps = struct.unpack_from("<H", boot, 11)[0]
    spc = boot[13]
    if bps not in (512, 1024, 2048, 4096) or spc == 0 or spc & (spc - 1):
        return None
    reserved = struct.unpack_from("<H", boot, 14)[0]
    nfats = boot[16]
    root_entries = struct.unpack_from("<H", boot, 17)[0]
    total = struct.unpack_from("<H", boot, 19)[0] or struct.unpack_from("<I", boot, 32)[0]
    fatsz16 = struct.unpack_from("<H", boot, 22)[0]
    fatsz = fatsz16 or struct.unpack_from("<I", boot, 36)[0]
    fat32 = fatsz16 == 0
    root_cluster = struct.unpack_from("<I", boot, 44)[0] if fat32 else 0
    root_sectors = ((root_entries * 32) + bps - 1) // bps
    first_data = reserved + nfats * fatsz + root_sectors
    if total <= first_data:
        return None
    count = (total - first_data) // spc
    geo = VolumeGeometry(fs="fat32" if fat32 else "fat16", volume_offset=volume_offset,
                         cluster_size=bps * spc, data_start=volume_offset + first_data * bps,
                         cluster_count=count)
    info = {"fat32": fat32, "root_cluster": root_cluster, "bps": bps,
            "root_region": (volume_offset + (reserved + nfats * fatsz) * bps, root_sectors * bps),
            "fat_offset": volume_offset + reserved * bps}
    return geo, info


def lfn_checksum(short11: bytes) -> int:
    s = 0
    for b in short11:
        s = (((s & 1) << 7) + (s >> 1) + b) & 0xFF
    return s


def _lfn_chars(slot: bytes) -> str:
    raw = slot[1:11] + slot[14:26] + slot[28:32]
    out = []
    for i in range(0, len(raw), 2):
        ch = struct.unpack_from("<H", raw, i)[0]
        if ch in (0x0000, 0xFFFF):
            break
        out.append(chr(ch))
    return "".join(out)


def _short_ok(slot: bytes) -> bool:
    attr = slot[11]
    if attr & 0xC0 or slot[12] & ~0x18 & 0xFF:
        return False
    if slot[0:11] in (b".          ", b"..         "):
        return bool(attr & DIR_ATTR)
    first = slot[0]
    if first == 0x20 or (first < 0x20 and first != 0x05):
        return False
    for b in slot[1:11]:
        if b < 0x20 or b in INVALID_83:
            return False
    if first in INVALID_83 and first != 0x2E:
        return False
    return True


def _lfn_ok(slot: bytes) -> bool:
    return slot[11] == LFN_ATTR and slot[12] == 0 and slot[26:28] == b"\0\0" and (
        slot[0] == 0xE5 or 1 <= (slot[0] & 0x1F) <= 20)


def parse_dir_cluster(buf: bytes) -> list[dict] | None:
    """クラスタをディレクトリとして解釈できればエントリの一覧、できなければ None。"""
    out: list[dict] = []
    lfn: list[bytes] = []
    valid_short = 0
    for i in range(0, len(buf), 32):
        slot = buf[i:i + 32]
        if slot[0] == 0x00:
            if any(buf[i:]):
                # 終端の後ろにゴミがあるのは削除・再利用の結果としてありうるが、
                # ディレクトリ以外のデータを誤認しないよう、ここで打ち切る
                pass
            break
        if slot[11] == LFN_ATTR:
            if not _lfn_ok(slot):
                return None
            lfn.append(slot)
            continue
        if not _short_ok(slot):
            return None
        valid_short += 1
        out.append({"slot": slot, "lfn": lfn})
        lfn = []
    return out if valid_short else None


def _decode_short(slot: bytes, first: int) -> str:
    base = bytes([first]) + slot[1:8]
    base_s = base.rstrip(b" ").decode("cp932", errors="replace")
    ext_s = slot[8:11].rstrip(b" ").decode("cp932", errors="replace")
    if slot[12] & 0x08:
        base_s = base_s.lower()
    if slot[12] & 0x10:
        ext_s = ext_s.lower()
    return f"{base_s}.{ext_s}" if ext_s else base_s


def decode_entry(slot: bytes, lfn_slots: list[bytes], fat32: bool) -> dict | None:
    attr = slot[11]
    if attr & VOL_ATTR:
        return None
    if slot[0:11] in (b".          ", b"..         "):
        return None
    deleted = slot[0] == 0xE5
    first = 0xE5 if slot[0] == 0x05 else slot[0]
    long_name = None
    if lfn_slots:
        chk = lfn_slots[0][13]
        cands = [first] if not deleted else list(range(0x21, 0x7F)) + list(range(0x80, 0xFF))
        for c in cands:
            if lfn_checksum(bytes([c]) + slot[1:11]) == chk:
                if deleted:
                    first = c
                long_name = "".join(_lfn_chars(s) for s in reversed(lfn_slots))
                break
    if deleted and long_name is None:
        first = ord("_")
    name = long_name or _decode_short(slot, first)
    hi = struct.unpack_from("<H", slot, 20)[0] if fat32 else 0
    lo = struct.unpack_from("<H", slot, 26)[0]
    return {"name": name, "is_dir": bool(attr & DIR_ATTR), "deleted": deleted,
            "start": (hi << 16) | lo, "hi": hi, "size": struct.unpack_from("<I", slot, 28)[0]}


def _dot_info(buf: bytes, fat32: bool) -> tuple[int, int] | None:
    if buf[0:11] != b".          " or buf[32:43] != b"..         ":
        return None
    if not (buf[11] & DIR_ATTR and buf[43] & DIR_ATTR):
        return None

    def clus(o: int) -> int:
        hi = struct.unpack_from("<H", buf, o + 20)[0] if fat32 else 0
        return (hi << 16) | struct.unpack_from("<H", buf, o + 26)[0]

    return clus(0), clus(32)


def scan(image: Path, volume_offset: int) -> tuple[VolumeGeometry, list[Entry], set[str]] | None:
    with open(image, "rb") as fh:
        fh.seek(volume_offset)
        boot = fh.read(512)
    parsed = parse_boot(boot, volume_offset)
    if parsed is None:
        return None
    geo, info = parsed
    fat32 = info["fat32"]
    cs = geo.cluster_size
    max_cluster = geo.first_cluster + geo.cluster_count - 1
    vol_end = geo.data_start + geo.cluster_count * cs

    dir_clusters: dict[int, str] = {}       # クラスタ → ディレクトリキー
    listings: list[tuple[int, list[dict]]] = []
    prev_dir: str | None = None
    prev_c = -2

    for c, buf in iter_clusters(image, geo):
        if not buf[11] & 0xC0 and buf[0] not in (0x00,):  # 早期除外（1 スロット目）
            entries = parse_dir_cluster(buf)
        else:
            entries = None
        if entries is None:
            prev_dir = None
            continue
        dot = _dot_info(buf, fat32)
        if dot:
            own, parent = dot
            key = f"c{own}" if own == c else f"c{c}"
            dir_clusters[c] = key
            parent_key = "root" if parent in (0, info["root_cluster"]) else f"c{parent}"
            listings.append((c, [{"_dotparent": parent_key}] + entries))
            prev_dir = key
        else:
            if fat32 and c == info["root_cluster"]:
                key = "root"
            elif prev_dir is not None and prev_c == c - 1:
                key = prev_dir
            else:
                key = f"c{c}"
            dir_clusters[c] = key
            listings.append((c, entries))
            prev_dir = key
        prev_c = c

    out: list[Entry] = []
    dir_parent: dict[str, str] = {}

    def add(raw: dict, parent_key: str) -> None:
        if raw["start"] and not (2 <= raw["start"] <= max_cluster):
            return
        if raw["is_dir"]:
            key = f"c{raw['start']}" if raw["start"] else None
            out.append(Entry(fs=geo.fs, name=raw["name"], is_dir=True, deleted=raw["deleted"], size=0,
                             parent=parent_key, key=key, start_cluster=raw["start"],
                             meta={"hi": raw["hi"]}))
            return
        if raw["size"] == 0 or raw["start"] == 0:
            return
        off = geo.cluster_offset(raw["start"])
        size = raw["size"]
        if off + size > vol_end:
            size = max(0, vol_end - off)
        out.append(Entry(fs=geo.fs, name=raw["name"], is_dir=False, deleted=raw["deleted"],
                         size=raw["size"], parent=parent_key, runs=[(off, size)],
                         start_cluster=raw["start"], meta={"hi": raw["hi"], "fat32": fat32}))

    for c, entries in listings:
        key = dir_clusters[c]
        for raw in entries:
            if "_dotparent" in raw:
                dir_parent[key] = raw["_dotparent"]
                continue
            d = decode_entry(raw["slot"], raw["lfn"], fat32)
            if d:
                add(d, key)

    # FAT12/16 の固定ルート領域
    if not fat32:
        r_off, r_len = info["root_region"]
        with open(image, "rb") as fh:
            fh.seek(r_off)
            region = fh.read(r_len)
        entries = parse_dir_cluster(region) or []
        for raw in entries:
            d = decode_entry(raw["slot"], raw["lfn"], fat32)
            if d:
                add(d, "root")

    # ".." でしか親が分からないディレクトリ（名前を持つエントリが失われたもの）を補う
    named = {e.key for e in out if e.is_dir and e.key}
    for key, parent in dir_parent.items():
        if key not in named and key != "root":
            # 名前は不明だが、親子関係は分かる → 名前なしのディレクトリとして登録
            out.append(Entry(fs=geo.fs, name="", is_dir=True, deleted=True, size=0, parent=parent, key=key,
                             meta={"nameless": True}))
    return geo, out, {"root"}
