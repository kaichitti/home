"""FFmpeg で PCM を取り出し、窓ごとのエネルギー（二乗和）を整数で求める。

抽出パラメータは固定（モノラル・48kHz・符号付き16bit）。
二乗和は int64 の整数演算なので、CPU や numpy のSIMD実装に左右されず完全に再現する。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from detcut.common import DetCutError

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

PCM_ARGS_VERSION = 1  # 抽出コマンドを変えたら上げる（キャッシュ無効化用）


def pcm_command(ffmpeg: str, path: str, sample_rate: int, fmt: str = "s16le") -> list[str]:
    codec = {"s16le": "pcm_s16le", "f32le": "pcm_f32le"}[fmt]
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-v", "error",
        "-i", path,
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-ac", "1", "-ar", str(sample_rate),
        "-c:a", codec, "-f", fmt, "-",
    ]


@dataclass
class EnergyData:
    sample_rate: int
    window: int                 # 窓長（サンプル）= ホップ長
    energies: np.ndarray        # int64: 各窓の二乗和（最後の窓は窓長に換算済み）
    total_samples: int
    pcm_sha256: str

    @property
    def n_windows(self) -> int:
        return int(self.energies.shape[0])


def extract_energies(
    ffmpeg: str,
    path: str,
    sample_rate: int = 48000,
    window_ms: int = 10,
    progress: Callable[[float], None] | None = None,
    expected_samples: int | None = None,
) -> EnergyData:
    window = sample_rate * window_ms // 1000
    cmd = pcm_command(ffmpeg, path, sample_rate)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except FileNotFoundError as e:
        raise DetCutError(f"ffmpeg が見つかりません: {ffmpeg}") from e

    err_chunks: list[bytes] = []
    assert proc.stderr is not None
    drain = threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True)
    drain.start()

    h = hashlib.sha256()
    chunks: list[np.ndarray] = []
    pending = b""
    total = 0
    block = window * 2 * 2000  # 20秒分ずつ
    assert proc.stdout is not None
    while True:
        buf = proc.stdout.read(block)
        if not buf:
            break
        h.update(buf)
        buf = pending + buf
        usable = (len(buf) // (window * 2)) * window * 2
        pending = buf[usable:]
        if usable:
            x = np.frombuffer(buf[:usable], dtype="<i2").astype(np.int64)
            total += x.shape[0]
            chunks.append((x * x).reshape(-1, window).sum(axis=1))
        if progress and expected_samples:
            progress(min(1.0, total / expected_samples))
    rc = proc.wait()
    drain.join()
    stderr = b"".join(err_chunks).decode("utf-8", "replace")
    if rc != 0:
        raise DetCutError(f"ffmpeg で音声を取り出せませんでした（音声トラックがない可能性）:\n{stderr.strip()}")
    if len(pending) % 2:
        pending = pending[:-1]
    if pending:
        x = np.frombuffer(pending, dtype="<i2").astype(np.int64)
        n = x.shape[0]
        total += n
        # 端数の窓は窓長に換算（整数演算）
        chunks.append(np.array([int((x * x).sum()) * window // n], dtype=np.int64))
    energies = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int64)
    if total == 0:
        raise DetCutError("音声が空です（音声トラックがない、または長さ0）")
    return EnergyData(sample_rate=sample_rate, window=window, energies=energies,
                      total_samples=total, pcm_sha256=h.hexdigest())


def extract_float_pcm(ffmpeg: str, path: str, sample_rate: int = 16000) -> np.ndarray:
    """文字起こし用の float32 PCM（16kHz モノラル）。"""
    cmd = pcm_command(ffmpeg, path, sample_rate, fmt="f32le")
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except FileNotFoundError as e:
        raise DetCutError(f"ffmpeg が見つかりません: {ffmpeg}") from e
    if p.returncode != 0:
        raise DetCutError("ffmpeg で文字起こし用の音声を取り出せませんでした:\n"
                          + p.stderr.decode("utf-8", "replace").strip())
    data = p.stdout[: len(p.stdout) // 4 * 4]
    return np.frombuffer(data, dtype="<f4").copy()
