"""ffprobe / ffmpeg の呼び出し（メディア情報・バージョン）。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from detcut.common import DetCutError, sha256_text

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


def run_capture(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as e:
        raise DetCutError(
            f"{cmd[0]} が見つかりません。FFmpeg をインストールしてPATHを通すか、"
            f"プリセットの ffmpeg.ffmpeg / ffmpeg.ffprobe にフルパスを指定してください。"
        ) from e


@dataclass(frozen=True)
class FfmpegInfo:
    version_line: str
    version_sha256: str


def ffmpeg_info(ffmpeg: str) -> FfmpegInfo:
    if shutil.which(ffmpeg) is None and not _exists(ffmpeg):
        raise DetCutError(f"ffmpeg が見つかりません: {ffmpeg}")
    p = run_capture([ffmpeg, "-hide_banner", "-version"])
    out = p.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    if p.returncode != 0 or not out:
        raise DetCutError(f"ffmpeg -version に失敗しました: {ffmpeg}")
    return FfmpegInfo(version_line=out.splitlines()[0].strip(), version_sha256=sha256_text(out))


def _exists(path: str) -> bool:
    import os
    return os.path.isfile(path)


def _frac(v: Any) -> Fraction | None:
    if v in (None, "", "N/A", "0/0"):
        return None
    try:
        s = str(v)
        if "/" in s:
            a, b = s.split("/", 1)
            if int(b) == 0:
                return None
            return Fraction(int(a), int(b))
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None


@dataclass
class MediaInfo:
    path: str
    has_video: bool
    has_audio: bool
    width: int | None = None
    height: int | None = None
    fps: Fraction | None = None          # r_frame_rate
    avg_fps: Fraction | None = None
    duration: Fraction | None = None     # 秒
    video_duration: Fraction | None = None
    audio_duration: Fraction | None = None
    audio_rate: int | None = None
    audio_channels: int | None = None
    vfr_suspect: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "has_video": self.has_video,
            "has_audio": self.has_audio,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "avg_fps": self.avg_fps,
            "duration": self.duration,
            "video_duration": self.video_duration,
            "audio_duration": self.audio_duration,
            "audio_rate": self.audio_rate,
            "audio_channels": self.audio_channels,
            "vfr_suspect": self.vfr_suspect,
        }


def probe(path: str, ffprobe: str = "ffprobe") -> MediaInfo:
    p = run_capture([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if p.returncode != 0:
        msg = p.stderr.decode("utf-8", "replace").strip()
        raise DetCutError(f"ffprobe でファイルを読めません: {path}\n{msg}")
    data = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    info = MediaInfo(path=path, has_video=v is not None, has_audio=a is not None, raw=data)
    info.duration = _frac(fmt.get("duration"))
    if v is not None:
        info.width = int(v.get("width") or 0) or None
        info.height = int(v.get("height") or 0) or None
        info.fps = _frac(v.get("r_frame_rate"))
        info.avg_fps = _frac(v.get("avg_frame_rate"))
        info.video_duration = _frac(v.get("duration")) or info.duration
        if info.fps and info.avg_fps:
            diff = abs(info.fps - info.avg_fps) / info.fps
            info.vfr_suspect = diff > Fraction(5, 1000)
    if a is not None:
        info.audio_rate = int(a.get("sample_rate") or 0) or None
        info.audio_channels = int(a.get("channels") or 0) or None
        info.audio_duration = _frac(a.get("duration")) or info.duration
    return info


def media_duration(path: str, ffprobe: str = "ffprobe") -> Fraction | None:
    """SE・BGMの長さ（秒）。読めなければ None。"""
    try:
        info = probe(path, ffprobe)
    except DetCutError:
        return None
    return info.audio_duration or info.duration
