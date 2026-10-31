"""自動テロップ（F7）＋辞書置換（F8）＋編集点吸着（F9）。

文字起こしの単語タイムスタンプを「1文字ずつの時刻」に展開し（単語内は整数で等分）、
  1. 辞書置換（置換後の文字は元の範囲の時刻を引き継ぐ）
  2. カット後のタイムラインへ写像（カットで分断された文字は、残りの長い側に寄せる。
     完全にカットされた文字は捨ててレポートに記録）
  3. 区切り（文末・セグメント境界・間の長さ・最大文字数）でテロップ単位にまとめる
  4. 句読点・助詞の後を優先して改行（禁則つき）
  5. 最小表示時間・隙間埋め・編集点への吸着
を、すべて固定ルールで行う。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from detcut.asr.transcript import Transcript
from detcut.edit.cutlist import CutList
from detcut.edit.dictionary import DictRule
from detcut.edit.snap import boundary_points, snap_frame
from detcut.timebase import TimeBase


@dataclass(frozen=True)
class Char:
    ch: str
    a: int          # 元素材上の開始（ms）
    b: int          # 元素材上の終了（ms）
    seg: int        # 文字起こしセグメント番号
    ws: bool        # 単語の先頭
    we: bool        # 単語の末尾
    ta: int = -1    # タイムライン上の開始フレーム
    tb: int = -1    # タイムライン上の終了フレーム（含まない）


@dataclass
class Telop:
    index: int
    start: int                 # タイムライン上の開始フレーム
    end: int                   # 終端フレーム（含む）
    text: str                  # 改行込み
    flat: str                  # 改行なし（SEのキーワード判定用）
    char_frames: tuple[int, ...]
    src_start_ms: int
    src_end_ms: int
    notes: list[str] = field(default_factory=list)


@dataclass
class TelopResult:
    telops: list[Telop] = field(default_factory=list)
    dropped: list[tuple[int, str]] = field(default_factory=list)  # (ms, 文字列) 完全にカットされた部分


# ---------------------------------------------------------------- char stream

def chars_from_transcript(t: Transcript) -> list[Char]:
    out: list[Char] = []
    for si, seg in enumerate(t.segments):
        if seg.words:
            units = [(w.start_ms, w.end_ms, w.text, False) for w in seg.words]
        else:
            units = [(seg.start_ms, seg.end_ms, seg.text, True)]
        for a, b, text, per_char in units:
            text = text.replace("\r", "").replace("\n", " ")
            k = len(text)
            if k == 0:
                continue
            b = max(a, b)
            for i, ch in enumerate(text):
                ca = a + (b - a) * i // k
                cb = a + (b - a) * (i + 1) // k
                out.append(Char(ch, ca, max(ca, cb), si, per_char or i == 0, per_char or i == k - 1))
    return out


def apply_dictionary_chars(chars: list[Char], rules: list[DictRule]) -> list[Char]:
    if not rules:
        return chars
    # セグメントごとに置換（セグメントをまたぐ置換はしない）
    out: list[Char] = []
    i = 0
    while i < len(chars):
        j = i
        while j < len(chars) and chars[j].seg == chars[i].seg:
            j += 1
        out.extend(_apply_rules(chars[i:j], rules))
        i = j
    return out


def _apply_rules(chars: list[Char], rules: list[DictRule]) -> list[Char]:
    for r in rules:
        text = "".join(c.ch for c in chars)
        new: list[Char] = []
        pos = 0
        changed = False
        for m in r.pattern.finditer(text):
            if m.end() <= m.start():
                continue
            changed = True
            new.extend(chars[pos:m.start()])
            repl = m.expand(r.replacement) if r.is_regex else r.replacement
            span = chars[m.start():m.end()]
            a, b, k = span[0].a, span[-1].b, len(repl)
            for n, ch in enumerate(repl):
                new.append(Char(ch, a + (b - a) * n // k, a + (b - a) * (n + 1) // k, span[0].seg,
                                span[0].ws if n == 0 else False, span[-1].we if n == k - 1 else False))
            pos = m.end()
        if changed:
            new.extend(chars[pos:])
            chars = new
    return chars


def map_chars(chars: list[Char], cl: CutList, tb: TimeBase) -> tuple[list[Char], list[tuple[int, str]]]:
    kept: list[Char] = []
    dropped: list[tuple[int, str]] = []
    run: list[Char] = []

    def flush_drop():
        if run:
            txt = "".join(c.ch for c in run).strip()
            if txt:
                dropped.append((run[0].a, txt))
            run.clear()

    for c in chars:
        fa = tb.ms_to_frame_floor(c.a)
        fb = max(fa + 1, tb.ms_to_frames_ceil(c.b))
        ivs = cl.src_frames_to_tl_intervals(fa, fb)
        if not ivs:
            run.append(c)
            continue
        flush_drop()
        best = max(ivs, key=lambda iv: (iv[1] - iv[0], -iv[0]))
        kept.append(replace(c, ta=best[0], tb=best[1]))
    flush_drop()
    return kept, dropped


# ---------------------------------------------------------------- breaking

class _Rules:
    def __init__(self, cfg: dict[str, Any]):
        self.cpl = int(cfg["max_chars_per_line"])
        self.lines = int(cfg["max_lines"])
        self.break_after = set(cfg["break_after"])
        self.sentence_end = set(cfg["sentence_end"])
        self.no_start = set(cfg["no_line_start"])
        self.no_end = set(cfg["no_line_end"])
        self.particles = sorted(cfg["particles"], key=lambda p: (-len(p), p))
        self.strip_trailing = set(cfg["strip_trailing"])

    def score(self, seq: list[Char], j: int) -> int | None:
        """seq[j-1] と seq[j] の間で区切るときの良さ（大きいほど良い。None は禁則）。"""
        left, right = seq[j - 1], seq[j]
        if right.ch in self.no_start or left.ch in self.no_end:
            return None
        if left.ch in self.break_after:
            return 4
        if left.ch.isspace() or right.ch.isspace():
            return 3
        if left.we:
            tail = "".join(c.ch for c in seq[max(0, j - 4):j])
            if any(tail.endswith(p) for p in self.particles):
                return 2
            return 1
        return 0


def _strip(seq: list[Char]) -> list[Char]:
    a, b = 0, len(seq)
    while a < b and seq[a].ch.isspace():
        a += 1
    while b > a and seq[b - 1].ch.isspace():
        b -= 1
    return seq[a:b]


def chunk_chars(chars: list[Char], cfg: dict[str, Any]) -> list[list[Char]]:
    R = _Rules(cfg)
    limit = R.cpl * R.lines
    gap = int(cfg["gap_break_ms"])
    chunks: list[list[Char]] = []
    cur: list[Char] = []
    for c in chars:
        if cur:
            prev = cur[-1]
            hard = (
                (cfg["break_on_segment"] and c.seg != prev.seg)
                or (c.a - prev.b >= gap)
                or (prev.ch in R.sentence_end and c.ch not in R.sentence_end and c.ch not in R.no_start)
            )
            if hard:
                chunks.append(cur)
                cur = []
        if len(_strip(cur)) >= limit:
            seq = cur + [c]
            best: tuple[int, int] | None = None
            for j in range(max(1, len(cur) // 3), len(cur) + 1):
                s = R.score(seq, j)
                if s is None:
                    continue
                if best is None or s >= best[0]:
                    best = (s, j)
            if best is None and c.ch in R.no_start:
                # 行頭禁則の文字はぶら下げて今のテロップに含める
                cur.append(c)
                chunks.append(cur)
                cur = []
                continue
            j = best[1] if best else len(cur)
            chunks.append(cur[:j])
            cur = cur[j:]
        cur.append(c)
    if cur:
        chunks.append(cur)
    out = []
    for ch in chunks:
        ch = _strip(ch)
        while ch and ch[-1].ch in R.strip_trailing:
            ch = _strip(ch[:-1])
        if ch:
            out.append(ch)
    return out


def wrap_lines(seq: list[Char], cfg: dict[str, Any]) -> list[list[Char]]:
    R = _Rules(cfg)
    out: list[list[Char]] = []
    rest = _strip(seq)
    while len(rest) > R.cpl and len(out) < R.lines - 1:
        r = R.lines - len(out)
        lo = max(1, len(rest) - R.cpl * (r - 1))
        hi = min(R.cpl, len(rest) - 1)
        best: tuple[tuple[int, int, int], int] | None = None
        for j in range(lo, hi + 1):
            s = R.score(rest, j)
            if s is None:
                continue
            key = (s, -abs(j * r - len(rest)), j)
            if best is None or key > best[0]:
                best = (key, j)
        if best is None:
            # 範囲内に禁則を守れる位置がない → ぶら下げ（句読点などを前の行に最大2文字はみ出させる）
            # それでもだめなら範囲より前で区切る
            for jj in list(range(hi + 1, min(len(rest) - 1, hi + 2) + 1)) + list(range(lo - 1, 0, -1)):
                if R.score(rest, jj) is not None:
                    best = ((0, 0, 0), jj)
                    break
        j = best[1] if best else hi
        out.append(_strip(rest[:j]))
        rest = _strip(rest[j:])
    out.append(rest)
    return [ln for ln in out if ln]


# ---------------------------------------------------------------- timing

def build_telops(
    transcript: Transcript,
    cl: CutList,
    tb: TimeBase,
    cfg: dict[str, Any],
    rules: list[DictRule],
) -> TelopResult:
    chars = apply_dictionary_chars(chars_from_transcript(transcript), rules)
    kept, dropped = map_chars(chars, cl, tb)
    res = TelopResult(dropped=dropped)
    total = cl.total_tl_frames
    if total <= 0:
        return res
    min_frames = max(1, tb.ms_to_frames_ceil(int(cfg["min_display_ms"])))
    fill = tb.ms_to_frames_round(int(cfg["fill_gap_ms"]))

    items: list[Telop] = []
    for chunk in chunk_chars(kept, cfg):
        lines = wrap_lines(chunk, cfg)
        flat_chars = [c for ln in lines for c in ln]
        start = chunk[0].ta
        end = max(start, chunk[-1].tb - 1)
        items.append(Telop(
            index=len(items), start=start, end=end,
            text="\n".join("".join(c.ch for c in ln) for ln in lines),
            flat="".join(c.ch for c in flat_chars),
            char_frames=tuple(c.ta for c in flat_chars),
            src_start_ms=chunk[0].a, src_end_ms=chunk[-1].b,
        ))
    items.sort(key=lambda t: (t.start, t.index))

    # 最小表示時間・隙間埋め・重なり防止
    for i, t in enumerate(items):
        nxt = items[i + 1].start if i + 1 < len(items) else total
        if t.end < t.start + min_frames - 1:
            t.end = t.start + min_frames - 1
            t.notes.append("min_display")
        if 0 < nxt - (t.end + 1) <= fill:
            t.end = nxt - 1
            t.notes.append("fill_gap")
        t.end = min(t.end, nxt - 1, total - 1)
        if t.end < t.start:
            t.end = t.start

    # 編集点吸着（F9）：前のテロップと重ならず、長さが1フレーム以上残る場合だけ動かす
    tol = int(cfg["snap_to_cut_frames"])
    points = boundary_points(cl.edit_points, total)
    prev_end = -1
    for i, t in enumerate(items):
        s = snap_frame(t.start, points, tol)
        if s != t.start and s > prev_end and s <= t.end:
            t.notes.append(f"F9:start {t.start}->{s}")
            t.start = s
        nxt = items[i + 1].start if i + 1 < len(items) else total
        e1 = snap_frame(t.end + 1, points, tol)
        if e1 != t.end + 1 and t.start <= e1 - 1 and e1 <= nxt and e1 <= total:
            t.notes.append(f"F9:end {t.end + 1}->{e1}")
            t.end = e1 - 1
        if t.start <= prev_end:  # 念のため
            t.start = prev_end + 1
            t.end = max(t.end, t.start)
        prev_end = t.end
    res.telops = [t for t in items if t.start < total]
    for i, t in enumerate(res.telops):
        t.index = i
    return res
