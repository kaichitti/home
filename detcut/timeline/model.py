"""中間表現（タイムラインモデル）。書き出し形式（.aup2/.exo）に依存しない。"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

KINDS = ("video", "audio", "text", "image", "se", "bgm")


@dataclass(frozen=True, order=True)
class SourceRange:
    """元素材上の範囲（解析サンプル単位、終端は含まない）。"""
    start_sample: int
    end_sample: int


@dataclass(frozen=True)
class Clip:
    id: str                    # "v0001" など。連番で決定論的に採番
    kind: str                  # video | audio | text | image | se | bgm
    layer: int                 # 1始まり（AviUtlの画面上のレイヤー番号）
    tl_start: int              # タイムライン上の開始フレーム（0始まり）
    tl_end: int                # 終端フレーム（含む）
    src: SourceRange | None = None
    file: str | None = None
    params: tuple = ()         # ソート可能な (key, value) のタプル
    reason: str = ""
    group: int = 0             # 同じ値の映像・音声を連携（.exo の group）

    def p(self, key: str, default: Any = None) -> Any:
        for k, v in self.params:
            if k == key:
                return v
        return default

    @property
    def length(self) -> int:
        return self.tl_end - self.tl_start + 1

    def sort_key(self) -> tuple:
        return (self.layer, self.tl_start, self.id)


def make_params(**kw: Any) -> tuple:
    return tuple(sorted((k, _freeze(v)) for k, v in kw.items() if v is not None))


def _freeze(v: Any) -> Any:
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    return v


@dataclass
class Timeline:
    fps: Fraction
    width: int
    height: int
    audio_rate: int
    audio_ch: int = 2
    clips: list[Clip] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    styles: dict[str, dict[str, Any]] = field(default_factory=dict)  # テロップのスタイル（style_id -> style）

    @property
    def length(self) -> int:
        return max((c.tl_end + 1 for c in self.clips), default=0)

    def sorted_clips(self) -> list[Clip]:
        return sorted(self.clips, key=Clip.sort_key)

    def to_json(self) -> dict[str, Any]:
        def clip_json(c: Clip) -> dict[str, Any]:
            return {
                "id": c.id, "kind": c.kind, "layer": c.layer, "tl_start": c.tl_start, "tl_end": c.tl_end,
                "src": [c.src.start_sample, c.src.end_sample] if c.src else None,
                "file": c.file, "params": {k: _thaw(v) for k, v in c.params}, "reason": c.reason, "group": c.group,
            }
        return {
            "fps": self.fps, "width": self.width, "height": self.height,
            "audio_rate": self.audio_rate, "audio_ch": self.audio_ch, "length": self.length,
            "meta": self.meta, "styles": self.styles,
            "clips": [clip_json(c) for c in self.sorted_clips()],
        }


def _thaw(v: Any) -> Any:
    if isinstance(v, tuple):
        if v and all(isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], str) for x in v):
            return {k: _thaw(x) for k, x in v}
        return [_thaw(x) for x in v]
    return v
