"""発話区間の判定（ヒステリシス付きのしきい値判定・決定論的）。

1. エネルギーが speech_on_db を超えたら発話開始。
2. 発話中に speech_off_db を下回ったら「終了候補」。
3. 終了候補から min_silence_ms 以上 off を下回り続けたら無音と確定（終了は候補位置）。
4. 長さが min_speech_ms 未満の発話は破棄（咳・クリック対策 = F2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from detcut.analysis.rms import db_to_energy
from detcut.common import ceil_div


@dataclass(frozen=True)
class SpeechSegment:
    start: int  # サンプル（含む）
    end: int    # サンプル（含まない）
    peak_energy: int


@dataclass
class SpeechResult:
    window: int
    sample_rate: int
    total_samples: int
    segments: list[SpeechSegment] = field(default_factory=list)       # 採用した発話
    dropped_short: list[SpeechSegment] = field(default_factory=list)  # F2で破棄した短い発話


def detect_speech(
    energies: np.ndarray,
    window: int,
    sample_rate: int,
    total_samples: int,
    speech_on_db: float,
    speech_off_db: float,
    min_silence_ms: int,
    min_speech_ms: int,
) -> SpeechResult:
    on_thr = db_to_energy(speech_on_db, window)
    off_thr = db_to_energy(speech_off_db, window)
    win_ms_num = window * 1000  # 1窓 = window*1000/sample_rate ms
    min_sil_w = max(1, ceil_div(min_silence_ms * sample_rate, win_ms_num))
    min_speech_w = ceil_div(min_speech_ms * sample_rate, win_ms_num)

    # 判定は float64 同士の比較のみ（二乗和は 2^53 未満なので正確に表せる）
    e = energies.astype(np.float64)
    above_on = e >= on_thr
    below_off = e < off_thr

    raw: list[tuple[int, int]] = []
    n = int(e.shape[0])
    in_speech = False
    start = 0
    below_run = 0
    cand = 0
    i = 0
    while i < n:
        if not in_speech:
            # 次に on を超える窓まで飛ばす
            nz = np.flatnonzero(above_on[i:])
            if nz.size == 0:
                break
            i += int(nz[0])
            in_speech = True
            start = i
            below_run = 0
            i += 1
            continue
        if below_off[i]:
            if below_run == 0:
                cand = i
            below_run += 1
            if below_run >= min_sil_w:
                raw.append((start, cand))
                in_speech = False
                below_run = 0
        else:
            below_run = 0
        i += 1
    if in_speech:
        raw.append((start, cand if below_run > 0 else n))

    res = SpeechResult(window=window, sample_rate=sample_rate, total_samples=total_samples)
    for w0, w1 in raw:
        s0 = w0 * window
        s1 = min(w1 * window, total_samples)
        seg = SpeechSegment(start=s0, end=s1, peak_energy=int(energies[w0:w1].max()) if w1 > w0 else 0)
        if (w1 - w0) < min_speech_w:
            res.dropped_short.append(seg)
        else:
            res.segments.append(seg)
    return res
