"""--analyze モード：音量分布からしきい値を提案する（提案値も決定論的に算出）。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from detcut.analysis.rms import db_histogram, energy_to_db


@dataclass
class Suggestion:
    noise_floor_db: float
    speech_level_db: float
    speech_on_db: int
    speech_off_db: int
    histogram: list[tuple[int, int]]


def percentile_energy(energies: np.ndarray, pct: int) -> int:
    if energies.shape[0] == 0:
        return 0
    s = np.sort(energies, kind="stable")
    idx = min(len(s) - 1, (len(s) - 1) * pct // 100)
    return int(s[idx])


def suggest(energies: np.ndarray, window: int) -> Suggestion:
    noise = energy_to_db(percentile_energy(energies, 10), window)
    speech = energy_to_db(percentile_energy(energies, 90), window)
    spread = max(0.0, speech - noise)
    off = math.floor(noise + max(3.0, min(8.0, spread * 0.25)))
    on = math.floor(off + max(3.0, min(10.0, spread * 0.2)))
    on = min(on, math.floor(speech) - 3) if speech - 3 > off else on
    on = max(on, off)
    off = max(-100, min(off, -1))
    on = max(off, min(on, -1))
    return Suggestion(
        noise_floor_db=round(noise, 1),
        speech_level_db=round(speech, 1),
        speech_on_db=int(on),
        speech_off_db=int(off),
        histogram=db_histogram(energies, window),
    )


def render_histogram(hist: list[tuple[int, int]], width: int = 50, step: int = 3) -> list[str]:
    """step dB ごとにまとめた横棒グラフ（テキスト）。"""
    merged: list[tuple[int, int]] = []
    for db, cnt in hist:
        key = (db // step) * step
        if merged and merged[-1][0] == key:
            merged[-1] = (key, merged[-1][1] + cnt)
        else:
            merged.append((key, cnt))
    peak = max((c for _, c in merged), default=0) or 1
    lines = []
    for db, cnt in merged:
        if cnt == 0:
            continue
        bar = "#" * max(1, cnt * width // peak)
        lines.append(f"{db:>5} dB | {bar} {cnt}")
    return lines
