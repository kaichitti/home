import re
from fractions import Fraction

from detcut.analysis.segments import SpeechResult, SpeechSegment
from detcut.asr.transcript import TSegment, Transcript, Word
from detcut.config import load_config
from detcut.edit.bgm import build_bgm
from detcut.edit.cutlist import build_cutlist
from detcut.edit.dictionary import DictRule, apply_text, load_dictionary
from detcut.edit.rules_se import build_se
from detcut.edit.snap import snap_frame
from detcut.edit.telop import build_telops, chars_from_transcript, chunk_chars, wrap_lines
from detcut.edit.zoom import plan_pieces
from detcut.timebase import TimeBase

import numpy as np

TB = TimeBase(Fraction(30))  # 1フレーム = 1600サンプル = 33.3ms
SR = 48000


def cutlist_for(speech_ms, total_ms, **cut):
    cfg = load_config(None, [f"cut.{k}={v}" for k, v in cut.items()] + ["cut.pad_before_ms=0", "cut.pad_after_ms=0"])
    segs = [SpeechSegment(a * 48, b * 48, 0) for a, b in speech_ms]
    sp = SpeechResult(window=480, sample_rate=SR, total_samples=total_ms * 48, segments=segs)
    e = np.zeros(total_ms // 10, dtype=np.int64)
    return build_cutlist(sp, e, cfg["cut"], TB), cfg


def words(*items):
    return [Word(a, b, t) for a, b, t in items]


def tcfg(**kw):
    return load_config(None, [f"telop.{k}={v}" for k, v in kw.items()])["telop"]


def test_char_distribution_integer():
    t = Transcript([TSegment(0, 1000, "abc", words((0, 1000, "abc")))])
    cs = chars_from_transcript(t)
    assert [(c.a, c.b) for c in cs] == [(0, 333), (333, 666), (666, 1000)]
    assert cs[0].ws and cs[-1].we and not cs[1].we


def test_dictionary_literal_and_regex(tmp_path):
    p = tmp_path / "d.tsv"
    p.write_text("# c\nアイフォン\tiPhone\nre:(\\d+)ギガ\t\\1GB\n", encoding="utf-8")
    rules = load_dictionary(str(p))
    assert apply_text("アイフォンは128ギガ", rules) == "iPhoneは128GB"


def test_dictionary_across_words_keeps_timing():
    cl, _ = cutlist_for([(0, 3000)], 3000, enabled="false")
    t = Transcript([TSegment(0, 2000, "アイフォンです", words((0, 600, "アイ"), (600, 1200, "フォン"), (1200, 2000, "です")))])
    rules = [DictRule(re.compile("アイフォン"), "iPhone", False, 1)]
    res = build_telops(t, cl, TB, tcfg(min_display_ms=0, snap_to_cut_frames=0, fill_gap_ms=0), rules)
    assert res.telops[0].flat == "iPhoneです"
    # 置換後の文字は元の「アイフォン」の範囲（0〜1200ms）に収まる
    assert res.telops[0].char_frames[0] == 0
    assert res.telops[0].char_frames[6] == TB.ms_to_frame_floor(1200)


def test_chunk_sentence_end_and_line_wrap():
    cfg = tcfg(max_chars_per_line=8, max_lines=2)
    text = "今日はいい天気ですね。散歩に行きましょう"
    t = Transcript([TSegment(0, 4000, text)])
    cs = chars_from_transcript(t)
    chunks = chunk_chars(cs, cfg)
    flat = ["".join(c.ch for c in ch) for ch in chunks]
    assert flat[0] == "今日はいい天気ですね"      # 文末で区切り、末尾の「。」は削除
    lines = ["".join(c.ch for c in ln) for ln in wrap_lines(chunks[0], cfg)]
    assert all(len(x) <= 8 for x in lines) and len(lines) == 2
    assert lines[0].endswith("は") or lines[0].endswith("、") or len(lines[0]) <= 8


def test_kinsoku_no_line_start():
    cfg = tcfg(max_chars_per_line=5, max_lines=2)
    t = Transcript([TSegment(0, 2000, "あいうえお、かきくけ")])
    lines = ["".join(c.ch for c in ln) for ln in wrap_lines(chars_from_transcript(t), cfg)]
    assert not any(ln.startswith("、") for ln in lines)


def test_max_chars_forces_break():
    cfg = tcfg(max_chars_per_line=5, max_lines=1)
    t = Transcript([TSegment(0, 5000, "あいうえおかきくけこさしすせそ")])
    chunks = chunk_chars(chars_from_transcript(t), cfg)
    assert all(len(c) <= 5 for c in chunks) and sum(len(c) for c in chunks) == 15


def test_words_in_cut_region_dropped_and_min_display():
    cl, _ = cutlist_for([(0, 1000), (3000, 4000)], 5000)
    t = Transcript([
        TSegment(0, 900, "はい", words((0, 900, "はい"))),
        TSegment(1500, 2000, "えー", words((1500, 2000, "えー"))),     # カット区間
        TSegment(3000, 3100, "次", words((3000, 3100, "次"))),
    ])
    res = build_telops(t, cl, TB, tcfg(min_display_ms=800, snap_to_cut_frames=0, fill_gap_ms=0), [])
    assert [x.flat for x in res.telops] == ["はい", "次"]
    assert res.dropped == [(1500, "えー")]
    second = res.telops[1]
    assert second.start == 30 and second.end - second.start + 1 >= 24  # 800ms = 24フレーム
    assert res.telops[0].end < second.start


def test_snap_to_edit_points():
    assert snap_frame(32, [0, 30, 60], 3) == 30
    assert snap_frame(34, [0, 30, 60], 3) == 34
    assert snap_frame(45, [0, 30, 60], 15) == 30  # 同距離なら早い方
    cl, _ = cutlist_for([(0, 1000), (2000, 3000)], 3000)
    t = Transcript([TSegment(2100, 2900, "テスト", words((2100, 2900, "テスト")))])
    res = build_telops(t, cl, TB, tcfg(snap_to_cut_frames=6, min_display_ms=0, fill_gap_ms=0), [])
    assert res.telops[0].start == 30           # 編集点（フレーム30）に吸着
    assert any(n.startswith("F9:start") for n in res.telops[0].notes)


def test_se_rules(tmp_path):
    se_file = tmp_path / "a.wav"
    se_file.write_bytes(b"x")
    se_b = tmp_path / "b.wav"
    se_b.write_bytes(b"x")
    cl, _ = cutlist_for([(0, 1000), (3000, 4000), (4500, 5500), (8000, 9000)], 9000)
    t = Transcript([TSegment(3000, 4000, "すごい最高", words((3000, 4000, "すごい最高")))])
    tel = build_telops(t, cl, TB, tcfg(), []).telops
    cfg = load_config(None, [
        "se.enabled=true",
        f'se.rules=[{{id: kw, type: keyword, pattern: "すごい|最高", file: "{se_file}", layer: 6, priority: 1, max_per_telop: 2}},'
        f' {{id: cut, type: after_cut, min_cut_ms: 1500, files: ["{se_b}", "{se_file}"], pick: hash, layer: 6, priority: 9}},'
        f' {{id: ch, type: chapter, file: "{se_file}", layer: 8}}]',
    ])
    warnings = []
    evs = build_se(cfg["se"], tel, cl, [5], TB, lambda p: Fraction(1, 2), warnings)
    acc = [e for e in evs if e.accepted]
    kinds = sorted({e.rule_id for e in acc})
    assert kinds == ["ch", "cut", "kw"]
    cut_frames = [e.frame for e in acc if e.rule_id == "cut"]
    assert cut_frames == [30, 90]              # 2000ms と 2500ms のカット（500ms は対象外）
    # 優先度の高い after_cut と重なる keyword は落ちる
    dropped = [e for e in evs if not e.accepted]
    assert all(e.rule_id == "kw" for e in dropped) and len(dropped) == 1
    # pick: hash は何度実行しても同じファイルを選ぶ
    evs2 = build_se(cfg["se"], tel, cl, [5], TB, lambda p: Fraction(1, 2), [])
    assert [e.file for e in evs] == [e.file for e in evs2]


def test_bgm_loop_and_ducking():
    cfg = load_config(None, ["bgm.duck_fade_ms=100", "bgm.duck_min_gap_ms=0"])["bgm"]
    pieces = build_bgm(cfg, 300, [(60, 120), (200, 240)], TB, Fraction(4))  # ループ120フレーム
    assert pieces[0].start == 0 and pieces[-1].end == 299
    assert all(a.end + 1 == b.start for a, b in zip(pieces, pieces[1:]))   # 隙間なく連続
    starts = [p.start for p in pieces]
    assert 120 in starts and 240 in starts                                # ループ境界で分割
    loop1 = next(p for p in pieces if p.start == 120)
    assert loop1.seek == 0 and loop1.loop == 1
    duck = [p for p in pieces if p.vol_start == p.vol_end == 12]
    assert duck and all(60 <= p.start and p.end < 240 for p in duck)
    fades = [p for p in pieces if p.vol_start != p.vol_end]
    assert len(fades) >= 4


def test_bgm_without_duck():
    cfg = load_config(None, ["bgm.duck=false"])["bgm"]
    pieces = build_bgm(cfg, 100, [(0, 100)], TB, None)
    assert len(pieces) == 1 and pieces[0].vol_start == 25


def test_zoom_alternation_and_split():
    cl, _ = cutlist_for([(0, 3000), (4000, 5000), (6000, 9000)], 9000)
    cfg = load_config(None, ["zoom.enabled=true", "zoom.min_shot_ms=2000"])["zoom"]
    p = plan_pieces(cl.keeps, cfg, TB)
    assert [x.level for x in p] == [0, 1, 1]     # 3秒続いた後で切替、次は1秒なので維持
    cfg2 = load_config(None, ["zoom.enabled=true", "zoom.min_shot_ms=1000", "zoom.split_long_ms=1000"])["zoom"]
    p2 = plan_pieces(cl.keeps, cfg2, TB)
    assert len(p2) == 7 and sum(x.n_frames for x in p2) == cl.total_tl_frames
    assert [x.level for x in p2][:4] == [0, 1, 0, 1]
    off = plan_pieces(cl.keeps, load_config(None)["zoom"], TB)
    assert all(x.level == 0 for x in off) and len(off) == 3
