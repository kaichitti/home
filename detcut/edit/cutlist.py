"""カットリスト生成（F1 ジェットカット / F2 短発話の除去・結合 / F3 間の圧縮）。

処理順：余白付与 → 近接区間の結合 → (compress) 間の圧縮 → 手動で残す区間の追加
        → 手動で切る区間の除去 → フレーム境界へ丸め（始点は床・終点は天井）→ 重なりの再結合。
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from detcut.analysis.rms import fmt_db, max_energy
from detcut.analysis.segments import SpeechResult
from detcut.common import merge_intervals, overlap, subtract_intervals
from detcut.timebase import TimeBase


@dataclass(frozen=True)
class Keep:
    index: int
    src_start_sample: int   # 余白・結合後の区間（フレーム丸め前）
    src_end_sample: int
    src_start_frame: int    # フレーム境界に丸めた元素材上の範囲 [start, end)
    src_end_frame: int
    tl_start_frame: int     # タイムライン上の開始フレーム
    rule: str               # F1 / F3 / manual / none

    @property
    def n_frames(self) -> int:
        return self.src_end_frame - self.src_start_frame

    @property
    def tl_end_frame(self) -> int:
        """タイムライン上の終端フレーム（含む）。"""
        return self.tl_start_frame + self.n_frames - 1


@dataclass(frozen=True)
class Cut:
    index: int
    src_start_frame: int
    src_end_frame: int
    src_start_sample: int
    src_end_sample: int
    tl_frame: int           # 編集点（カット直後に続くタイムライン上のフレーム）
    rule: str               # F1 / F2 / F3 / manual
    reason: str
    max_db: str

    @property
    def n_frames(self) -> int:
        return self.src_end_frame - self.src_start_frame


@dataclass
class CutList:
    tb: TimeBase
    total_samples: int
    total_src_frames: int
    keeps: list[Keep] = field(default_factory=list)
    cuts: list[Cut] = field(default_factory=list)

    @property
    def total_tl_frames(self) -> int:
        return sum(k.n_frames for k in self.keeps)

    @property
    def edit_points(self) -> list[int]:
        """カット編集点（タイムライン上で区間が切り替わるフレーム）。先頭0と末尾は含まない。"""
        return [k.tl_start_frame for k in self.keeps[1:]]

    def _starts(self) -> list[int]:
        cache = self.__dict__.get("_starts_cache")
        if cache is None or len(cache) != len(self.keeps):
            cache = [k.src_start_frame for k in self.keeps]
            self.__dict__["_starts_cache"] = cache
        return cache

    def keep_index_for_src_frame(self, f: int) -> int | None:
        i = bisect.bisect_right(self._starts(), f) - 1
        if i >= 0 and f < self.keeps[i].src_end_frame:
            return i
        return None

    def src_frame_to_tl(self, f: int) -> int | None:
        i = self.keep_index_for_src_frame(f)
        if i is None:
            return None
        k = self.keeps[i]
        return k.tl_start_frame + f - k.src_start_frame

    def src_frame_to_tl_or_next(self, f: int) -> int:
        """カットされた位置なら直後の区間の先頭（なければ末尾）を返す。"""
        t = self.src_frame_to_tl(f)
        if t is not None:
            return t
        i = bisect.bisect_right(self._starts(), f)
        if i < len(self.keeps):
            return self.keeps[i].tl_start_frame
        return self.total_tl_frames

    def src_frames_to_tl_intervals(self, f0: int, f1: int) -> list[tuple[int, int]]:
        """元素材の [f0, f1) が残っている部分をタイムライン上の [a, b) の列にする。"""
        out = []
        i = max(0, bisect.bisect_right(self._starts(), f0) - 1)
        while i < len(self.keeps) and self.keeps[i].src_start_frame < f1:
            k = self.keeps[i]
            a, b = max(f0, k.src_start_frame), min(f1, k.src_end_frame)
            if b > a:
                out.append((k.tl_start_frame + a - k.src_start_frame, k.tl_start_frame + b - k.src_start_frame))
            i += 1
        return out

    def to_json(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {
            **meta,
            "fps": self.tb.fps,
            "analysis_sample_rate": self.tb.sample_rate,
            "total_src_frames": self.total_src_frames,
            "total_tl_frames": self.total_tl_frames,
            "keep": [
                {
                    "src_start_sample": k.src_start_sample, "src_end_sample": k.src_end_sample,
                    "src_start_frame": k.src_start_frame, "src_end_frame": k.src_end_frame,
                    "tl_start_frame": k.tl_start_frame, "tl_end_frame": k.tl_end_frame, "rule": k.rule,
                }
                for k in self.keeps
            ],
            "cut": [
                {
                    "src_start_frame": c.src_start_frame, "src_end_frame": c.src_end_frame,
                    "src_start_sample": c.src_start_sample, "src_end_sample": c.src_end_sample,
                    "tl_frame": c.tl_frame, "rule": c.rule, "reason": c.reason, "max_db": c.max_db,
                }
                for c in self.cuts
            ],
        }


def _ms_to_samples(ms: int, sr: int) -> int:
    return ms * sr // 1000


def build_cutlist(
    speech: SpeechResult,
    energies: np.ndarray,
    cut_cfg: dict[str, Any],
    tb: TimeBase,
    total_src_frames: int | None = None,
) -> CutList:
    sr = speech.sample_rate
    total = speech.total_samples
    max_frames = tb.sample_to_frame_floor(total)
    if total_src_frames is not None:
        max_frames = min(max_frames, total_src_frames)
    cl = CutList(tb=tb, total_samples=total, total_src_frames=max_frames)

    manual_keep = [(_ms_to_samples(a, sr), _ms_to_samples(b, sr)) for a, b in cut_cfg["keep_ranges"]]
    manual_cut = merge_intervals([(_ms_to_samples(a, sr), _ms_to_samples(b, sr)) for a, b in cut_cfg["force_cut_ranges"]])
    compressed: list[tuple[int, int, int]] = []  # (gap_start, gap_end, 元の長さ)

    if not cut_cfg["enabled"]:
        intervals = [(0, total)]
        base_rule = "none"
    else:
        base_rule = "F1"
        pb = _ms_to_samples(cut_cfg["pad_before_ms"], sr)
        pa = _ms_to_samples(cut_cfg["pad_after_ms"], sr)
        padded = [(max(0, s.start - pb), min(total, s.end + pa)) for s in speech.segments]
        intervals = merge_intervals(padded, gap=_ms_to_samples(cut_cfg["merge_gap_ms"], sr))
        if cut_cfg["mode"] == "compress" and intervals:
            c = _ms_to_samples(cut_cfg["compress_to_ms"], sr)
            out = [list(intervals[0])]
            for a, b in intervals[1:]:
                prev = out[-1]
                gap = a - prev[1]
                if gap <= c:
                    prev[1] = b
                    continue
                left = c // 2
                compressed.append((prev[1] + left, a - (c - left), gap))
                prev[1] += left
                out.append([a - (c - left), b])
            intervals = [(a, b) for a, b in out]
    if manual_keep:
        intervals = merge_intervals(intervals + manual_keep)
    if manual_cut:
        intervals = subtract_intervals(intervals, manual_cut)

    # フレーム境界へ丸め（始点は床、終点は天井）→ フレーム上で重なれば結合
    framed: list[list[int]] = []  # [f0, f1, s0, s1]
    for a, b in intervals:
        f0 = tb.sample_to_frame_floor(a)
        f1 = min(tb.sample_to_frame_ceil(b), max_frames)
        if f1 <= f0:
            continue
        if framed and f0 <= framed[-1][1]:
            framed[-1][1] = max(framed[-1][1], f1)
            framed[-1][3] = max(framed[-1][3], b)
        else:
            framed.append([f0, f1, a, b])

    tl = 0
    for i, (f0, f1, s0, s1) in enumerate(framed):
        rule = base_rule
        if base_rule != "none":
            has_speech = any(overlap(s0, s1, s.start, s.end) for s in speech.segments)
            if not has_speech and any(overlap(s0, s1, a, b) for a, b in manual_keep):
                rule = "manual"
            elif any(s0 <= g0 <= s1 or s0 <= g1 <= s1 for g0, g1, _ in compressed):
                rule = "F3"
        cl.keeps.append(Keep(index=i, src_start_sample=s0, src_end_sample=s1, src_start_frame=f0,
                             src_end_frame=f1, tl_start_frame=tl, rule=rule))
        tl += f1 - f0

    # カット区間（キープの補集合）と理由
    win = speech.window
    gaps: list[tuple[int, int]] = []
    pos = 0
    for k in cl.keeps:
        if k.src_start_frame > pos:
            gaps.append((pos, k.src_start_frame))
        pos = k.src_end_frame
    if pos < max_frames:
        gaps.append((pos, max_frames))
    for ci, (g0, g1) in enumerate(gaps):
        s0 = min(total, tb.frame_to_sample(g0))
        s1 = min(total, tb.frame_to_sample(g1))
        e_max = max_energy(energies, s0 // win, (s1 + win - 1) // win)
        db = fmt_db(e_max, win)
        dur_ms = (s1 - s0) * 1000 // sr
        shorts = [d for d in speech.dropped_short if overlap(s0, s1, d.start, d.end)]
        comp = [g for g in compressed if overlap(s0, s1, g[0], g[1])]
        if any(overlap(s0, s1, a, b) for a, b in manual_cut):
            rule, reason = "manual", f"manual:force_cut {dur_ms}ms"
        elif shorts:
            rule = "F2"
            reason = f"F2:short_speech x{len(shorts)} max {db}dB {dur_ms}ms"
        elif comp:
            rule = "F3"
            orig = comp[0][2] * 1000 // sr
            reason = f"F3:compress {orig}ms->{cut_cfg['compress_to_ms']}ms max {db}dB"
        else:
            rule = "F1"
            where = "leading " if g0 == 0 else ("trailing " if g1 == max_frames else "")
            reason = f"F1:{where}silence max {db}dB {dur_ms}ms"
        cl.cuts.append(Cut(index=ci, src_start_frame=g0, src_end_frame=g1, src_start_sample=s0,
                           src_end_sample=s1, tl_frame=cl.src_frame_to_tl_or_next(g1),
                           rule=rule, reason=reason, max_db=db))
    return cl
