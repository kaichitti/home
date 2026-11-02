"""入力ファイル → 出力ファイルまでの結合テスト（ffmpeg が必要）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import DATA, ROOT, full_overrides, needs_ffmpeg
from detcut.config import load_config
from detcut.pipeline import run
from detcut.writers.exo import decode_exo_text
from detcut.writers.ini import parse_ini

import synth

GOLDEN = Path(__file__).resolve().parent / "golden"
PRESET = ROOT / "presets" / "gadget_review.yaml"


def _objects(text: str, name_key: str) -> list[str]:
    secs = parse_ini(text)
    return [s.get(name_key) for s in secs if s.name.endswith(".0") and s.name.split(".")[0].isdigit()]


@needs_ffmpeg
def test_full_run_mp4(sample_mp4, media_dir, tmp_path):
    cfg = load_config(PRESET, full_overrides(media_dir, tmp_path / "cache"))
    res = run(str(sample_mp4), cfg, out_dir=str(tmp_path / "out"), target="both")
    s = res.stats
    assert (s["keeps"], s["cuts"]) == (3, 4)
    assert s["telops"] == 5 and s["se"] == 3 and s["bgm_pieces"] >= 3
    aup2 = Path(res.files["aup2"]).read_bytes().decode("utf-8")
    kinds = _objects(aup2, "effect.name")
    assert kinds.count("動画ファイル") == 3
    assert kinds.count("テキスト") == 7          # テロップ5 + 章タイトル2
    assert kinds.count("音声ファイル") == 3 + s["bgm_pieces"]
    exo = Path(res.files["exo"]).read_bytes().decode("cp932")
    ekinds = _objects(exo, "_name")
    assert ekinds.count("動画ファイル") == 3 and ekinds.count("音声ファイル") == 3 + 3 + s["bgm_pieces"]
    texts = [decode_exo_text(x.get("text")) for x in parse_ini(exo) if x.get("_name") == "テキスト"]
    assert "こんにちは、今日はiPhoneをレビューします" in texts       # 辞書置換
    report = Path(res.files["report"]).read_bytes().decode("utf-8-sig")
    assert "えー" in report and "telop_dropped" in report
    run_json = json.loads(Path(res.files["run"]).read_text("utf-8"))
    for name, digest in run_json["outputs"].items():
        from detcut.common import sha256_file
        assert sha256_file(os.path.join(res.out_dir, name)) == digest


@needs_ffmpeg
def test_determinism_across_dirs_and_cache(sample_mp4, media_dir, tmp_path):
    cfg = load_config(PRESET, full_overrides(media_dir, tmp_path / "cache"))
    r1 = run(str(sample_mp4), cfg, out_dir=str(tmp_path / "a"), target="both", use_cache=False)
    r2 = run(str(sample_mp4), cfg, out_dir=str(tmp_path / "b"), target="both", use_cache=True)
    r3 = run(str(sample_mp4), cfg, out_dir=str(tmp_path / "c"), target="both", use_cache=True)
    names = sorted(os.listdir(r1.out_dir))
    assert names == sorted(os.listdir(r2.out_dir)) == sorted(os.listdir(r3.out_dir))
    for n in names:
        a = Path(r1.out_dir, n).read_bytes()
        assert a == Path(r2.out_dir, n).read_bytes() == Path(r3.out_dir, n).read_bytes(), n


@needs_ffmpeg
def test_golden_wav(tmp_path):
    """整数演算で作ったWAV（デコーダに依存しない）で、出力が期待ファイルとバイト単位で一致するか。"""
    media = tmp_path / "media"
    wav = synth.write_talk_wav(media / "talk.wav")
    synth.write_beep_wav(media / "se" / "wow.wav", 600)
    synth.write_beep_wav(media / "se" / "whoosh.wav", 400, 40)
    synth.write_beep_wav(media / "bgm" / "loop.wav", 5000, 109)
    overrides = full_overrides(media, tmp_path / "cache") + [
        f"se.rules.0.file={media / 'se' / 'wow.wav'}",
        f"se.rules.1.file={media / 'se' / 'whoosh.wav'}",
        f"bgm.file={media / 'bgm' / 'loop.wav'}",
        f'output.path_map=[["{media.as_posix()}/", "C:\\\\media\\\\"]]',
        "output.windows_paths=true",
    ]
    cfg = load_config(PRESET, overrides)
    res = run(str(wav), cfg, out_dir=str(tmp_path / "out"), target="both")
    produced = {
        "talk.aup2": Path(res.files["aup2"]).read_bytes(),
        "talk.exo": Path(res.files["exo"]).read_bytes(),
    }
    cut = json.loads(Path(res.files["cutlist"]).read_text("utf-8"))
    cut.pop("config_sha256")
    produced["talk.cutlist.json"] = (json.dumps(cut, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    produced["talk.report.csv"] = Path(res.files["report"]).read_bytes().replace(
        str(media).encode(), b"<MEDIA>")
    assert b"C:\\media\\talk.wav" in produced["talk.aup2"]
    if os.environ.get("DETCUT_UPDATE_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        for name, data in produced.items():
            (GOLDEN / name).write_bytes(data)
    for name, data in produced.items():
        expected = GOLDEN / name
        assert expected.exists(), f"{expected} がありません（DETCUT_UPDATE_GOLDEN=1 で作成）"
        assert data == expected.read_bytes(), f"{name} が期待ファイルと異なります"


@needs_ffmpeg
def test_audio_only_and_compress(sample_wav, tmp_path):
    cfg = load_config(ROOT / "presets" / "podcast_compress.yaml", [f"cache.dir={tmp_path / 'cache'}"])
    res = run(str(sample_wav), cfg, out_dir=str(tmp_path / "out"))
    aup2 = Path(res.files["aup2"]).read_bytes().decode("utf-8")
    kinds = _objects(aup2, "effect.name")
    assert "動画ファイル" not in kinds and kinds.count("音声ファイル") == res.stats["keeps"]
    exo = Path(res.files["exo"]).read_bytes().decode("cp932")
    assert "動画ファイルと連携=0" in exo
    assert res.stats["keeps"] >= 1


@needs_ffmpeg
def test_no_speech_is_reported(tmp_path, media_dir):
    from detcut.common import DetCutError
    silent = synth.write_beep_wav(tmp_path / "quiet.wav", 2000, 50)
    cfg = load_config(None, [f"cache.dir={tmp_path / 'cache'}", "cut.speech_on_db=-1", "cut.speech_off_db=-2"])
    with pytest.raises(DetCutError, match="残す区間がありません"):
        run(str(silent), cfg, out_dir=str(tmp_path / "out"))


def test_transcript_fixture_exists():
    assert (DATA / "sample_talk.transcript.json").exists()


@needs_ffmpeg
def test_determinism_across_processes_and_hash_seeds(sample_mp4, media_dir, tmp_path):
    """別プロセス・別の PYTHONHASHSEED でも出力が一致する（集合・辞書の順序に依存していない）。"""
    import subprocess
    import sys
    outs = []
    for seed in ("1", "12345"):
        out = tmp_path / f"o{seed}"
        args = [sys.executable, "-m", "detcut", "run", str(sample_mp4), "-p", str(PRESET), "-o", str(out),
                "-t", "both", "-q", "--no-cache"]
        for o in full_overrides(media_dir, tmp_path / f"cache{seed}"):
            args += ["--set", o]
        env = dict(os.environ, PYTHONHASHSEED=seed)
        subprocess.run(args, check=True, cwd=str(ROOT), env=env, capture_output=True)
        outs.append(out)
    for name in sorted(os.listdir(outs[0])):
        assert (outs[0] / name).read_bytes() == (outs[1] / name).read_bytes(), name
