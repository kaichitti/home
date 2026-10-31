"""AviUtl ExEdit2 プロジェクト（.aup2：UTF-8・BOMなし・CRLF）の書き出し。

テンプレート方式：AviUtl2で保存した空プロジェクトの [project]・[scene.N] などは保持し、
解像度・fps・音声レートだけ設定値で上書きして、オブジェクトのセクションを追記する。
  [K]    layer=（0始まり） / frame=開始,終了（0始まり・終端を含む）
  [K.0]  メディア入力（動画ファイル・音声ファイル・テキスト…）
  [K.n]  最後が描画/再生（映像再生・音声再生・標準描画）
"""

from __future__ import annotations

import copy
import re
from fractions import Fraction
from typing import Callable

from detcut.common import DetCutError, fmt_fixed
from detcut.timeline.model import Clip, Timeline
from detcut.writers.effects import AUP2_BUILTIN, DECORATION_AUP2, EffectBank, align_aup2
from detcut.writers.ini import Section, parse_ini, serialize_ini

# 組み込みテンプレート（project.template_aup2 を指定しない場合に使う空プロジェクト）
BUILTIN_TEMPLATE_LINES = [
    "[project]", "version=2005200", "file=", "display.scene=0", "preview.scene=0",
    "[scene.0]", "scene=0", "name=Root",
    "video.width=1920", "video.height=1080", "video.rate=30", "video.scale=1", "audio.rate=48000",
    "cursor.frame=0", "cursor.layer=0", "preview.frame=0", "display.frame=0", "display.layer=0",
    "display.zoom=10000", "display.order=0", "display.camera=",
    "display.grid.x=16,-16", "display.grid.y=16,-16", "display.grid.width=200", "display.grid.height=200",
    "display.grid.step=200.000000", "display.grid.range=10000.000000",
    "display.tempo.bpm=120.000000", "display.tempo.beat=4", "display.tempo.offset=0.000000",
]
BUILTIN_TEMPLATE = "\r\n".join(BUILTIN_TEMPLATE_LINES) + "\r\n"
VERIFIED_VERSION = 2005200  # 組み込みキー表を確認した版の [project] version

_OBJ_RE = re.compile(r"^\d+$")
_EFF_RE = re.compile(r"^(\d+)\.(\d+)$")


def escape_text(text: str) -> str:
    """テキスト値のエスケープ（\\ → \\\\、改行 → \\n）。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\\", "\\\\").replace("\n", "\\n")


def _sec(v: Fraction) -> str:
    # 開始位置は切り上げ（ミリ秒）にして、目的のフレームより前に戻らないようにする
    return fmt_fixed(v, 3, "ceil")


def _vol(v) -> str:
    return fmt_fixed(v, 2)


def _volume_track(clip: Clip) -> str:
    a, b = clip.p("volume", 100), clip.p("volume_end")
    if b is None or b == a:
        return _vol(a)
    return f"{_vol(a)},{_vol(b)},直線移動,0"


class Aup2Writer:
    def __init__(self, timeline: Timeline, *, template_text: str | None = None,
                 samples: dict | None = None, style_template_text: str | None = None,
                 scene: int = 0, audio_mode: str = "embedded",
                 path_fn: Callable[[str], str] = lambda p: p):
        self.tl = timeline
        self.template_text = template_text or BUILTIN_TEMPLATE
        self.bank = EffectBank(AUP2_BUILTIN, samples, "effect.name")
        self.scene = scene
        self.audio_mode = audio_mode
        self.path_fn = path_fn
        self.warnings: list[str] = []
        self.template_version: int | None = None
        self.style_effects: list[list[tuple[str, str]]] | None = None
        if style_template_text:
            self.style_effects = _object_effects(parse_ini(style_template_text))
            if not any(dict(e).get("effect.name") == "テキスト" for e in self.style_effects):
                raise DetCutError("telop.style_template に テキスト エフェクトが含まれていません")

    # ------------------------------------------------------------ effects per clip
    def _pos(self, seek: Fraction, length: int) -> str:
        end = seek + Fraction(length) / self.tl.fps
        return f"{_sec(seek)},{_sec(end)},再生範囲,0"

    def effects_for(self, clip: Clip) -> list[list[tuple[str, str]]]:
        b = self.bank
        if clip.kind == "video":
            with_audio = "1" if (clip.p("has_audio") and self.audio_mode == "embedded") else "0"
            return [
                b.build("動画ファイル", [("再生位置", self._pos(clip.p("seek", Fraction(0)), clip.length)),
                                       ("再生速度", "100.00"), ("ファイル", self.path_fn(clip.file)),
                                       ("音声付き", with_audio)]),
                b.build("映像再生", [("X", fmt_fixed(clip.p("x", 0), 2)), ("Y", fmt_fixed(clip.p("y", 0), 2)),
                                   ("拡大率", fmt_fixed(clip.p("scale", 100), 3)), ("音量", _volume_track(clip))]),
            ]
        if clip.kind in ("audio", "se", "bgm"):
            return [
                b.build("音声ファイル", [("再生位置", self._pos(clip.p("seek", Fraction(0)), clip.length)),
                                       ("再生速度", "100.00"), ("ファイル", self.path_fn(clip.file))]),
                b.build("音声再生", [("音量", _volume_track(clip))]),
            ]
        if clip.kind == "image":
            return [
                b.build("画像ファイル", [("ファイル", self.path_fn(clip.file))]),
                b.build("標準描画", [("X", fmt_fixed(clip.p("x", 0), 2)), ("Y", fmt_fixed(clip.p("y", 0), 2)),
                                   ("拡大率", fmt_fixed(clip.p("scale", 100), 3))]),
            ]
        if clip.kind == "text":
            return self._text_effects(clip)
        raise DetCutError(f"未対応のクリップ種別: {clip.kind}")

    def _text_effects(self, clip: Clip) -> list[list[tuple[str, str]]]:
        text = escape_text(clip.p("text", ""))
        if self.style_effects is not None and clip.p("use_template"):
            effects = copy.deepcopy(self.style_effects)
            for e in effects:
                if dict(e).get("effect.name") == "テキスト":
                    for i, (k, _) in enumerate(e):
                        if k == "テキスト":
                            e[i] = (k, text)
                            break
                    else:
                        e.append(("テキスト", text))
            return effects
        st = self.tl.styles.get(clip.p("style_id", "telop"), {})
        over = [
            ("サイズ", fmt_fixed(st.get("size", 48), 2)),
            ("字間", fmt_fixed(st.get("spacing_x", 0), 2)),
            ("行間", fmt_fixed(st.get("spacing_y", 0), 2)),
            ("表示速度", "0.00"),
            ("フォント", st.get("font", "メイリオ")),
            ("文字色", st.get("color", "ffffff")),
            ("影・縁色", st.get("outline_color", "000000")),
            ("文字装飾", DECORATION_AUP2[st.get("decoration", "none")]),
            ("文字揃え", align_aup2(st.get("align", "center_middle"))),
            ("B", "1" if st.get("bold") else "0"),
            ("I", "1" if st.get("italic") else "0"),
            ("テキスト", text),
        ]
        over += sorted((st.get("extra_aup2") or {}).items())
        return [
            self.bank.build("テキスト", over),
            self.bank.build("標準描画", [("X", fmt_fixed(clip.p("x", st.get("x", 0)), 2)),
                                     ("Y", fmt_fixed(clip.p("y", st.get("y", 0)), 2))]),
        ]

    # ------------------------------------------------------------ project
    def clips_to_write(self) -> list[Clip]:
        out = []
        for c in self.tl.sorted_clips():
            if c.kind == "audio" and c.p("linked") and self.audio_mode == "embedded":
                continue  # 動画オブジェクトの「音声付き」で再生されるので不要
            out.append(c)
        return out

    def build(self) -> str:
        sections = parse_ini(self.template_text)
        project = next((s for s in sections if s.name == "project"), None)
        if project is None:
            raise DetCutError("テンプレート .aup2 に [project] セクションがありません")
        try:
            self.template_version = int(project.get("version") or 0)
        except ValueError:
            self.template_version = None
        if self.template_version and self.template_version != VERIFIED_VERSION and not self.bank.samples:
            self.warnings.append(
                f"テンプレートの version={self.template_version} は組み込みキー表の確認版 {VERIFIED_VERSION} と異なります。"
                " AviUtl2で保存したオブジェクト入りの .aup2 を project.object_samples_aup2 に指定すると確実です。")
        project.set("file", "")

        scene_name = f"scene.{self.scene}"
        scene_idx = next((i for i, s in enumerate(sections) if s.name == scene_name), None)
        if scene_idx is None:
            raise DetCutError(f"テンプレート .aup2 に [{scene_name}] がありません")
        scene = sections[scene_idx]
        fps = self.tl.fps
        scene.set("video.width", str(self.tl.width))
        scene.set("video.height", str(self.tl.height))
        scene.set("video.rate", str(fps.numerator))
        scene.set("video.scale", str(fps.denominator))
        scene.set("audio.rate", str(self.tl.audio_rate))

        # シーン内の既存オブジェクトの末尾を探す
        end = scene_idx + 1
        existing = 0
        while end < len(sections) and (_OBJ_RE.match(sections[end].name) or _EFF_RE.match(sections[end].name)):
            if _OBJ_RE.match(sections[end].name):
                existing += 1
            end += 1
        if existing:
            self.warnings.append(f"テンプレートのシーンに既存オブジェクトが {existing} 個あります（重なりに注意）")

        new: list[Section] = []
        for i, clip in enumerate(self.clips_to_write()):
            k = existing + i
            new.append(Section(str(k), [("layer", str(clip.layer - 1)), ("frame", f"{clip.tl_start},{clip.tl_end}")]))
            for j, eff in enumerate(self.effects_for(clip)):
                new.append(Section(f"{k}.{j}", list(eff)))
        sections[end:end] = new
        self.warnings.extend(w for w in self.bank.warnings if w not in self.warnings)
        return serialize_ini(sections, "\r\n")


def _object_effects(sections: list[Section]) -> list[list[tuple[str, str]]]:
    """.object（[Object] / [Object.N]）または .aup2 の最初のオブジェクトのエフェクト列。"""
    effs: list[list[tuple[str, str]]] = []
    head: str | None = None
    for s in sections:
        if head is None:
            if s.name == "Object" or _OBJ_RE.match(s.name):
                head = s.name
            continue
        if s.name.startswith(head + ".") and s.name[len(head) + 1:].isdigit():
            effs.append([(k, v if v is not None else "") for k, v in s.entries])
        elif effs:
            break
    if not effs:
        raise DetCutError("スタイルテンプレートからオブジェクトを読み取れません（[Object.0] などが必要）")
    return effs


def write_aup2(timeline: Timeline, **kw) -> tuple[bytes, list[str], int | None]:
    w = Aup2Writer(timeline, **kw)
    text = w.build()
    return text.encode("utf-8"), w.warnings, w.template_version
