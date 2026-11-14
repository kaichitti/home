"""種別判定と「開けるか」の検証（S8 統合と catalog で共用）。

結果:
  OK          開ける
  PARTIAL     開けるが一部破損
  BROKEN      開けない（破損）
  ZERO        中身がすべてゼロ（上書き済み）→ 復旧扱いにしない
  EMPTY       0 バイト
  UNVERIFIED  種別は分かるが検証手段がない
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

OK, PARTIAL, BROKEN, ZERO, EMPTY, UNVERIFIED = "OK", "PARTIAL", "BROKEN", "ZERO", "EMPTY", "UNVERIFIED"
NOT_RECOVERED = (BROKEN, ZERO, EMPTY)

IMAGE_KINDS = {"jpg", "png", "gif", "bmp", "tif", "webp"}

KIND_LABEL = {
    "jpg": "写真(JPEG)", "png": "画像(PNG)", "gif": "画像(GIF)", "bmp": "画像(BMP)", "tif": "画像(TIFF)",
    "webp": "画像(WebP)", "heic": "写真(HEIC)", "pdf": "PDF", "docx": "Word", "xlsx": "Excel",
    "pptx": "PowerPoint", "zip": "ZIP", "ole": "Office(旧形式)", "mp4": "動画(MP4)", "mov": "動画(MOV)",
    "mp3": "音楽(MP3)", "wav": "音声(WAV)", "avi": "動画(AVI)", "txt": "テキスト", "bin": "不明",
}


@dataclass
class Result:
    kind: str
    status: str
    detail: str = ""


def detect_kind(head: bytes, name: str = "") -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head.startswith(b"BM") and ext == "bmp":
        return "bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "avi"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"mif1"):
            return "heic"
        if brand == b"qt  ":
            return "mov"
        return "mp4"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        if ext in ("docx", "xlsx", "pptx"):
            return ext
        return "zip"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "ole"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return "mp3"
    if ext in ("txt", "csv", "log", "md", "ini", "xml", "html", "htm", "json"):
        return "txt"
    return "bin"


def _all_zero(path: Path) -> bool:
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            if chunk.count(0) != len(chunk):
                return False
    return True


def _check_image(path: Path) -> Result:
    from PIL import Image, ImageFile

    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
        return Result("", OK)
    except Exception as e:  # noqa: BLE001
        first = str(e)
    prev = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    try:
        with Image.open(path) as im:
            im.load()
        return Result("", PARTIAL, f"一部のみ表示可: {first}")
    except Exception as e:  # noqa: BLE001
        return Result("", BROKEN, str(e))
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = prev


def _check_pdf(path: Path) -> Result:
    data = path.read_bytes()
    tail = data[-4096:]
    if b"%%EOF" not in tail or b"startxref" not in tail:
        return Result("", PARTIAL, "末尾（%%EOF/startxref）がない：途中で切れている可能性")
    m = re.search(rb"startxref\s+(\d+)", tail)
    if not m:
        return Result("", PARTIAL, "startxref が読めない")
    xref = int(m.group(1))
    if xref >= len(data):
        return Result("", PARTIAL, "xref の位置がファイル外")
    at = data[xref:xref + 64].lstrip()
    if not (at.startswith(b"xref") or re.match(rb"\d+\s+\d+\s+obj", at)):
        return Result("", PARTIAL, "xref の位置に表がない")
    if data.count(b"endobj") == 0:
        return Result("", BROKEN, "オブジェクトがない")
    return Result("", OK)


def _check_zip(path: Path, kind: str) -> Result:
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            bad = z.testzip()
    except (zipfile.BadZipFile, OSError, EOFError) as e:
        return Result(kind, BROKEN, f"ZIP 構造が壊れている: {e}")
    except Exception as e:  # noqa: BLE001 - 破損データでは様々な例外が出る
        return Result(kind, PARTIAL, f"一部メンバーが読めない: {e}")
    if "[Content_Types].xml" in names:
        if any(n.startswith("word/") for n in names):
            kind = "docx"
        elif any(n.startswith("xl/") for n in names):
            kind = "xlsx"
        elif any(n.startswith("ppt/") for n in names):
            kind = "pptx"
    if bad is not None:
        return Result(kind, PARTIAL, f"破損メンバー: {bad}")
    return Result(kind, OK)


def _check_text(path: Path) -> Result:
    data = path.read_bytes()[: 1 << 20]
    for enc in ("utf-8", "cp932", "utf-16"):
        try:
            data.decode(enc)
            return Result("", OK)
        except UnicodeDecodeError:
            continue
    return Result("", PARTIAL, "文字コードを判定できない")


def _check_mp4(path: Path) -> Result:
    data = path.read_bytes() if path.stat().st_size < (64 << 20) else b""
    if not data:
        return Result("", UNVERIFIED, "大きいため簡易検証のみ")
    return Result("", OK) if b"moov" in data else Result("", PARTIAL, "moov ボックスがない（再生できない可能性）")


def validate(path: Path, name: str | None = None) -> Result:
    size = path.stat().st_size
    with open(path, "rb") as fh:
        head = fh.read(64)
    kind = detect_kind(head, name or path.name)
    if size == 0:
        return Result(kind, EMPTY, "0 バイト")
    if _all_zero(path):
        return Result(kind, ZERO, "中身がすべてゼロ（上書き済み）")
    if kind in IMAGE_KINDS:
        r = _check_image(path)
    elif kind == "pdf":
        r = _check_pdf(path)
    elif kind in ("zip", "docx", "xlsx", "pptx"):
        r = _check_zip(path, kind)
        return r
    elif kind == "txt":
        r = _check_text(path)
    elif kind in ("mp4", "mov"):
        r = _check_mp4(path)
    else:
        r = Result("", UNVERIFIED, "検証手段なし")
    r.kind = kind
    return r
