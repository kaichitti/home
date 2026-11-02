"""ズーム・カット割り（F12）。

キープ区間（カット後の映像のまとまり）を順に見て、同じ画が min_shot_ms 以上続いたら、
次の編集点で拡大率を levels の次の値（例：100% → 110% → 100%…）に切り替える。
split_long_ms を指定すると、長すぎる区間をその長さ以下に等分割して切り替え点を作る。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from detcut.common import ceil_div
from detcut.edit.cutlist import Keep
from detcut.timebase import TimeBase


@dataclass(frozen=True)
class VideoPiece:
    keep_index: int
    src_start_frame: int
    n_frames: int
    tl_start: int
    level: int          # levels のインデックス
    split: bool         # 長尺分割で生まれた切れ目の後か


def plan_pieces(keeps: list[Keep], zoom_cfg: dict[str, Any], tb: TimeBase) -> list[VideoPiece]:
    enabled = bool(zoom_cfg["enabled"])
    split = tb.ms_to_frames_round(int(zoom_cfg["split_long_ms"])) if enabled else 0
    raw: list[tuple[int, int, int, int, bool]] = []  # keep, src_start, n, tl_start, split
    for k in keeps:
        n = k.n_frames
        parts = ceil_div(n, split) if split > 0 and n > split else 1
        for p in range(parts):
            a = n * p // parts
            b = n * (p + 1) // parts
            raw.append((k.index, k.src_start_frame + a, b - a, k.tl_start_frame + a, p > 0))
    pieces: list[VideoPiece] = []
    min_shot = tb.ms_to_frames_round(int(zoom_cfg["min_shot_ms"]))
    nlev = len(zoom_cfg["levels"])
    level = 0
    run = 0
    for i, (ki, s, n, t, sp) in enumerate(raw):
        if enabled and i > 0 and run >= min_shot and nlev > 1:
            level = (level + 1) % nlev
            run = 0
        run += n
        pieces.append(VideoPiece(ki, s, n, t, level if enabled else 0, sp))
    return pieces
