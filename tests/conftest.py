from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

DATA = Path(__file__).resolve().parent / "data"

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg/ffprobe が必要")


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg が必要")
    import make_sample_media as m
    d = tmp_path_factory.mktemp("media")
    m.make_talk_video(d)
    m.make_assets(d)
    return d


@pytest.fixture(scope="session")
def sample_mp4(media_dir) -> Path:
    return media_dir / "sample_talk.mp4"


@pytest.fixture(scope="session")
def sample_wav(media_dir) -> Path:
    return media_dir / "sample_talk.wav"


def full_overrides(media_dir: Path, cache: Path) -> list[str]:
    """テロップ・SE・BGM・ズーム・章をすべて有効にする上書き。"""
    return [
        f"cache.dir={cache}",
        "telop.enabled=true",
        f"telop.transcript_file={DATA / 'sample_talk.transcript.json'}",
        f"telop.dictionary={ROOT / 'dict' / 'gadget_terms.tsv'}",
        f"telop.style_template={ROOT / 'templates' / 'telop_gadget.object'}",
        "se.enabled=true",
        f"se.rules.0.file={media_dir / 'assets' / 'se' / 'wow.wav'}",
        f"se.rules.1.file={media_dir / 'assets' / 'se' / 'whoosh.wav'}",
        "se.rules.1.min_cut_ms=500",
        "bgm.enabled=true",
        f"bgm.file={media_dir / 'assets' / 'bgm' / 'lofi01.wav'}",
        "zoom.enabled=true",
        "zoom.min_shot_ms=2000",
        f"chapters.file={DATA / 'sample_talk.chapters.csv'}",
        "chapters.title_telop=true",
        f"project.template_aup2={ROOT / 'templates' / 'base_1080p.aup2'}",
    ]
