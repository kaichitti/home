"""辞書置換（F8）。固有名詞の表記ゆれを、ファイルに書いた順にルール表で置換する。

TSV 形式（UTF-8）:
    アイフォン<TAB>iPhone
    re:ギャラクシー\\s*(\\d+)<TAB>Galaxy \\1
    # で始まる行と空行は無視
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from detcut.common import DetCutError


@dataclass(frozen=True)
class DictRule:
    pattern: re.Pattern
    replacement: str
    is_regex: bool
    line: int


def load_dictionary(path: str | None) -> list[DictRule]:
    if not path:
        return []
    try:
        text = open(path, "rb").read().decode("utf-8-sig")
    except OSError as e:
        raise DetCutError(f"辞書ファイルを読めません: {path}") from e
    rules = []
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" not in line:
            raise DetCutError(f"辞書 {path}:{no} にタブ区切りがありません: {line!r}")
        src, dst = line.split("\t", 1)
        dst = dst.rstrip("\r")
        if src.startswith("re:"):
            try:
                rx = re.compile(src[3:])
            except re.error as e:
                raise DetCutError(f"辞書 {path}:{no} の正規表現が不正です: {e}") from e
            rules.append(DictRule(rx, dst, True, no))
        else:
            if not src:
                continue
            rules.append(DictRule(re.compile(re.escape(src)), dst, False, no))
    return rules


def apply_text(text: str, rules: list[DictRule]) -> str:
    for r in rules:
        text = r.pattern.sub(r.replacement if r.is_regex else lambda m, d=r.replacement: d, text)
    return text
