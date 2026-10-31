"""決定論性を保つための共通ヘルパー。

- ハッシュは常に SHA-256。Python組み込みの hash() はプロセスごとに値が変わるので使わない。
- JSON は sort_keys=True・区切り文字固定で書き出す。
- 小数の文字列化は Fraction の整数演算で行い、浮動小数点の表示揺れを避ける。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable


class DetCutError(Exception):
    """利用者向けのエラー（スタックトレースを出さずにメッセージだけ表示する）。"""


# ---------------------------------------------------------------- hashing

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: str | os.PathLike, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class FileHashCache:
    """大きな動画ファイルのハッシュを (絶対パス, サイズ, mtime) で記憶して再計算を省く。

    キャッシュは高速化のためだけに使い、結果（ハッシュ値）は常に同じになる。
    """

    def __init__(self, cache_dir: str | None):
        self.path = Path(cache_dir) / "filehash.json" if cache_dir else None
        self._data: dict[str, dict[str, Any]] = {}
        if self.path and self.path.exists():
            try:
                self._data = json.loads(self.path.read_text("utf-8"))
            except (OSError, ValueError):
                self._data = {}

    def get(self, file: str) -> str:
        p = os.path.abspath(file)
        st = os.stat(p)
        key = p
        ent = self._data.get(key)
        if ent and ent.get("size") == st.st_size and ent.get("mtime_ns") == st.st_mtime_ns:
            return ent["sha256"]
        digest = sha256_file(p)
        self._data[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                write_json(self.path, self._data)
            except OSError:
                pass
        return digest


def stable_int_hash(text: str) -> int:
    """プロセス・環境に依存しない整数ハッシュ（「ランダム感」のある決定論的選択用）。"""
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


# ---------------------------------------------------------------- JSON / text output

def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, Fraction):
        return f"{obj.numerator}/{obj.denominator}" if obj.denominator != 1 else obj.numerator
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def canonical_json(obj: Any) -> str:
    """ハッシュ計算用の正規化JSON（キー順・区切り固定、改行なし）。"""
    return json.dumps(to_jsonable(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def dumps_json(obj: Any) -> str:
    """人が読む用のJSON。キー順固定・インデント固定・末尾改行あり（LF）。"""
    return json.dumps(to_jsonable(obj), sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def write_json(path: str | os.PathLike, obj: Any) -> None:
    write_bytes(path, dumps_json(obj).encode("utf-8"))


def write_bytes(path: str | os.PathLike, data: bytes) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)


# ---------------------------------------------------------------- numbers

def round_half_up(x: Fraction) -> int:
    """Fraction を四捨五入（0.5は絶対値が大きい方へ）した整数にする。"""
    if x >= 0:
        return int((x * 2 + 1) // 2)
    return -int((-x * 2 + 1) // 2)


def ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


def fmt_fixed(value: Fraction | int | float | str, digits: int, mode: str = "round") -> str:
    """数値を小数点以下 digits 桁の固定小数表記にする（整数演算のみで丸める）。

    mode: "round"（四捨五入） / "ceil"（切り上げ） / "floor"（切り捨て）
    """
    if isinstance(value, float):
        value = Fraction(repr(value))
    elif isinstance(value, str):
        value = Fraction(value)
    else:
        value = Fraction(value)
    scale = 10 ** digits
    scaled = value * scale
    if mode == "round":
        n = round_half_up(scaled)
    elif mode == "ceil":
        n = ceil_div(scaled.numerator, scaled.denominator)
    elif mode == "floor":
        n = scaled.numerator // scaled.denominator
    else:  # pragma: no cover - programming error
        raise ValueError(mode)
    sign = "-" if n < 0 else ""
    n = abs(n)
    if digits == 0:
        return f"{sign}{n}"
    return f"{sign}{n // scale}.{n % scale:0{digits}d}"


def parse_fraction(value: Any) -> Fraction:
    """'30000/1001'・'29.97'・30 などを Fraction に。"""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(repr(value))
    s = str(value).strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return Fraction(int(a.strip()), int(b.strip()))
    return Fraction(s)


# ---------------------------------------------------------------- time strings

_TIME_RE = re.compile(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$")


def parse_time_ms(value: Any) -> int:
    """'HH:MM:SS.mmm' / 'MM:SS.mmm' / 'SS.mmm' / 整数ミリ秒 をミリ秒の整数に。"""
    if isinstance(value, bool):
        raise DetCutError(f"時刻として解釈できません: {value!r}")
    if isinstance(value, int):
        return value
    s = str(value).strip()
    m = _TIME_RE.match(s)
    if not m:
        raise DetCutError(f"時刻として解釈できません: {value!r}（例: 00:01:23.500）")
    a, b, sec = m.groups()
    if b is None:
        hours, minutes = 0, int(a) if a else 0
    else:
        hours, minutes = int(a), int(b)
    ms = round_half_up(Fraction(sec) * 1000)
    return ((hours * 60 + minutes) * 60) * 1000 + ms


def parse_range_ms(value: Any) -> tuple[int, int]:
    """'00:01:23.000-00:01:30.000' または [start, end] をミリ秒の組に。"""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        a, b = parse_time_ms(value[0]), parse_time_ms(value[1])
    else:
        s = str(value)
        if "-" not in s:
            raise DetCutError(f"区間は '開始-終了' の形式で指定してください: {value!r}")
        left, right = s.split("-", 1)
        a, b = parse_time_ms(left), parse_time_ms(right)
    if b <= a:
        raise DetCutError(f"区間の終了が開始以前です: {value!r}")
    return a, b


def fmt_ms(ms: int) -> str:
    sign = "-" if ms < 0 else ""
    ms = abs(ms)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{sign}{h:02d}:{m:02d}:{s:02d}.{msec:03d}"


# ---------------------------------------------------------------- intervals

def merge_intervals(items: Iterable[tuple[int, int]], gap: int = 0) -> list[tuple[int, int]]:
    """半開区間 [a, b) のリストを結合する。隙間が gap 未満なら結合。"""
    out: list[list[int]] = []
    for a, b in sorted(items):
        if b <= a:
            continue
        if out and (a <= out[-1][1] or a - out[-1][1] < gap):
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def subtract_intervals(base: list[tuple[int, int]], cut: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """base から cut を引いた半開区間のリスト（どちらも結合済み・昇順を想定）。"""
    result: list[tuple[int, int]] = []
    for a, b in base:
        pieces = [(a, b)]
        for c, d in cut:
            nxt = []
            for x, y in pieces:
                if d <= x or c >= y:
                    nxt.append((x, y))
                    continue
                if c > x:
                    nxt.append((x, c))
                if d < y:
                    nxt.append((d, y))
            pieces = nxt
        result.extend(pieces)
    return [(a, b) for a, b in result if b > a]


def overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))
