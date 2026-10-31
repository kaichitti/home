from __future__ import annotations

import sys
import types

import pytest

from conftest import DATA, ROOT, needs_ffmpeg
from detcut.asr.transcript import load_transcript, parse_srt, to_srt
from detcut.cli import main
from detcut.common import DetCutError, sha256_bytes
from detcut.config import load_config
from detcut.gui.controller import preview_geometry, state_from_config, PreviewData
from detcut.shortcuts import build_shortcut, find_shortcut, merge_exo
from detcut.writers.exo import decode_exo_text, exo_text_hex
from detcut.writers.ini import parse_ini

PRESET = ROOT / "presets" / "gadget_review.yaml"


# ---------------------------------------------------------------- transcript

def test_srt_roundtrip(tmp_path):
    srt = "1\n00:00:01,000 --> 00:00:02,500\nこんにちは\n\n2\n00:00:03,000 --> 00:00:04,000\n二行\n目\n"
    t = parse_srt(srt)
    assert [(s.start_ms, s.end_ms, s.text) for s in t.segments] == [(1000, 2500, "こんにちは"), (3000, 4000, "二行\n目")]
    p = tmp_path / "a.srt"
    p.write_text(to_srt(t), encoding="utf-8")
    assert [s.text for s in load_transcript(str(p)).segments] == ["こんにちは", "二行\n目"]


def test_transcript_json_fixture():
    t = load_transcript(str(DATA / "sample_talk.transcript.json"))
    assert len(t.segments) == 5 and t.segments[0].words[0].text == "こんにちは、"


# ---------------------------------------------------------------- whisper stage (fake module)

class _W:
    def __init__(self, s, e, w):
        self.start, self.end, self.word = s, e, w


class _S:
    def __init__(self, s, e, text, words):
        self.start, self.end, self.text, self.words = s, e, text, words


class FakeModel:
    init_args: list = []
    calls: list = []

    def __init__(self, path, **kw):
        FakeModel.init_args.append((path, kw))

    def transcribe(self, audio, **kw):
        FakeModel.calls.append(kw)
        segs = [_S(0.6, 2.4, "テスト", [_W(0.6, 1.5, "テ"), _W(1.5, 2.4, "スト")])]
        return iter(segs), types.SimpleNamespace(language="ja")


@pytest.fixture
def fake_whisper(monkeypatch, tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"weights")
    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = FakeModel
    utils = types.ModuleType("faster_whisper.utils")
    utils.download_model = lambda name: str(model_dir)
    fw.utils = utils
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    FakeModel.init_args.clear()
    FakeModel.calls.clear()
    return model_dir


@needs_ffmpeg
def test_whisper_stage_settings_and_cache(fake_whisper, sample_wav, tmp_path):
    from detcut.asr.whisper_stage import transcribe_cached
    asr = load_config(None)["telop"]["asr"]
    t1, info1 = transcribe_cached(str(sample_wav), "pcmhash", asr, str(tmp_path / "c"), "ffmpeg", lambda m: None)
    kw = FakeModel.calls[0]
    assert kw["temperature"] == 0.0 and isinstance(kw["temperature"], float)  # 温度フォールバックなし
    assert kw["word_timestamps"] is True and kw["beam_size"] == 5 and kw["language"] == "ja"
    assert FakeModel.init_args[0][1] == {"device": "cpu", "compute_type": "int8", "cpu_threads": 4, "num_workers": 1}
    assert [(w.start_ms, w.text) for w in t1.segments[0].words] == [(600, "テ"), (1500, "スト")]
    assert t1.meta["model_sha256"] == sha256_bytes(b"weights")
    # 2回目はキャッシュを使い、モデルを呼ばない。結果も同じ
    t2, info2 = transcribe_cached(str(sample_wav), "pcmhash", asr, str(tmp_path / "c"), "ffmpeg", lambda m: None)
    assert len(FakeModel.calls) == 1
    assert t1.dumps() == t2.dumps() and info1 == info2
    # 設定が変わればキャッシュは別
    asr2 = dict(asr, beam_size=3)
    transcribe_cached(str(sample_wav), "pcmhash", asr2, str(tmp_path / "c"), "ffmpeg", lambda m: None)
    assert len(FakeModel.calls) == 2


@needs_ffmpeg
def test_whisper_model_hash_mismatch(fake_whisper, sample_wav, tmp_path):
    from detcut.asr.whisper_stage import transcribe_cached
    asr = dict(load_config(None)["telop"]["asr"], model_sha256="0" * 64)
    with pytest.raises(DetCutError, match="ハッシュ"):
        transcribe_cached(str(sample_wav), "x", asr, None, "ffmpeg", lambda m: None)


def test_whisper_missing_gives_hint(monkeypatch):
    from detcut.asr.whisper_stage import run_whisper
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(DetCutError, match="faster-whisper"):
        run_whisper("x.wav", load_config(None)["telop"]["asr"], "ffmpeg", lambda m: None)


# ---------------------------------------------------------------- shortcuts

def test_shortcut_files(tmp_path):
    cfg = load_config(PRESET, [f"shortcuts.0.items.1.file={tmp_path / 'missing.wav'}"])
    with pytest.raises(DetCutError, match="見つかりません"):
        build_shortcut(find_shortcut(cfg, "wow"), cfg)
    se = tmp_path / "se.wav"
    import synth
    synth.write_beep_wav(se, 500)
    cfg = load_config(PRESET, [f"shortcuts.0.items.1.file={se}"])
    files = build_shortcut(find_shortcut(cfg, "wow"), cfg)
    assert sorted(files) == ["wow.exo", "wow_01.object", "wow_02.object"]
    obj = parse_ini(files["wow_01.object"].decode("utf-8"))
    assert obj[0].name == "Object" and obj[1].get("effect.name") == "テキスト" and obj[1].get("テキスト") == "すごい！"
    exo = parse_ini(files["wow.exo"].decode("cp932"))
    assert decode_exo_text(next(s for s in exo if s.get("_name") == "テキスト").get("text")) == "すごい！"
    with pytest.raises(DetCutError):
        find_shortcut(cfg, "nope")


def test_merge_exo_shifts_layers():
    base = parse_ini("[exedit]\nlength=10\n[0]\nstart=1\nend=10\nlayer=1\n[0.0]\n_name=テキスト\n")
    extra = parse_ini("[exedit]\n[0]\nstart=1\nend=5\nlayer=2\n[0.0]\n_name=図形\n[1]\nstart=3\nend=4\nlayer=3\n")
    out = merge_exo(base, extra, layer_offset=2, frame_offset=5)
    d = {s.name: s for s in out}
    assert d["1"].get("layer") == "4" and d["1"].get("start") == "6" and d["1.0"].get("_name") == "図形"
    assert d["2"].get("layer") == "5" and d["2"].get("end") == "9"


# ---------------------------------------------------------------- gui controller (no Tk)

def test_ui_state_overrides():
    cfg = load_config(PRESET)
    st = state_from_config(cfg)
    assert st.overrides(cfg) == []
    st.cut["speech_on_db"] = -41.0
    st.flags["bgm.enabled"] = True
    st.mode = "compress"
    assert st.overrides(cfg) == ["cut.mode=compress", "cut.speech_on_db=-41", "bgm.enabled=true"]
    cfg2 = load_config(PRESET, st.overrides(cfg))
    assert cfg2["cut"]["speech_on_db"] == -41 and cfg2["bgm"]["enabled"] is True


def test_preview_geometry():
    p = PreviewData(envelope=[-90.0, 0.0, -45.0], duration_ms=1000, keeps_ms=[(250, 500)], on_db=-30, off_db=-60,
                    stats="")
    g = preview_geometry(p, 101, 90)
    assert g["line"] == [0.0, 90.0, 50.0, 0.0, 100.0, 45.0]
    assert g["keeps"] == [(25.25, 50.5)]
    assert g["on_y"] == 30.0 and g["off_y"] == 60.0


@needs_ffmpeg
def test_controller_analyze(sample_mp4, tmp_path):
    from detcut.gui.controller import Controller
    st = state_from_config(load_config(PRESET), str(sample_mp4))
    st.output_dir = str(tmp_path)
    c = Controller(log=lambda m: None)
    p = c.analyze(st)
    assert len(p.keeps_ms) == 3 and len(p.envelope) == 1200 and p.suggestion is not None


# ---------------------------------------------------------------- CLI

@needs_ffmpeg
def test_cli_run_verify_analyze(sample_mp4, tmp_path, capsys):
    cache = f"cache.dir={tmp_path / 'cache'}"
    assert main(["run", str(sample_mp4), "-p", str(PRESET), "-o", str(tmp_path / "o"), "-t", "both", "-q",
                 "--set", cache]) == 0
    out = capsys.readouterr().out
    assert "3区間を残し4区間をカット" in out
    assert (tmp_path / "o" / "sample_talk.aup2").exists() and (tmp_path / "o" / "sample_talk.exo").exists()
    assert main(["verify", str(sample_mp4), "-p", str(PRESET), "--set", cache]) == 0
    assert "OK" in capsys.readouterr().out
    assert main(["analyze", str(sample_mp4), "--set", cache]) == 0
    assert "提案:" in capsys.readouterr().out


def test_cli_errors_and_misc(tmp_path, capsys):
    assert main(["run", str(tmp_path / "none.mp4"), "-q"]) == 1
    assert "見つかりません" in capsys.readouterr().err
    assert main(["run", "x.mp4", "-p", str(tmp_path / "nope.yaml")]) == 1
    assert main(["shortcut", "--list", "-p", str(PRESET)]) == 0
    assert "wow" in capsys.readouterr().out
    assert main(["harvest", str(ROOT / "templates" / "telop_gadget.object")]) == 0
    out = capsys.readouterr().out
    assert "テキスト" in out and "object_samples_aup2" in out
    assert main(["presets"]) == 0
    assert "gadget_review.yaml" in capsys.readouterr().out


def test_exo_hex_length():
    assert len(exo_text_hex("あ" * 3000)) == 4096
