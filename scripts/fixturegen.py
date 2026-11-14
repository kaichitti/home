#!/usr/bin/env python3
"""テスト用ディスクイメージ（フィクスチャ）を生成する。root 不要。

実デバイスには一切触れない。すべて fixtures/ 配下の通常ファイルに対して
mkfs.vfat（-C でファイル作成）と mtools（mcopy / mdel / mmd）を実行する。

生成するイメージ:
  deleted.img      FAT32。一部ファイルを削除。
  overwrite.img    FAT32。削除したファイルのデータ領域をゼロで上書き（＝戻らない想定）。
  quickformat.img  FAT32。ファイル投入後にクイックフォーマット。
  parttable.img    MBR＋FAT32 パーティション。パーティション表を消去済み。
  corrupt/         破損ファイル（catalog の破損判定テスト用）

削除前の sha256 を fixtures/expected.json に保存する。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import random
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("RESQ_FIXTURES", ROOT / "fixtures"))
FS_MB = 40  # FAT32 の最小クラスタ数を満たすため -s 1 と組み合わせる
SEED = 20261113


def sh(*args: str, env: dict | None = None) -> None:
    for a in args:
        if a.startswith("/dev/"):
            raise SystemExit(f"refusing device path: {a}")
    e = dict(os.environ, MTOOLS_SKIP_CHECK="1", MTOOLS_NO_VFAT="0")
    if env:
        e.update(env)
    subprocess.run(list(args), check=True, env=e, stdout=subprocess.DEVNULL)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- 内容生成
def make_jpeg(rng: random.Random, w: int, h: int) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (w, h))
    px = img.load()
    a, b, c = rng.randrange(256), rng.randrange(256), rng.randrange(256)
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 3 + a + rng.randrange(40)) % 256,
                        (y * 5 + b + rng.randrange(40)) % 256,
                        ((x ^ y) + c) % 256)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def make_pdf(text: str, pad: int) -> bytes:
    """最小構成の正しい PDF（xref 付き）。pad でサイズを調整。"""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET\n" + "% " + "x" * pad + "\n"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}endstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(rng: random.Random, text: str, paras: int) -> bytes:
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
          'officedocument.wordprocessingml.document.main+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    body = "".join(
        f"<w:p><w:r><w:t>{text} {i} {rng.getrandbits(64):x}</w:t></w:r></w:p>" for i in range(paras))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:  # 無圧縮＝カービング対象として素直
        for name, data in (("[Content_Types].xml", ct), ("_rels/.rels", rels), ("word/document.xml", doc)):
            zi = zipfile.ZipInfo(name, date_time=(2026, 11, 1, 10, 0, 0))
            z.writestr(zi, data)
    return buf.getvalue()


def content_set(tag: str) -> dict[str, bytes]:
    """フィクスチャ毎に内容を変える（ハッシュ衝突を避ける）。パス → 内容。"""
    rng = random.Random(f"{SEED}-{tag}")
    return {
        "DCIM/IMG_0001.JPG": make_jpeg(rng, 320, 240),
        "DCIM/IMG_0002.JPG": make_jpeg(rng, 400, 300),
        "DCIM/IMG_0003.JPG": make_jpeg(rng, 360, 270),
        "DOCS/REPORT.PDF": make_pdf(f"resq fixture {tag} report", 30000),
        "DOCS/MEMO.DOCX": make_docx(rng, f"memo {tag}", 400),
        "KEEP.PDF": make_pdf(f"resq fixture {tag} keep", 9000),
    }


# ---------------------------------------------------------------- FAT 操作
def new_fat(path: Path, mb: int = FS_MB) -> None:
    if path.exists():
        path.unlink()
    # -C: ファイルを作成してそこにファイルシステムを作る（デバイスではない）
    sh("mkfs.vfat", "-C", "-F", "32", "-s", "1", "-n", "RESQFIX", "-i", "1A2B3C4D",
       str(path), str(mb * 1024))


def put_files(img: Path, files: dict[str, bytes], tmp: Path, offset: int = 0) -> None:
    target = f"{img}@@{offset}" if offset else str(img)
    dirs = sorted({str(Path(p).parent) for p in files if str(Path(p).parent) != "."})
    for d in dirs:
        sh("mmd", "-i", target, f"::/{d}")
    for rel, data in files.items():
        src = tmp / rel.replace("/", "_")
        src.write_bytes(data)
        sh("mcopy", "-i", target, str(src), f"::/{rel}")
        src.unlink()


def del_files(img: Path, rels: list[str], offset: int = 0) -> None:
    target = f"{img}@@{offset}" if offset else str(img)
    for rel in rels:
        sh("mdel", "-i", target, f"::/{rel}")


def entries(files: dict[str, bytes], deleted: set[str], overwritten: set[str] = frozenset()) -> list[dict]:
    out = []
    for rel, data in files.items():
        state = "overwritten" if rel in overwritten else "deleted" if rel in deleted else "present"
        out.append({"path": rel, "name": Path(rel).name, "size": len(data),
                    "sha256": sha256(data), "state": state,
                    "type": Path(rel).suffix.lower().lstrip(".")})
    return out


# ---------------------------------------------------------------- 各フィクスチャ
def fx_deleted(tmp: Path) -> dict:
    img = OUT / "deleted.img"
    files = content_set("deleted")
    new_fat(img)
    put_files(img, files, tmp)
    gone = ["DCIM/IMG_0002.JPG", "DOCS/REPORT.PDF", "DOCS/MEMO.DOCX"]
    del_files(img, gone)
    return {"file": img.name, "scenario": "削除のみ", "files": entries(files, set(gone))}


def fx_overwrite(tmp: Path) -> dict:
    img = OUT / "overwrite.img"
    files = content_set("overwrite")
    new_fat(img)
    put_files(img, files, tmp)
    gone = ["DCIM/IMG_0001.JPG", "DCIM/IMG_0003.JPG"]
    del_files(img, gone)
    # IMG_0003 のデータ領域をゼロで上書き（削除後に別データで上書きされた状況の再現）
    raw = bytearray(img.read_bytes())
    target = files["DCIM/IMG_0003.JPG"]
    pos = raw.find(target[:4096])
    assert pos > 0, "fixture content not found in image"
    raw[pos:pos + len(target)] = b"\0" * len(target)
    img.write_bytes(raw)
    return {"file": img.name, "scenario": "削除＋一部上書き",
            "files": entries(files, set(gone), {"DCIM/IMG_0003.JPG"})}


def fx_quickformat(tmp: Path) -> dict:
    img = OUT / "quickformat.img"
    files = content_set("quickformat")
    new_fat(img)
    put_files(img, files, tmp)
    # クイックフォーマット＝管理情報だけ作り直す。データ領域は残る。
    # mkfs.vfat -C は新規ファイル専用のため、別ファイルに作った FS のメタデータ領域だけを書き戻す
    fresh = tmp / "fresh.img"
    sh("mkfs.vfat", "-C", "-F", "32", "-s", "1", "-n", "NEWVOL", "-i", "5E6F7A8B",
       str(fresh), str(FS_MB * 1024))
    f = fresh.read_bytes()
    reserved = struct.unpack_from("<H", f, 14)[0]
    nfats = f[16]
    fatsz = struct.unpack_from("<I", f, 36)[0]
    root_clus = struct.unpack_from("<I", f, 44)[0]
    meta_end = (reserved + nfats * fatsz) * 512
    root_off = meta_end + (root_clus - 2) * 512  # -s 1 → 1 cluster = 512B
    raw = bytearray(img.read_bytes())
    raw[:meta_end] = f[:meta_end]
    raw[root_off:root_off + 512] = f[root_off:root_off + 512]
    img.write_bytes(raw)
    fresh.unlink()
    return {"file": img.name, "scenario": "クイックフォーマット後",
            "files": entries(files, set(files))}


def fx_parttable(tmp: Path) -> dict:
    img = OUT / "parttable.img"
    files = content_set("parttable")
    part = tmp / "part.img"
    new_fat(part)
    put_files(part, files, tmp)
    start = 2048
    p = part.read_bytes()
    nsect = len(p) // 512
    mbr = bytearray(512)
    struct.pack_into("<I", mbr, 440, 0x52455351)  # disk signature
    entry = struct.pack("<B3sB3sII", 0x00, b"\xfe\xff\xff", 0x0C, b"\xfe\xff\xff", start, nsect)
    mbr[446:462] = entry
    mbr[510:512] = b"\x55\xaa"
    with img.open("wb") as fh:
        fh.write(mbr)
        fh.write(b"\0" * (start * 512 - 512))
        fh.write(p)
        fh.write(b"\0" * (1024 * 1024))
    (OUT / "parttable_intact.img").write_bytes(img.read_bytes())
    # パーティション表を削除（エントリをゼロに）
    with img.open("r+b") as fh:
        fh.seek(446)
        fh.write(b"\0" * 64)
    part.unlink()
    return {"file": img.name, "scenario": "パーティション表削除", "partition_offset_sectors": start,
            "files": entries(files, set())}


def fx_corrupt() -> dict:
    d = OUT / "corrupt"
    d.mkdir(exist_ok=True)
    rng = random.Random(f"{SEED}-corrupt")
    good_jpg = make_jpeg(rng, 300, 200)
    good_pdf = make_pdf("corrupt fixture", 2000)
    good_docx = make_docx(rng, "corrupt", 50)
    samples = {
        "good.jpg": good_jpg,
        "truncated.jpg": good_jpg[: len(good_jpg) // 2],
        "garbage.jpg": good_jpg[:20] + bytes(rng.randrange(256) for _ in range(4000)),
        "good.pdf": good_pdf,
        "truncated.pdf": good_pdf[: len(good_pdf) // 2],
        "good.docx": good_docx,
        "broken.docx": good_docx[:200] + b"\0" * 500 + good_docx[700:],
        "zero.bin": b"\0" * 8192,
    }
    for n, b in samples.items():
        (d / n).write_bytes(b)
    return {"dir": "corrupt", "files": {n: sha256(b) for n, b in samples.items()}}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / ".tmp"
    tmp.mkdir(exist_ok=True)
    expected = {
        "generator": "scripts/fixturegen.py",
        "seed": SEED,
        "images": {
            "deleted": fx_deleted(tmp),
            "overwrite": fx_overwrite(tmp),
            "quickformat": fx_quickformat(tmp),
            "parttable": fx_parttable(tmp),
        },
        "corrupt": fx_corrupt(),
    }
    for v in expected["images"].values():
        v["image_sha256"] = sha256((OUT / v["file"]).read_bytes())
    (OUT / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2))
    tmp.rmdir()
    print(f"fixtures written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
