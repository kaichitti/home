"""ゴールデンテスト用の音声を整数演算だけで作る（環境・numpyのバージョンに依存しない）。"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000
PATTERN_MS = [(600, 2400, "speech"), (3400, 5000, "speech"), (5250, 7000, "speech"),
              (9500, 9550, "blip"), (10500, 13000, "speech")]
LENGTH_MS = 14000


def _hash_noise(n: int, seed: int, amp: int) -> np.ndarray:
    i = np.arange(n, dtype=np.uint64)
    x = (i * np.uint64(0x9E3779B97F4A7C15) + np.uint64(seed)) & np.uint64(0xFFFFFFFFFFFFFFFF)
    x ^= x >> np.uint64(29)
    x = (x * np.uint64(0xBF58476D1CE4E5B9)) & np.uint64(0xFFFFFFFFFFFFFFFF)
    x ^= x >> np.uint64(32)
    return (x % np.uint64(2 * amp + 1)).astype(np.int64) - amp


def _triangle(n: int, period: int, amp: int, offset: int) -> np.ndarray:
    ph = (np.arange(n, dtype=np.int64) + offset) % period
    half = period // 2
    up = (4 * amp * ph) // period - amp
    down = amp - (4 * amp * (ph - half)) // period
    return np.where(ph < half, up, down)


def talk_pcm() -> np.ndarray:
    n = LENGTH_MS * SR // 1000
    x = _hash_noise(n, 7, 16)  # 約 -66dB の部屋ノイズ
    for a, b, kind in PATTERN_MS:
        i0, i1 = a * SR // 1000, b * SR // 1000
        m = i1 - i0
        if kind == "speech":
            env = 6 + 4 * ((np.arange(m, dtype=np.int64) // 1200) % 2)  # 25ms ごとに強弱
            sig = _triangle(m, 266, 600, i0) + _triangle(m, 133, 300, i0)
            x[i0:i1] += sig * env
        else:
            x[i0:i1] += _hash_noise(m, 11, 6000)
    return np.clip(x, -32768, 32767).astype("<i2")


def write_talk_wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(talk_pcm().tobytes())
    return path


def write_beep_wav(path: Path, ms: int, period: int = 60) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = ms * SR // 1000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(_triangle(n, period, 8000, 0).astype("<i2").tobytes())
    return path
