"""残骸スキャンの共通部：エントリ表現・フォルダツリーの再構築・取り出し。

各 FS のスキャナは「ディレクトリ情報の残骸」を Entry の列として返す。
  parent : そのエントリが見つかったディレクトリのキー（"root" / "c<クラスタ>" / "r<MFT番号>"）
  key    : ディレクトリ自身のキー（ディレクトリのときのみ）
  runs   : データ位置（イメージ内バイトオフセット, 長さ）。None のオフセットは疎領域（ゼロ）
イメージは読むだけ。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..manifest import LOST_DIR

READ_CHUNK = 4 * 1024 * 1024


@dataclass
class Entry:
    fs: str
    name: str
    is_dir: bool
    deleted: bool
    size: int
    parent: str | None
    key: str | None = None
    runs: list[tuple[int | None, int]] = field(default_factory=list)
    resident: bytes | None = None
    start_cluster: int | None = None
    meta: dict = field(default_factory=dict)

    @property
    def data_offset(self) -> int | None:
        for off, _ln in self.runs:
            return off
        return None

    def ident(self) -> tuple:
        first = self.runs[0] if self.runs else None
        return (self.fs, self.parent, self.name.lower(), self.size, first, self.is_dir)

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("resident")
        d["has_resident"] = self.resident is not None
        d["data_offset"] = self.data_offset
        return d


@dataclass
class VolumeGeometry:
    fs: str
    volume_offset: int          # バイト
    cluster_size: int
    data_start: int             # クラスタ 2（NTFS は LCN 0）のイメージ内バイトオフセット
    cluster_count: int
    first_cluster: int = 2      # FAT/exFAT は 2 始まり、NTFS は 0

    def cluster_offset(self, c: int) -> int:
        return self.data_start + (c - self.first_cluster) * self.cluster_size

    def cluster_at(self, img_offset: int) -> int | None:
        rel = img_offset - self.data_start
        if rel < 0 or rel % self.cluster_size:
            return None
        c = rel // self.cluster_size + self.first_cluster
        return c if c < self.first_cluster + self.cluster_count else None


def dedupe(entries: list[Entry]) -> list[Entry]:
    seen: dict[tuple, Entry] = {}
    for e in entries:
        k = e.ident()
        if k not in seen or (seen[k].deleted and not e.deleted):
            seen[k] = e
    return list(seen.values())


def build_paths(entries: list[Entry], root_keys: set[str]) -> dict[int, tuple[list[str], bool]]:
    """各エントリのパス（部品のリスト）と、ルートまで名前が揃っているか（path_known）を返す。"""
    dirs: dict[str, Entry] = {}
    for e in entries:
        if e.is_dir and e.key and e.key not in root_keys:
            cur = dirs.get(e.key)
            if cur is None or (cur.deleted and not e.deleted):
                dirs[e.key] = e

    cache: dict[str, tuple[list[str], bool]] = {}

    def dir_path(key: str | None, depth: int = 0) -> tuple[list[str], bool]:
        if key is None or key in root_keys:
            return [], True
        if key in cache:
            return cache[key]
        if depth > 64:
            return [f"{LOST_DIR}_{key}"], False
        d = dirs.get(key)
        if d is None:
            res = ([f"{LOST_DIR}_{key}"], False)
        else:
            name = d.name or f"{LOST_DIR}_{key}"
            if d.parent == key:
                res = ([name], False)
            else:
                parts, known = dir_path(d.parent, depth + 1)
                res = (parts + [name], known and bool(d.name))
        cache[key] = res
        return res

    out = {}
    for e in entries:
        parts, known = dir_path(e.parent)
        out[id(e)] = (parts + [e.name], known)
    return out


def read_runs(image: Path, entry: Entry, limit: int | None = None) -> bytes:
    """データを取り出す（イメージは読み取り専用で開く）。"""
    if entry.resident is not None:
        return entry.resident[: entry.size]
    want = entry.size if limit is None else min(entry.size, limit)
    out = bytearray()
    with open(image, "rb") as fh:
        for off, ln in entry.runs:
            if len(out) >= want:
                break
            n = min(ln, want - len(out))
            if off is None:
                out += b"\0" * n
            else:
                fh.seek(off)
                chunk = fh.read(n)
                out += chunk
                if len(chunk) < n:
                    break
    return bytes(out[:want])


def iter_clusters(image: Path, geo: VolumeGeometry, first: int | None = None, last: int | None = None):
    """(クラスタ番号, バイト列) を順に返す。大きなまとまりで読んでから切り出す。"""
    first = geo.first_cluster if first is None else first
    last = geo.first_cluster + geo.cluster_count - 1 if last is None else last
    cs = geo.cluster_size
    per = max(1, READ_CHUNK // cs)
    size = image.stat().st_size
    with open(image, "rb") as fh:
        c = first
        while c <= last:
            off = geo.cluster_offset(c)
            if off >= size:
                break
            n = min(per, last - c + 1)
            fh.seek(off)
            buf = fh.read(n * cs)
            for i in range(len(buf) // cs):
                yield c + i, buf[i * cs:(i + 1) * cs]
            c += n
