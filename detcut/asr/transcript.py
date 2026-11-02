"""文字起こし結果の形式（JSON・SRT）。時刻はすべて整数ミリ秒。

JSON はキャッシュ兼「人が直した確定版」として使える。
一度Whisperで作ったら、誤字を直したファイルを telop.transcript_file に指定すれば、
以降はAIを使わず完全に決定論的にテロップが作られる。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from detcut.common import DetCutError, dumps_json, fmt_ms


@dataclass
class Word:
    start_ms: int
    end_ms: int
    text: str


@dataclass
class TSegment:
    start_ms: int
    end_ms: int
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    segments: list[TSegment] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "format": "detcut-transcript",
            "version": 1,
            "meta": self.meta,
            "segments": [
                {
                    "start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text,
                    "words": [{"start_ms": w.start_ms, "end_ms": w.end_ms, "text": w.text} for w in s.words],
                }
                for s in self.segments
            ],
        }

    def dumps(self) -> str:
        return dumps_json(self.to_json())


def from_json(data: dict[str, Any]) -> Transcript:
    segs = []
    for s in data.get("segments", []):
        words = [Word(int(w["start_ms"]), int(w["end_ms"]), str(w["text"])) for w in s.get("words", [])]
        segs.append(TSegment(int(s["start_ms"]), int(s["end_ms"]), str(s.get("text", "")), words))
    segs.sort(key=lambda s: (s.start_ms, s.end_ms))
    return Transcript(segs, dict(data.get("meta", {})))


_SRT_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


def _srt_ms(s: str) -> int:
    m = _SRT_TIME.search(s)
    if not m:
        raise DetCutError(f"SRTの時刻を読めません: {s!r}")
    h, mi, se, ms = m.groups()
    return ((int(h) * 60 + int(mi)) * 60 + int(se)) * 1000 + int(ms.ljust(3, "0"))


def parse_srt(text: str) -> Transcript:
    blocks = re.split(r"\r?\n\s*\r?\n", text.replace("﻿", "").strip())
    segs = []
    for b in blocks:
        lines = [ln for ln in re.split(r"\r?\n", b) if ln.strip() != ""]
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue
        a, _, c = lines[idx].partition("-->")
        body = "\n".join(lines[idx + 1:]).strip()
        if body:
            segs.append(TSegment(_srt_ms(a), _srt_ms(c), body))
    segs.sort(key=lambda s: (s.start_ms, s.end_ms))
    return Transcript(segs, {"source": "srt"})


def to_srt(t: Transcript) -> str:
    out = []
    for i, s in enumerate(t.segments, 1):
        a, b = fmt_ms(s.start_ms).replace(".", ","), fmt_ms(s.end_ms).replace(".", ",")
        out.append(f"{i}\n{a} --> {b}\n{s.text.strip()}\n")
    return "\n".join(out)


def load_transcript(path: str) -> Transcript:
    try:
        raw = open(path, "rb").read().decode("utf-8-sig")
    except OSError as e:
        raise DetCutError(f"文字起こしファイルを読めません: {path}") from e
    if path.lower().endswith(".srt"):
        return parse_srt(raw)
    try:
        return from_json(json.loads(raw))
    except (ValueError, KeyError, TypeError) as e:
        raise DetCutError(f"文字起こしJSONの形式が正しくありません: {path} ({e})") from e
