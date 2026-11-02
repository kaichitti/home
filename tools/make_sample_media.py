"""試用・テスト用の素材を作る（すべて決定論的に生成）。

  python tools/make_sample_media.py [出力フォルダ]
  python tools/make_sample_media.py --assets-only   （SE/BGMのサンプルだけ作る）

作るもの:
  <出力>/sample_talk.mp4   320x180・29.97fps・14秒。発話っぽい音と無音が交互に入った動画
  assets/se/*.wav          SEのサンプル（wow / whoosh / pop）
  assets/bgm/lofi01.wav    8秒のループBGM
"""

from __future__ import annotations

import math
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000
ROOT = Path(__file__).resolve().parent.parent

# (開始秒, 終了秒, 種類)  speech=発話っぽい音 / blip=短いノイズ（咳・クリック）
TALK_PATTERN = [
    (0.6, 2.4, "speech"),
    (3.4, 5.0, "speech"),
    (5.25, 7.0, "speech"),   # 直前の 0.25 秒の間は min_silence_ms 未満なので切らない
    (9.5, 9.55, "blip"),     # 50ms の短い音 → F2 で除去
    (10.5, 13.0, "speech"),
]
TALK_LENGTH = 14.0


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    y = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())


def _rng(seed: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(seed))


def talk_audio() -> np.ndarray:
    n = int(TALK_LENGTH * SR)
    t = np.arange(n) / SR
    x = _rng(1).standard_normal(n) * 0.0005  # -66dB程度の部屋ノイズ
    for a, b, kind in TALK_PATTERN:
        i0, i1 = int(a * SR), int(b * SR)
        tt = t[i0:i1] - a
        if kind == "speech":
            env = 0.55 + 0.45 * np.sin(2 * math.pi * 4.0 * tt) ** 2  # 音節っぽい揺れ
            sig = (np.sin(2 * math.pi * 180 * tt) + 0.5 * np.sin(2 * math.pi * 360 * tt)
                   + 0.25 * np.sin(2 * math.pi * 720 * tt))
            x[i0:i1] += 0.18 * env * sig
        else:
            x[i0:i1] += _rng(2).standard_normal(i1 - i0) * 0.2
    return x


def se_wow() -> np.ndarray:
    t = np.arange(int(0.6 * SR)) / SR
    f = 500 + 700 * t / 0.6
    return 0.4 * np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-3 * t)


def se_whoosh() -> np.ndarray:
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    noise = _rng(3).standard_normal(n)
    return 0.3 * noise * np.sin(math.pi * t / 0.4) ** 2


def se_pop() -> np.ndarray:
    t = np.arange(int(0.15 * SR)) / SR
    return 0.5 * np.sin(2 * math.pi * 900 * t) * np.exp(-30 * t)


def bgm_loop() -> np.ndarray:
    t = np.arange(int(8.0 * SR)) / SR
    notes = [220.0, 277.18, 329.63, 277.18]
    x = np.zeros_like(t)
    for i, f in enumerate(notes):
        m = (t >= i * 2.0) & (t < (i + 1) * 2.0)
        x[m] = 0.2 * np.sin(2 * math.pi * f * t[m]) * (0.6 + 0.4 * np.cos(2 * math.pi * 0.5 * t[m]))
    return x


def make_talk_video(out: Path, ffmpeg: str = "ffmpeg") -> Path:
    out.mkdir(parents=True, exist_ok=True)
    wav = out / "sample_talk.wav"
    write_wav(wav, talk_audio())
    mp4 = out / "sample_talk.mp4"
    cmd = [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
           f"testsrc2=size=320x180:rate=30000/1001:duration={TALK_LENGTH}",
           "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", str(mp4)]
    subprocess.run(cmd, check=True)
    return mp4


def make_assets(root: Path = ROOT) -> None:
    """サンプルのSE・BGMを作る（同名のファイルが既にあれば上書きしない）。"""
    for rel, gen in (("se/wow.wav", se_wow), ("se/whoosh.wav", se_whoosh), ("se/pop.wav", se_pop),
                     ("bgm/lofi01.wav", bgm_loop)):
        path = root / "assets" / rel
        if not path.exists():
            write_wav(path, gen())


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    make_assets()
    if "--assets-only" in sys.argv:
        print(f"SE/BGMのサンプル: {ROOT / 'assets'}")
        return 0
    out = Path(args[0]) if args else ROOT / "out" / "samples"
    mp4 = make_talk_video(out)
    print(f"作成しました: {mp4}")
    print(f"SE/BGM: {ROOT / 'assets'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
