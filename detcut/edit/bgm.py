"""BGM自動配置・ダッキング（F11）。

BGMをタイムライン全体にループ配置し、発話区間では音量を duck_volume に下げる。
キーフレームではなく「区間分割」で表現する（音量一定の区間＋短いフェード区間）。
フェード区間は音量トラックの直線移動を使う。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from detcut.common import merge_intervals, round_half_up
from detcut.timebase import TimeBase


@dataclass(frozen=True)
class BgmPiece:
    start: int          # タイムライン上の開始フレーム
    end: int            # 終端（含む）
    seek: Fraction      # BGMファイル内の再生開始位置（秒）
    vol_start: Fraction
    vol_end: Fraction
    loop: int


def _q(v: Fraction) -> Fraction:
    return Fraction(round_half_up(v * 100), 100)


def _vol_at(t: int, a: int, b: int, v0: Fraction, v1: Fraction) -> Fraction:
    """区間 [a, b) で v0 → v1 に直線変化するときの、フレーム t の音量（0.01刻み）。"""
    return _q(v0 + (v1 - v0) * Fraction(t - a, b - a)) if b > a else v0


def build_bgm(
    bgm_cfg: dict[str, Any],
    total_frames: int,
    speech_tl: list[tuple[int, int]],
    tb: TimeBase,
    bgm_duration: Fraction | None,
) -> list[BgmPiece]:
    if total_frames <= 0:
        return []
    vol = Fraction(str(bgm_cfg["volume"]))
    duck = Fraction(str(bgm_cfg["duck_volume"]))
    fade = tb.ms_to_frames_round(int(bgm_cfg["duck_fade_ms"]))

    # (a, b, v0, v1) の区間列を作る
    spans: list[tuple[int, int, Fraction, Fraction]] = []
    if bgm_cfg["duck"] and speech_tl:
        min_gap = max(tb.ms_to_frames_round(int(bgm_cfg["duck_min_gap_ms"])), 2 * fade)
        regions = merge_intervals([(max(0, a), min(total_frames, b)) for a, b in speech_tl], gap=min_gap)
        cursor = 0
        for a, b in regions:
            fd0 = max(cursor, a - fade)
            if fd0 > cursor:
                spans.append((cursor, fd0, vol, vol))
            if a > fd0:
                spans.append((fd0, a, vol, duck))
            spans.append((a, b, duck, duck))
            fu1 = min(total_frames, b + fade)
            if fu1 > b:
                spans.append((b, fu1, duck, vol))
            cursor = max(b, fu1)
        if cursor < total_frames:
            spans.append((cursor, total_frames, vol, vol))
    else:
        spans.append((0, total_frames, vol, vol))

    loop_len = None
    if bgm_duration and bgm_duration > 0:
        loop_len = max(1, tb.seconds_to_frames_floor(bgm_duration))

    pieces: list[BgmPiece] = []
    for a, b, v0, v1 in spans:
        cuts = [a, b]
        if loop_len:
            k = (a // loop_len + 1) * loop_len
            while k < b:
                cuts.append(k)
                k += loop_len
        cuts = sorted(set(cuts))
        for x, y in zip(cuts, cuts[1:]):
            loop = x // loop_len if loop_len else 0
            seek = tb.frame_to_seconds(x - loop * loop_len) if loop_len else tb.frame_to_seconds(x)
            pieces.append(BgmPiece(start=x, end=y - 1, seek=seek, vol_start=_vol_at(x, a, b, v0, v1),
                                   vol_end=_vol_at(y, a, b, v0, v1), loop=loop))
    return pieces
