"""章マーカー（SEの chapter ルール・章タイトルのテロップ用）。

CSV/TSV（UTF-8）: 1列目=元素材上の時刻（00:01:23.000 など）、2列目=タイトル。# 行は無視。
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from detcut.common import DetCutError, parse_time_ms


@dataclass(frozen=True)
class Chapter:
    at_ms: int
    title: str


def load_chapters(file: str | None, items: list[dict]) -> list[Chapter]:
    out: list[Chapter] = []
    for it in items:
        out.append(Chapter(parse_time_ms(it["at"]), str(it.get("title") or "")))
    if file:
        try:
            text = open(file, "rb").read().decode("utf-8-sig")
        except OSError as e:
            raise DetCutError(f"章ファイルを読めません: {file}") from e
        first = text.splitlines()[0] if text.strip() else ""
        delim = "\t" if "\t" in first else ","
        for row in csv.reader(io.StringIO(text), delimiter=delim):
            if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            if row[0].strip().lower() in ("time", "at", "時刻"):
                continue
            out.append(Chapter(parse_time_ms(row[0].strip()), row[1].strip() if len(row) > 1 else ""))
    return sorted(set(out), key=lambda c: (c.at_ms, c.title))
