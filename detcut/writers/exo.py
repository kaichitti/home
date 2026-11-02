"""従来版 AviUtl 1.10 + 拡張編集 0.92 向け .exo（Shift-JIS・CRLF）の書き出し。

  [exedit]  width / height / rate / scale / length / audio_rate / audio_ch
  [n]       start / end（1始まり・終端を含む）/ layer（1始まり）/ group / overlay / camera or audio
  [n.0]     _name=動画ファイル など（オブジェクト本体）
  [n.1]~    フィルタ（最後が 標準描画 / 標準再生）
テキスト本体は UTF-16LE の16進文字列（4096桁まで0埋め）なので、Shift-JISにない文字も扱える。
AviUtl2 でも .exo は読み込める（Shift-JISが必要）。
"""

from __future__ import annotations

import copy
from fractions import Fraction
from typing import Callable

from detcut.common import DetCutError, fmt_fixed
from detcut.timeline.model import Clip, Timeline
from detcut.writers.effects import DECORATION_EXO, EXO_BUILTIN, EffectBank, align_exo
from detcut.writers.ini import Section, parse_ini, serialize_ini

TEXT_HEX_LEN = 4096
ENCODING = "cp932"


def exo_text_hex(text: str, warnings: list[str] | None = None) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    data = t.encode("utf-16-le")
    limit = TEXT_HEX_LEN // 2 - 2  # 終端の NUL 分を残す
    if len(data) > limit:
        data = data[: limit - (limit % 2)]
        if warnings is not None:
            warnings.append(f"テキストが長すぎるため切り詰めました: {text[:20]}…")
    return data.hex().ljust(TEXT_HEX_LEN, "0")


def decode_exo_text(hexstr: str) -> str:
    raw = bytes.fromhex(hexstr)
    end = 0
    while end + 1 < len(raw) and not (raw[end] == 0 and raw[end + 1] == 0):
        end += 2
    return raw[:end].decode("utf-16-le").replace("\r\n", "\n")


def _vol(v) -> str:
    return fmt_fixed(v, 1)


def _volume_track(clip: Clip) -> str:
    a, b = clip.p("volume", 100), clip.p("volume_end")
    if b is None or b == a:
        return _vol(a)
    return f"{_vol(a)},{_vol(b)},1"  # 1 = 直線移動


class ExoWriter:
    def __init__(self, timeline: Timeline, *, samples: dict | None = None,
                 style_template_text: str | None = None, path_fn: Callable[[str], str] = lambda p: p):
        self.tl = timeline
        self.bank = EffectBank(EXO_BUILTIN, samples, "_name")
        self.path_fn = path_fn
        self.warnings: list[str] = []
        self.style_obj: tuple[list[tuple[str, str]], list[list[tuple[str, str]]]] | None = None
        if style_template_text:
            self.style_obj = _exo_text_object(parse_ini(style_template_text))

    def _path(self, p: str) -> str:
        out = self.path_fn(p)
        try:
            out.encode(ENCODING)
        except UnicodeEncodeError as e:
            raise DetCutError(
                f"このファイルパスは Shift-JIS で表せない文字を含むため .exo に書けません: {out}\n"
                "ファイル名・フォルダ名を変更するか、.aup2 出力を使ってください。") from e
        return out

    def _src_pos(self, clip: Clip) -> str:
        seek: Fraction = clip.p("seek", Fraction(0))
        src_fps: Fraction | None = clip.p("source_fps")
        rate = src_fps or self.tl.fps
        v = seek * rate
        return str(v.numerator // v.denominator + 1)

    def effects_for(self, clip: Clip) -> list[list[tuple[str, str]]]:
        b = self.bank
        if clip.kind == "video":
            return [
                b.build("動画ファイル", [("再生位置", self._src_pos(clip)), ("再生速度", "100.0"),
                                       ("file", self._path(clip.file))]),
                b.build("標準描画", [("X", fmt_fixed(clip.p("x", 0), 1)), ("Y", fmt_fixed(clip.p("y", 0), 1)),
                                   ("拡大率", fmt_fixed(clip.p("scale", 100), 2))]),
            ]
        if clip.kind in ("audio", "se", "bgm"):
            linked = "1" if clip.p("linked") else "0"
            return [
                b.build("音声ファイル", [("再生位置", fmt_fixed(clip.p("seek", Fraction(0)), 2)),
                                       ("再生速度", "100.0"), ("動画ファイルと連携", linked),
                                       ("file", self._path(clip.file))]),
                b.build("標準再生", [("音量", _volume_track(clip))]),
            ]
        if clip.kind == "image":
            return [
                b.build("画像ファイル", [("file", self._path(clip.file))]),
                b.build("標準描画", [("X", fmt_fixed(clip.p("x", 0), 1)), ("Y", fmt_fixed(clip.p("y", 0), 1)),
                                   ("拡大率", fmt_fixed(clip.p("scale", 100), 2))]),
            ]
        if clip.kind == "text":
            return self._text_effects(clip)
        raise DetCutError(f"未対応のクリップ種別: {clip.kind}")

    def _text_effects(self, clip: Clip) -> list[list[tuple[str, str]]]:
        hexed = exo_text_hex(clip.p("text", ""), self.warnings)
        if self.style_obj is not None and clip.p("use_template"):
            effects = copy.deepcopy(self.style_obj[1])
            for i, (k, _) in enumerate(effects[0]):
                if k == "text":
                    effects[0][i] = (k, hexed)
                    break
            else:
                effects[0].append(("text", hexed))
            return effects
        st = self.tl.styles.get(clip.p("style_id", "telop"), {})
        over = [
            ("サイズ", str(int(st.get("size", 34)))),
            ("B", "1" if st.get("bold") else "0"),
            ("I", "1" if st.get("italic") else "0"),
            ("type", DECORATION_EXO[st.get("decoration", "none")]),
            ("align", align_exo(st.get("align", "center_middle"))),
            ("spacing_x", str(int(st.get("spacing_x", 0)))),
            ("spacing_y", str(int(st.get("spacing_y", 0)))),
            ("color", st.get("color", "ffffff")),
            ("color2", st.get("outline_color", "000000")),
            ("font", st.get("font", "MS UI Gothic")),
            ("text", hexed),
        ]
        over += sorted((st.get("extra_exo") or {}).items())
        return [
            self.bank.build("テキスト", over),
            self.bank.build("標準描画", [("X", fmt_fixed(clip.p("x", st.get("x", 0)), 1)),
                                     ("Y", fmt_fixed(clip.p("y", st.get("y", 0)), 1))]),
        ]

    def build(self) -> str:
        fps = self.tl.fps
        length = max(1, self.tl.length)
        sections = [Section("exedit", [
            ("width", str(self.tl.width)), ("height", str(self.tl.height)),
            ("rate", str(fps.numerator)), ("scale", str(fps.denominator)),
            ("length", str(length)), ("audio_rate", str(self.tl.audio_rate)),
            ("audio_ch", str(self.tl.audio_ch)),
        ])]
        group_ids: dict[int, int] = {}
        next_group = 1
        for i, clip in enumerate(self.tl.sorted_clips()):
            if clip.group:
                if clip.group not in group_ids:
                    group_ids[clip.group] = next_group
                    next_group += 1
                g = group_ids[clip.group]
            else:
                g = next_group
                next_group += 1
            head = [("start", str(clip.tl_start + 1)), ("end", str(clip.tl_end + 1)),
                    ("layer", str(clip.layer)), ("group", str(g)), ("overlay", "1")]
            if clip.kind in ("audio", "se", "bgm"):
                head.append(("audio", "1"))
            elif self.style_obj is not None and clip.kind == "text" and clip.p("use_template"):
                skip = {"start", "end", "layer", "group", "overlay", "audio"}
                head += [(k, v) for k, v in self.style_obj[0] if k not in skip]
            else:
                head.append(("camera", "0"))
            sections.append(Section(str(i), head))
            for j, eff in enumerate(self.effects_for(clip)):
                sections.append(Section(f"{i}.{j}", list(eff)))
        self.warnings.extend(w for w in self.bank.warnings if w not in self.warnings)
        return serialize_ini(sections, "\r\n")


def _exo_text_object(sections: list[Section]):
    """スタイル用 .exo から、最初のテキストオブジェクト（ヘッダとエフェクト列）を取り出す。"""
    by_name = {s.name: s for s in sections}
    idx = 0
    while str(idx) in by_name:
        first = by_name.get(f"{idx}.0")
        if first is not None and first.get("_name") == "テキスト":
            head = [(k, v or "") for k, v in by_name[str(idx)].entries]
            effs = []
            j = 0
            while f"{idx}.{j}" in by_name:
                effs.append([(k, v or "") for k, v in by_name[f"{idx}.{j}"].entries])
                j += 1
            return head, effs
        idx += 1
    raise DetCutError("telop.style_template_exo にテキストオブジェクトが見つかりません")


def write_exo(timeline: Timeline, **kw) -> tuple[bytes, list[str]]:
    w = ExoWriter(timeline, **kw)
    text = w.build()
    try:
        data = text.encode(ENCODING)
    except UnicodeEncodeError as e:
        raise DetCutError(f".exo を Shift-JIS で書き出せません（表せない文字があります）: {e}") from e
    return data, w.warnings
