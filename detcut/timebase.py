"""サンプル・ミリ秒・フレームの相互変換（すべて整数／有理数演算）。

時間は内部では「解析用サンプル数（既定 48kHz）」の整数で持ち、
最後にプロジェクトの fps（例: 30000/1001）で床関数・天井関数を使ってフレームにする。
浮動小数点を介さないので、環境が変わっても丸め結果が揺れない。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from detcut.common import ceil_div


@dataclass(frozen=True)
class TimeBase:
    fps: Fraction           # プロジェクトのフレームレート
    sample_rate: int = 48000  # 解析用サンプルレート

    # --- サンプル <-> フレーム
    def sample_to_frame_floor(self, s: int) -> int:
        return (s * self.fps.numerator) // (self.sample_rate * self.fps.denominator)

    def sample_to_frame_ceil(self, s: int) -> int:
        return ceil_div(s * self.fps.numerator, self.sample_rate * self.fps.denominator)

    def frame_to_sample(self, f: int) -> int:
        """フレーム f の開始時刻に当たるサンプル位置（切り上げ）。"""
        return ceil_div(f * self.fps.denominator * self.sample_rate, self.fps.numerator)

    # --- ミリ秒 <-> サンプル / フレーム
    def ms_to_samples(self, ms: int) -> int:
        return (ms * self.sample_rate) // 1000

    def samples_to_ms(self, s: int) -> int:
        return (s * 1000) // self.sample_rate

    def ms_to_frame_floor(self, ms: int) -> int:
        return (ms * self.fps.numerator) // (1000 * self.fps.denominator)

    def ms_to_frames_ceil(self, ms: int) -> int:
        """ミリ秒の長さを、それを覆うのに必要なフレーム数（切り上げ）に。"""
        return ceil_div(ms * self.fps.numerator, 1000 * self.fps.denominator)

    def ms_to_frames_round(self, ms: int) -> int:
        num = ms * self.fps.numerator
        den = 1000 * self.fps.denominator
        return (2 * num + den) // (2 * den)

    def frame_to_ms(self, f: int) -> int:
        return (f * 1000 * self.fps.denominator) // self.fps.numerator

    # --- フレーム -> 秒（有理数）
    def frame_to_seconds(self, f: int) -> Fraction:
        return Fraction(f * self.fps.denominator, self.fps.numerator)

    def seconds_to_frames_floor(self, sec: Fraction) -> int:
        v = sec * self.fps
        return v.numerator // v.denominator

    def seconds_to_frames_ceil(self, sec: Fraction) -> int:
        v = sec * self.fps
        return ceil_div(v.numerator, v.denominator)
