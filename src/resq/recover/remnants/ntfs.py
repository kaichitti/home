"""NTFS の MFT レコード残骸スキャナ。

ボリューム全域から "FILE" レコードを探し、$FILE_NAME（名前・親レコード番号）と $DATA（常駐データ
またはランリスト）を読む。ランリストがあるため、断片化したファイルも正しく取り出せる。
再フォーマット（クイック）後も、旧 $MFT のレコードはデータ領域に残骸として残ることが多い。

未対応（TODO）: 圧縮・暗号化属性、$ATTRIBUTE_LIST（拡張レコードに分かれた大きなファイル）。
"""
from __future__ import annotations

import struct
from pathlib import Path

from .common import READ_CHUNK, Entry, VolumeGeometry

ROOT_RECORD = 5
FIRST_USER_RECORD = 16
NS_DOS = 2


def parse_boot(boot: bytes, volume_offset: int) -> tuple[VolumeGeometry, dict] | None:
    if len(boot) < 512 or boot[3:11] != b"NTFS    ":
        return None
    bps = struct.unpack_from("<H", boot, 0x0B)[0]
    spc = boot[0x0D]
    if bps not in (512, 1024, 2048, 4096) or spc == 0:
        return None
    if spc > 0x80:  # 大きなクラスタは 2^(256-n) で表す
        spc = 1 << (256 - spc)
    cs = bps * spc
    total = struct.unpack_from("<Q", boot, 0x28)[0]
    mft_lcn = struct.unpack_from("<Q", boot, 0x30)[0]
    cpr = struct.unpack_from("<b", boot, 0x40)[0]
    rec_size = (1 << -cpr) if cpr < 0 else cpr * cs
    geo = VolumeGeometry(fs="ntfs", volume_offset=volume_offset, cluster_size=cs,
                         data_start=volume_offset, cluster_count=total * bps // cs, first_cluster=0)
    return geo, {"record_size": rec_size, "mft_lcn": mft_lcn, "bps": bps}


def apply_fixups(rec: bytearray, sector: int = 512) -> bool:
    usa_off, usa_cnt = struct.unpack_from("<HH", rec, 4)
    if usa_off + usa_cnt * 2 > len(rec) or usa_cnt < 2:
        return False
    usn = rec[usa_off:usa_off + 2]
    ok = True
    for i in range(1, usa_cnt):
        end = i * sector - 2
        if end + 2 > len(rec):
            break
        if rec[end:end + 2] != usn:
            ok = False
        rec[end:end + 2] = rec[usa_off + i * 2:usa_off + i * 2 + 2]
    return ok


def decode_runlist(data: bytes, pos: int) -> list[tuple[int | None, int]]:
    """ランリスト → [(LCN または None(疎), クラスタ数)]"""
    runs: list[tuple[int | None, int]] = []
    lcn = 0
    while pos < len(data):
        head = data[pos]
        if head == 0:
            break
        ln_size, off_size = head & 0x0F, head >> 4
        pos += 1
        if ln_size == 0 or pos + ln_size + off_size > len(data):
            break
        length = int.from_bytes(data[pos:pos + ln_size], "little")
        pos += ln_size
        if off_size == 0:
            runs.append((None, length))
        else:
            delta = int.from_bytes(data[pos:pos + off_size], "little", signed=True)
            pos += off_size
            lcn += delta
            runs.append((lcn, length))
    return runs


def parse_record(rec: bytes) -> dict | None:
    if rec[:4] != b"FILE":
        return None
    r = bytearray(rec)
    torn = not apply_fixups(r)
    attr_off = struct.unpack_from("<H", r, 0x14)[0]
    flags = struct.unpack_from("<H", r, 0x16)[0]
    base = struct.unpack_from("<Q", r, 0x20)[0] & 0xFFFFFFFFFFFF
    recno = struct.unpack_from("<I", r, 0x2C)[0]
    if base or attr_off >= len(r):
        return None  # 拡張レコード（TODO: $ATTRIBUTE_LIST 対応）
    names: list[tuple[int, int, str]] = []
    data = None
    pos = attr_off
    while pos + 16 <= len(r):
        atype, alen = struct.unpack_from("<II", r, pos)
        if atype == 0xFFFFFFFF or alen == 0 or pos + alen > len(r):
            break
        nonres = r[pos + 8]
        name_len = r[pos + 9]
        aflags = struct.unpack_from("<H", r, pos + 12)[0]
        if atype == 0x30 and not nonres:
            vlen, voff = struct.unpack_from("<IH", r, pos + 16)
            v = r[pos + voff:pos + voff + vlen]
            if len(v) >= 0x42:
                parent = struct.unpack_from("<Q", v, 0)[0] & 0xFFFFFFFFFFFF
                nlen, ns = v[0x40], v[0x41]
                try:
                    nm = bytes(v[0x42:0x42 + nlen * 2]).decode("utf-16-le")
                    names.append((ns, parent, nm))
                except UnicodeDecodeError:
                    pass
        elif atype == 0x80 and name_len == 0 and data is None:
            if aflags & 0x0001 or aflags & 0x4000:
                data = {"unsupported": "圧縮または暗号化"}
            elif not nonres:
                vlen, voff = struct.unpack_from("<IH", r, pos + 16)
                data = {"resident": bytes(r[pos + voff:pos + voff + vlen]), "size": vlen}
            else:
                start_vcn = struct.unpack_from("<Q", r, pos + 16)[0]
                run_off = struct.unpack_from("<H", r, pos + 32)[0]
                real = struct.unpack_from("<Q", r, pos + 48)[0]
                init = struct.unpack_from("<Q", r, pos + 56)[0]
                if start_vcn == 0:
                    data = {"runs": decode_runlist(bytes(r[pos:pos + alen]), run_off), "size": real,
                            "initialized": init}
        pos += alen
    if not names:
        return None
    names.sort(key=lambda n: (n[0] == NS_DOS, n[0]))
    ns, parent, name = names[0]
    return {"recno": recno, "in_use": bool(flags & 1), "is_dir": bool(flags & 2), "parent": parent,
            "name": name, "data": data, "torn": torn}


def scan(image: Path, volume_offset: int) -> tuple[VolumeGeometry, list[Entry], set[str]] | None:
    with open(image, "rb") as fh:
        fh.seek(volume_offset)
        boot = fh.read(512)
    parsed = parse_boot(boot, volume_offset)
    if parsed is None:
        return None
    geo, info = parsed
    rs = info["record_size"]
    cs = geo.cluster_size
    vol_end = min(image.stat().st_size, volume_offset + geo.cluster_count * cs)

    records: list[dict] = []
    with open(image, "rb") as fh:
        pos = volume_offset
        while pos < vol_end:
            fh.seek(pos)
            buf = fh.read(min(READ_CHUNK + rs, vol_end - pos))
            i = buf.find(b"FILE")
            while 0 <= i < min(READ_CHUNK, len(buf)):
                if (pos + i - volume_offset) % 512 == 0 and i + rs <= len(buf):
                    rec = parse_record(buf[i:i + rs])
                    if rec:
                        records.append(rec)
                i = buf.find(b"FILE", i + 1)
            pos += READ_CHUNK

    out: list[Entry] = []
    for rec in records:
        n = rec["recno"]
        if n < FIRST_USER_RECORD or (rec["parent"] == ROOT_RECORD and rec["name"].startswith("$")):
            continue
        parent = "root" if rec["parent"] == ROOT_RECORD else f"r{rec['parent']}"
        if rec["is_dir"]:
            out.append(Entry(fs="ntfs", name=rec["name"], is_dir=True, deleted=not rec["in_use"], size=0,
                             parent=parent, key=f"r{n}", meta={"recno": n}))
            continue
        d = rec["data"]
        if not d or "unsupported" in d:
            continue
        if "resident" in d:
            if not d["size"]:
                continue
            out.append(Entry(fs="ntfs", name=rec["name"], is_dir=False, deleted=not rec["in_use"],
                             size=d["size"], parent=parent, resident=d["resident"], meta={"recno": n}))
            continue
        size = d["size"]
        if not size or not d["runs"]:
            continue
        runs: list[tuple[int | None, int]] = []
        for lcn, length in d["runs"]:
            if lcn is not None and (lcn < 0 or lcn + length > geo.cluster_count):
                runs = []
                break
            runs.append((None if lcn is None else geo.cluster_offset(lcn), length * cs))
        if not runs:
            continue
        if d.get("initialized", size) < size:
            # 初期化済みサイズより後ろはゼロ（NTFS の仕様）
            keep, acc = [], 0
            for off, ln in runs:
                take = max(0, min(ln, d["initialized"] - acc))
                if take:
                    keep.append((off, take))
                acc += ln
            keep.append((None, size - d["initialized"]))
            runs = keep
        first_lcn = next((lcn for lcn, _ in d["runs"] if lcn is not None), None)
        out.append(Entry(fs="ntfs", name=rec["name"], is_dir=False, deleted=not rec["in_use"], size=size,
                         parent=parent, runs=runs, start_cluster=first_lcn,
                         meta={"recno": n, "fragments": len(d["runs"])}))
    return geo, out, {"root"}
