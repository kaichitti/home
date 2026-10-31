from fractions import Fraction

import numpy as np

from detcut.analysis.rms import db_to_energy, energy_to_db
from detcut.analysis.segments import detect_speech
from detcut.analysis.suggest import suggest
from detcut.config import load_config
from detcut.edit.cutlist import build_cutlist
from detcut.timebase import TimeBase

SR = 48000
W = 480


def energies_from_pattern(pattern):
    """[(ms, dB), ...] から10ms窓のエネルギー列を作る。"""
    out = []
    for ms, db in pattern:
        e = int(db_to_energy(db, W)) if db > -120 else 0
        out += [e] * (ms // 10)
    return np.array(out, dtype=np.int64)


def run(pattern, **cut):
    cfg = load_config(None, [f"cut.{k}={v}" for k, v in cut.items()])
    e = energies_from_pattern(pattern)
    total = len(e) * W
    sp = detect_speech(e, W, SR, total, cfg["cut"]["speech_on_db"], cfg["cut"]["speech_off_db"],
                       cfg["cut"]["min_silence_ms"], cfg["cut"]["min_speech_ms"])
    tb = TimeBase(Fraction(30000, 1001))
    return sp, build_cutlist(sp, e, cfg["cut"], tb)


def test_db_roundtrip():
    for db in (-60.0, -45.0, -20.0, -3.0):
        assert abs(energy_to_db(int(db_to_energy(db, W)), W) - db) < 0.01
    assert energy_to_db(0, W) == -120.0


def test_hysteresis_and_min_silence():
    # 発話1秒 → 200ms の間（min_silence 350ms 未満なので切らない）→ 発話1秒
    sp, _ = run([(500, -70), (1000, -20), (200, -70), (1000, -20), (500, -70)])
    assert [(s.start // W, s.end // W) for s in sp.segments] == [(50, 270)]
    # -42dB は on(-38) 未満なので発話開始にならないが、発話中なら off(-45) 以上で継続扱い
    sp, _ = run([(500, -70), (1000, -20), (600, -42), (1000, -20), (500, -70)])
    assert len(sp.segments) == 1
    sp, _ = run([(500, -70), (600, -42), (500, -70)])
    assert sp.segments == []


def test_short_speech_dropped_f2():
    sp, cl = run([(500, -70), (1000, -20), (1000, -70), (50, -10), (1000, -70), (1000, -20), (300, -70)])
    assert len(sp.segments) == 2
    assert len(sp.dropped_short) == 1
    middle = [c for c in cl.cuts if c.rule == "F2"]
    assert len(middle) == 1 and "short_speech" in middle[0].reason


def test_padding_merge_and_frames():
    sp, cl = run([(1000, -70), (1000, -20), (300, -70), (1000, -20), (1000, -70)], min_silence_ms=200,
                 pad_before_ms=100, pad_after_ms=100, merge_gap_ms=150)
    # 間300ms - 余白200ms = 100ms < merge_gap 150ms → 1区間に結合
    assert len(cl.keeps) == 1
    k = cl.keeps[0]
    tb = cl.tb
    assert k.src_start_frame == tb.sample_to_frame_floor(900 * 48)
    assert k.src_end_frame == tb.sample_to_frame_ceil(3400 * 48)
    assert k.tl_start_frame == 0
    assert cl.total_tl_frames == k.n_frames
    # 先頭と末尾の無音はカット
    assert [c.rule for c in cl.cuts] == ["F1", "F1"]
    assert "leading" in cl.cuts[0].reason and "trailing" in cl.cuts[1].reason


def test_compress_mode_f3():
    pat = [(500, -70), (1000, -20), (2000, -70), (1000, -20), (500, -70)]
    _, jet = run(pat)
    _, comp = run(pat, mode="compress", compress_to_ms=400)
    gap_jet = jet.keeps[1].src_start_frame - jet.keeps[0].src_end_frame
    gap_comp = comp.keeps[1].src_start_frame - comp.keeps[0].src_end_frame
    assert gap_comp < gap_jet
    assert comp.total_tl_frames - jet.total_tl_frames in (11, 12, 13)  # 400ms ≒ 12フレーム
    assert any(c.rule == "F3" for c in comp.cuts)


def test_manual_keep_and_force_cut():
    pat = [(1000, -70), (2000, -20), (1000, -70)]
    _, cl = run(pat, force_cut_ranges='["00:00:01.500-00:00:02.000"]')
    assert len(cl.keeps) == 2
    assert any(c.rule == "manual" for c in cl.cuts)
    _, cl = run([(3000, -70)], keep_ranges='["00:00:01.000-00:00:02.000"]')
    assert len(cl.keeps) == 1 and cl.keeps[0].rule == "manual"


def test_mapping_helpers():
    _, cl = run([(500, -70), (1000, -20), (1000, -70), (1000, -20), (500, -70)])
    k0, k1 = cl.keeps
    assert cl.src_frame_to_tl(k0.src_start_frame) == 0
    assert cl.src_frame_to_tl(k1.src_start_frame) == k0.n_frames
    assert cl.src_frame_to_tl(k0.src_end_frame + 2) is None
    assert cl.src_frame_to_tl_or_next(k0.src_end_frame + 2) == k1.tl_start_frame
    assert cl.edit_points == [k1.tl_start_frame]
    ivs = cl.src_frames_to_tl_intervals(k0.src_end_frame - 3, k1.src_start_frame + 3)
    assert ivs == [(k0.n_frames - 3, k0.n_frames), (k0.n_frames, k0.n_frames + 3)]


def test_cut_disabled_keeps_everything():
    _, cl = run([(1000, -70), (1000, -20)], enabled="false")
    assert len(cl.keeps) == 1 and cl.cuts == []


def test_suggest_is_deterministic():
    e = energies_from_pattern([(3000, -66), (3000, -20), (1000, -66)])
    a, b = suggest(e, W), suggest(e, W)
    assert (a.speech_on_db, a.speech_off_db) == (b.speech_on_db, b.speech_off_db)
    assert a.speech_off_db > -66 and a.speech_on_db >= a.speech_off_db and a.speech_on_db < -20
