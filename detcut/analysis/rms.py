"""窓エネルギー（二乗和）と dBFS の変換。

判定は「二乗和 >= しきい値エネルギー」の比較だけで行い、対数は表示・レポート用にだけ使う。
dBFS = 10*log10(二乗和 / (窓長 * 32768^2)) = 20*log10(rms/32768)。
"""

from __future__ import annotations

import math

import numpy as np

from detcut.common import fmt_fixed

FULL_SCALE_SQ = 32768 * 32768
FLOOR_DB = -120.0


def db_to_energy(db: float, window: int) -> float:
    return window * FULL_SCALE_SQ * math.pow(10.0, db / 10.0)


def energy_to_db(energy: int, window: int) -> float:
    if energy <= 0:
        return FLOOR_DB
    v = 10.0 * math.log10(energy / (window * FULL_SCALE_SQ))
    return max(FLOOR_DB, v)


def fmt_db(energy: int, window: int) -> str:
    return fmt_fixed(energy_to_db(int(energy), window), 1)


def max_energy(energies: np.ndarray, w0: int, w1: int) -> int:
    if w1 <= w0:
        return 0
    return int(energies[w0:w1].max())


def db_histogram(energies: np.ndarray, window: int, lo: int = -90, hi: int = 0) -> list[tuple[int, int]]:
    """1dB刻みのヒストグラム [(dB下端, 窓数)]。境界はエネルギー値で比較するので決定論的。"""
    edges = np.array([db_to_energy(float(d), window) for d in range(lo, hi + 1)], dtype=np.float64)
    idx = np.searchsorted(edges, energies.astype(np.float64), side="right")
    counts = np.bincount(idx, minlength=len(edges) + 1)
    out = [(lo - 1, int(counts[0]))]  # lo 未満
    for i in range(1, len(edges)):
        out.append((lo + i - 1, int(counts[i])))
    out.append((hi, int(counts[len(edges)])))
    return out


def envelope_db(energies: np.ndarray, window: int, buckets: int) -> list[float]:
    """GUIの波形表示用：buckets 個の区間ごとの最大 dB（表示専用）。"""
    n = energies.shape[0]
    if n == 0 or buckets <= 0:
        return []
    out = []
    for i in range(buckets):
        a = i * n // buckets
        b = max(a + 1, (i + 1) * n // buckets)
        out.append(energy_to_db(int(energies[a:b].max()), window))
    return out
