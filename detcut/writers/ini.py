"""AviUtl の INI 風テキスト（.aup2 / .object / .exo 共通）の読み書き。

セクションとキーの出現順を保持する（キーの重複・順序は実機の出力どおりに残す）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SEC_RE = re.compile(r"^\[(.+)\]$")


@dataclass
class Section:
    name: str
    entries: list[tuple[str, str | None]] = field(default_factory=list)

    def get(self, key: str, default: str | None = None) -> str | None:
        for k, v in self.entries:
            if k == key:
                return v
        return default

    def set(self, key: str, value: str) -> None:
        for i, (k, _) in enumerate(self.entries):
            if k == key:
                self.entries[i] = (k, value)
                return
        self.entries.append((key, value))

    def keys(self) -> list[str]:
        return [k for k, _ in self.entries]


def parse_ini(text: str) -> list[Section]:
    if text.startswith("﻿"):
        text = text[1:]
    sections: list[Section] = []
    cur: Section | None = None
    for line in re.split(r"\r\n|\n|\r", text):
        if line == "":
            continue
        m = _SEC_RE.match(line)
        if m:
            cur = Section(m.group(1))
            sections.append(cur)
            continue
        if cur is None:
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cur.entries.append((k, v))
        else:
            cur.entries.append((line, None))
    return sections


def serialize_ini(sections: list[Section], newline: str = "\r\n") -> str:
    lines: list[str] = []
    for s in sections:
        lines.append(f"[{s.name}]")
        for k, v in s.entries:
            lines.append(k if v is None else f"{k}={v}")
    return newline.join(lines) + newline


def clean_value(v: str) -> str:
    """1行1エントリの形式を壊さないよう、値の改行を取り除く。"""
    return str(v).replace("\r", "").replace("\n", "")
