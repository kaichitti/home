"""exFAT のディレクトリエントリセット残骸スキャナ。

exFAT のファイルは「File(0x85) + Stream Extension(0xC0) + File Name(0xC1)×n」のエントリセットで表される。
削除すると各エントリの最上位ビット（InUse）が落ちるだけで、名前・先頭クラスタ・長さは残る。
サブディレクトリには "." ".." がないため、ディレクトリのエントリが指すクラスタ範囲から親子関係を復元する。
"""
from __future__ import annotations

import struct
from pathlib import Path

from .common import Entry, VolumeGeometry, iter_clusters

T_FILE, T_STREAM, T_NAME = 0x05, 0x40, 0x41
KNOWN_TYPES = {0x00, 0x81, 0x82, 0x83, 0xA0, 0xA1, 0xA2, 0x85, 0xC0, 0xC1, 0x05, 0x40, 0x41, 0x03, 0x01, 0x02,
               0x20, 0x21, 0x22, 0xE0, 0xE1}


def parse_boot(boot: bytes, volume_offset: int) -> tuple[VolumeGeometry, dict] | None:
    if len(boot) < 512 or boot[3:11] != b"EXFAT   " or boot[510:512] != b"\x55\xaa":
        return None
    bps = 1 << boot[0x6C]
    cs = bps << boot[0x6D]
    heap = struct.unpack_from("<I", boot, 0x58)[0]
    count = struct.unpack_from("<I", boot, 0x5C)[0]
    root = struct.unpack_from("<I", boot, 0x60)[0]
    geo = VolumeGeometry(fs="exfat", volume_offset=volume_offset, cluster_size=cs,
                         data_start=volume_offset + heap * bps, cluster_count=count)
    return geo, {"root_cluster": root}


def _name(slots: list[bytes], length: int) -> str | None:
    raw = b"".join(s[2:32] for s in slots)[: length * 2]
    try:
        name = raw.decode("utf-16-le")
    except UnicodeDecodeError:
        return None
    if not name or any(ord(ch) < 0x20 or ch in '"*/:<>?\\|' for ch in name):
        return None
    return name


def parse_entry_sets(buf: bytes, max_cluster: int, vol_size: int) -> list[dict] | None:
    """クラスタ内のエントリセットを解釈する。ディレクトリでなさそうなら None。"""
    slots = [buf[i:i + 32] for i in range(0, len(buf), 32)]
    out: list[dict] = []
    i = 0
    while i < len(slots):
        s = slots[i]
        t = s[0]
        if t == 0x00:
            break
        if t not in KNOWN_TYPES:
            return None
        if t & 0x7F != T_FILE:
            i += 1
            continue
        sec = s[1]
        if sec < 2 or sec > 18 or i + sec >= len(slots) + 1:
            return None
        set_slots = slots[i:i + 1 + sec]
        if len(set_slots) < 1 + sec:
            break  # クラスタ境界をまたぐセット（次のクラスタは別途走査）
        st = set_slots[1]
        if st[0] & 0x7F != T_STREAM or any(x[0] & 0x7F != T_NAME for x in set_slots[2:]):
            return None
        in_use = bool(t & 0x80)
        if any(bool(x[0] & 0x80) != in_use for x in set_slots):
            return None
        name_len = st[3]
        name = _name(set_slots[2:], name_len)
        first = struct.unpack_from("<I", st, 20)[0]
        length = struct.unpack_from("<Q", st, 24)[0]
        valid = struct.unpack_from("<Q", st, 8)[0]
        if name is None or (first and not 2 <= first <= max_cluster) or length > vol_size:
            return None
        attrs = struct.unpack_from("<H", s, 4)[0]
        out.append({"name": name, "is_dir": bool(attrs & 0x10), "deleted": not in_use, "first": first,
                    "length": length, "valid": min(valid, length), "nofat": bool(st[1] & 0x02)})
        i += 1 + sec
    return out if out else None


def scan(image: Path, volume_offset: int) -> tuple[VolumeGeometry, list[Entry], set[str]] | None:
    with open(image, "rb") as fh:
        fh.seek(volume_offset)
        boot = fh.read(512)
    parsed = parse_boot(boot, volume_offset)
    if parsed is None:
        return None
    geo, info = parsed
    cs = geo.cluster_size
    max_cluster = geo.first_cluster + geo.cluster_count - 1
    vol_size = geo.cluster_count * cs

    found: list[tuple[int, list[dict]]] = []
    for c, buf in iter_clusters(image, geo):
        t = buf[0]
        if t & 0x7F not in (T_FILE, 0x03, 0x01, 0x02, 0x20, 0x00) or not any(buf[:32]):
            continue
        sets = parse_entry_sets(buf, max_cluster, vol_size)
        if sets:
            found.append((c, sets))

    # ディレクトリが占めるクラスタ範囲 → ディレクトリキー
    owner: dict[int, str] = {info["root_cluster"]: "root"}
    for _c, sets in found:
        for e in sets:
            if e["is_dir"] and e["first"]:
                n = max(1, (e["length"] + cs - 1) // cs) if e["nofat"] else 1
                for k in range(n):
                    owner.setdefault(e["first"] + k, f"c{e['first']}")

    out: list[Entry] = []
    for c, sets in found:
        parent = owner.get(c, f"c{c}")
        for e in sets:
            if e["is_dir"]:
                out.append(Entry(fs="exfat", name=e["name"], is_dir=True, deleted=e["deleted"], size=0,
                                 parent=parent, key=f"c{e['first']}" if e["first"] else None,
                                 start_cluster=e["first"]))
                continue
            if not e["first"] or not e["length"]:
                continue
            off = geo.cluster_offset(e["first"])
            runs: list[tuple[int | None, int]] = [(off, e["valid"])]
            if e["length"] > e["valid"]:
                runs.append((None, e["length"] - e["valid"]))
            out.append(Entry(fs="exfat", name=e["name"], is_dir=False, deleted=e["deleted"],
                             size=e["length"], parent=parent, runs=runs, start_cluster=e["first"],
                             meta={"contiguous": e["nofat"]}))
    return geo, out, {"root"}
