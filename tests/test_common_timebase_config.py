from fractions import Fraction

import pytest

from detcut.common import (DetCutError, fmt_fixed, merge_intervals, parse_range_ms, parse_time_ms,
                           stable_int_hash, subtract_intervals)
from detcut.config import load_config
from detcut.timebase import TimeBase


def test_fmt_fixed_modes():
    assert fmt_fixed(Fraction(1, 3), 3) == "0.333"
    assert fmt_fixed(Fraction(2, 3), 3) == "0.667"
    assert fmt_fixed(Fraction(1, 3), 3, "ceil") == "0.334"
    assert fmt_fixed(Fraction(2, 3), 3, "floor") == "0.666"
    assert fmt_fixed(Fraction(5, 1000), 2) == "0.01"      # 0.005 → 四捨五入
    assert fmt_fixed(-1.25, 1) == "-1.3"
    assert fmt_fixed(100, 2) == "100.00"
    assert fmt_fixed(7, 0) == "7"


def test_parse_time():
    assert parse_time_ms("00:01:23.500") == 83500
    assert parse_time_ms("1:02.5") == 62500
    assert parse_time_ms("2.25") == 2250
    assert parse_time_ms(1234) == 1234
    assert parse_range_ms("00:00:01.000-00:00:02.000") == (1000, 2000)
    with pytest.raises(DetCutError):
        parse_range_ms("00:00:02.000-00:00:01.000")
    with pytest.raises(DetCutError):
        parse_time_ms("abc")


def test_intervals():
    assert merge_intervals([(10, 20), (0, 5), (5, 8), (25, 30)], gap=0) == [(0, 8), (10, 20), (25, 30)]
    assert merge_intervals([(0, 5), (8, 10)], gap=4) == [(0, 10)]
    assert merge_intervals([(0, 5), (9, 10)], gap=4) == [(0, 5), (9, 10)]
    assert subtract_intervals([(0, 100)], [(10, 20), (50, 60)]) == [(0, 10), (20, 50), (60, 100)]


def test_stable_hash_is_stable():
    assert stable_int_hash("se_wow:120") == stable_int_hash("se_wow:120")
    assert stable_int_hash("a") != stable_int_hash("b")
    # SHA-256("abc") の先頭8バイト（PYTHONHASHSEED に依存しない）
    assert stable_int_hash("abc") == 0xBA7816BF8F01CFEA


def test_timebase_ntsc_exact():
    tb = TimeBase(Fraction(30000, 1001))
    assert tb.sample_to_frame_floor(48000) == 29          # 1秒 = 29.97 フレーム
    assert tb.sample_to_frame_ceil(48000) == 30
    assert tb.frame_to_seconds(30000) == Fraction(1001)
    for f in (0, 1, 29, 30, 12345):
        assert tb.sample_to_frame_floor(tb.frame_to_sample(f)) == f
    assert tb.ms_to_frames_ceil(1000) == 30
    assert tb.frame_to_ms(30) == 1001


def test_config_defaults_and_hash(tmp_path):
    c1 = load_config(None)
    c2 = load_config(None, [f"output.dir={tmp_path}", f"cache.dir={tmp_path}"])
    assert c1.sha256 == c2.sha256  # 出力先・キャッシュはハッシュに含めない
    c3 = load_config(None, ["cut.speech_on_db=-30"])
    assert c3.sha256 != c1.sha256
    # 1.0 と 1 の表記ゆれでハッシュが変わらない
    assert load_config(None, ["cut.speech_on_db=-38.0"]).sha256 == load_config(None, ["cut.speech_on_db=-38"]).sha256


def test_config_validation_errors(tmp_path):
    with pytest.raises(DetCutError, match="Additional properties"):
        load_config(None, ["cut.unknown_key=1"])
    with pytest.raises(DetCutError, match="speech_on_db"):
        load_config(None, ["cut.speech_on_db=-50", "cut.speech_off_db=-40"])
    p = tmp_path / "p.yaml"
    p.write_text("version: 1\ntelop:\n  style:\n    color: 000000\n", encoding="utf-8")
    with pytest.raises(DetCutError, match="引用符"):
        load_config(p)


def test_config_paths_relative_to_base_dir(tmp_path):
    (tmp_path / "presets").mkdir()
    p = tmp_path / "presets" / "a.yaml"
    p.write_text('version: 1\npaths: {base_dir: ".."}\nbgm: {file: "assets/x.wav"}\n'
                 'se:\n  rules:\n    - {id: r1, type: after_cut, file: "se/a.wav"}\n', encoding="utf-8")
    cfg = load_config(p, ["se.rules.0.layer=8"])
    assert cfg["bgm"]["file"] == str(tmp_path / "assets" / "x.wav")
    assert cfg["se"]["rules"][0]["file"] == str(tmp_path / "se" / "a.wav")
    assert cfg["se"]["rules"][0]["layer"] == 8
    assert cfg["se"]["rules"][0]["pick"] == "first"  # 既定値の補完
    with pytest.raises(DetCutError, match="範囲外"):
        load_config(p, ["se.rules.5.layer=8"])


def test_bundled_presets_load():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for p in sorted((root / "presets").glob("*.yaml")):
        cfg = load_config(p)
        assert cfg.sha256
