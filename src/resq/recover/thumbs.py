"""S7 サムネイルキャッシュからの救出（最終手段）。

本体が消えた写真でも、Windows のサムネイルキャッシュに低解像度版が残っていることがある。
他の段で回収したファイルの中から次を探して画像を取り出し、ランク D（サムネイルのみ）として載せる。

  thumbcache_*.db  Windows Vista 以降（"CMMM" 形式。Vista / 7 / 8 / 8.1 / 10・11 の版に対応）
  Thumbs.db        Windows XP 以前（OLE 複合ファイル。olefile がある場合のみ）
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from .. import safety
from .manifest import Candidate, Manifest

SIGS = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"BM", "bmp"))
OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def _image_ext(data: bytes) -> str | None:
    for sig, ext in SIGS:
        if data.startswith(sig):
            return ext
    return None


def _layout(ver: int) -> tuple[int, int, int, int]:
    """(識別子長, パディング長, データ長, ヘッダ長) のオフセット"""
    if ver == 0x14:            # Vista（拡張子フィールドあり）
        return 24, 28, 32, 56
    if ver == 0x15:            # Windows 7
        return 16, 20, 24, 48
    return 16, 20, 24, 56      # Windows 8 / 8.1 / 10 / 11（幅・高さフィールドあり）


def parse_thumbcache(data: bytes) -> list[dict]:
    if data[:4] != b"CMMM" or len(data) < 24:
        return []
    ver = _u32(data, 4)
    first = _u32(data, 12) if ver in (0x14, 0x15) else _u32(data, 16)
    pos = first if 0 < first < len(data) else 24
    id_o, pad_o, len_o, hdr = _layout(ver)
    out = []
    while pos + 8 <= len(data):
        if data[pos:pos + 4] != b"CMMM":
            nxt = data.find(b"CMMM", pos + 1)
            if nxt < 0:
                break
            pos = nxt
            continue
        size = _u32(data, pos + 4)
        if size < hdr or pos + size > len(data):
            break
        e = data[pos:pos + size]
        idlen, pad, dlen = _u32(e, id_o), _u32(e, pad_o), _u32(e, len_o)
        ident = e[hdr:hdr + idlen].decode("utf-16-le", errors="replace") if hdr + idlen <= size else ""
        doff = hdr + idlen + pad
        img = e[doff:doff + dlen] if dlen and doff + dlen <= size else b""
        if not _image_ext(img):
            # 版の違いでオフセットがずれていても、エントリ内の画像シグネチャから拾う
            img = b""
            for sig, _ext in SIGS[:2]:
                k = e.find(sig, hdr)
                if k >= 0:
                    img = e[k:]
                    break
        ext = _image_ext(img)
        if ext:
            out.append({"id": ident, "data": img, "ext": ext})
        pos += size
    return out


def parse_thumbs_db(path: Path) -> list[dict]:
    try:
        import olefile  # type: ignore
    except ImportError:
        return []
    out = []
    try:
        with olefile.OleFileIO(str(path)) as ole:
            for stream in ole.listdir():
                if stream == ["Catalog"]:
                    continue
                data = ole.openstream(stream).read()
                k = data.find(b"\xff\xd8\xff")
                if k >= 0:
                    out.append({"id": "/".join(stream), "data": data[k:], "ext": "jpg"})
    except Exception:  # noqa: BLE001 - 破損した Thumbs.db は飛ばす
        return []
    return out


def _is_source(path: Path) -> str | None:
    n = path.name.lower()
    with open(path, "rb") as fh:
        head = fh.read(8)
    if head[:4] == b"CMMM" or (n.startswith("thumbcache_") and n.endswith(".db")):
        return "thumbcache"
    if n == "thumbs.db" and head == OLE_SIG:
        return "thumbs.db"
    return None


def run(case, image_id: int | None, sources: list[tuple[str, Path]], stage_dir: Path) -> Manifest:
    """sources: [(元のパスまたは保存名, 保存済みファイル)]"""
    man = Manifest(stage="S7", image_id=image_id, method="サムネイル")
    seen: set[str] = set()
    for label, path in sources:
        kind = _is_source(path)
        if kind is None:
            continue
        items = parse_thumbcache(path.read_bytes()) if kind == "thumbcache" else parse_thumbs_db(path)
        sub = safety.safe_join(stage_dir, Path(label).name.replace(".", "_"))
        for i, it in enumerate(items, 1):
            h = hashlib.sha256(it["data"]).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            dest = sub / f"thumb_{i:04d}.{it['ext']}"
            safety.assert_writable_target(dest, case_dir=case.dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(it["data"])
            man.candidates.append(Candidate(stored=str(dest.relative_to(case.dir)), method=f"サムネイル:{kind}",
                                            extra={"thumbnail": True, "source": label, "cache_id": it["id"]}))
    man.write(stage_dir)
    return man


def collect_sources(case) -> list[tuple[str, Path]]:
    """他の段の回収結果からサムネイルキャッシュを探す。"""
    out = []
    for p in sorted((case.dir / "stages").glob("img*/*/manifest.json")):
        man = Manifest.read(p)
        if man.stage == "S7":
            continue
        for c in man.candidates:
            f = case.dir / c.stored
            if f.is_file() and f.stat().st_size >= 24 and _is_source(f):
                out.append((c.orig_path or c.stored, f))
    return out
