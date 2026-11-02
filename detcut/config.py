"""プリセット（YAML）の読込・スキーマ検証・正規化・ハッシュ計算。

正規化 = 既定値をすべて補完し、相対パスを絶対パスに直し、数値型をそろえた設定。
その正規化済み設定の SHA-256 を「設定ハッシュ」として出力に記録する。
出力先やキャッシュの場所のように結果に影響しない項目はハッシュから除外する。
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from detcut.common import DetCutError, canonical_json, parse_fraction, parse_range_ms, sha256_text

# ---------------------------------------------------------------- defaults

DEFAULT_PARTICLES = [
    "から", "まで", "より", "けど", "ので", "のに", "って", "ため", "けれど",
    "は", "が", "を", "に", "で", "と", "も", "へ", "の", "や", "ね", "よ",
]

DEFAULT_STYLE: dict[str, Any] = {
    "font": "メイリオ",
    "size": 64,
    "color": "ffffff",
    "outline_color": "000000",
    "decoration": "outline",   # none | shadow | shadow_light | outline | outline_thin
    "align": "center_middle",  # {left,center,right}_{top,middle,bottom}
    "x": 0,
    "y": 400,
    "bold": False,
    "italic": False,
    "spacing_x": 0,
    "spacing_y": 0,
    "extra_aup2": {},           # テキストエフェクトに直接書き込むキー（AviUtl2）
    "extra_exo": {},            # 同（従来版 .exo）
}

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "paths": {"base_dir": "."},
    "project": {
        "target": "aup2",          # aup2 | exo | both
        "width": 1920,             # 整数 または "auto"（入力動画から取得）
        "height": 1080,
        "fps": "auto",             # "30000/1001" / 30 / "auto"
        "audio_rate": 48000,
        "audio_ch": 2,
        "scene": 0,
        "template_aup2": None,     # AviUtl2で保存した空プロジェクト
        "aup2_audio": "embedded",  # embedded（動画オブジェクトの音声付き）| separate（音声ファイルを別レイヤー）
        "object_samples_aup2": None,  # 実機で保存した .aup2/.object（キー名を採取）
        "object_samples_exo": None,   # 実機でエクスポートした .exo
    },
    "cut": {
        "enabled": True,
        "mode": "jetcut",          # jetcut | compress
        "speech_on_db": -38.0,
        "speech_off_db": -45.0,
        "min_silence_ms": 350,
        "min_speech_ms": 120,
        "pad_before_ms": 80,
        "pad_after_ms": 120,
        "merge_gap_ms": 150,
        "compress_to_ms": 200,
        "keep_ranges": [],
        "force_cut_ranges": [],
    },
    "telop": {
        "enabled": False,
        "transcript_file": None,   # 指定するとASRを使わずにこのSRT/JSONを使う
        "asr": {
            "engine": "faster-whisper",
            "model": "large-v3",
            "model_path": None,
            "model_sha256": None,
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": 4,
            "language": "ja",
            "beam_size": 5,
            "temperature": 0.0,
            "vad_filter": True,
            "condition_on_previous_text": False,
            "initial_prompt": None,
        },
        "max_chars_per_line": 24,
        "max_lines": 2,
        "min_display_ms": 800,
        "gap_break_ms": 700,
        "fill_gap_ms": 300,
        "break_on_segment": True,
        "snap_to_cut_frames": 6,
        "strip_trailing": "。",
        "break_after": "、。，．！？!?…",
        "sentence_end": "。！？!?",
        "particles": DEFAULT_PARTICLES,
        "no_line_start": "、。，．！？!?）」』】ー〜ぁぃぅぇぉっゃゅょァィゥェォッャュョ",
        "no_line_end": "（「『【",
        "style_template": None,      # AviUtl2で保存したテキストの .object
        "style_template_exo": None,  # 従来版でエクスポートしたテキストの .exo
        "style": DEFAULT_STYLE,
        "dictionary": None,
    },
    "se": {
        "enabled": False,
        "snap_to_cut_frames": 3,
        "min_gap_ms": 0,
        "rules": [],
    },
    "bgm": {
        "enabled": False,
        "file": None,
        "volume": 25,
        "duck": True,
        "duck_volume": 12,
        "duck_min_gap_ms": 1500,
        "duck_fade_ms": 300,
    },
    "zoom": {
        "enabled": False,
        "min_shot_ms": 6000,
        "split_long_ms": 0,
        "levels": [{"scale": 100, "x": 0, "y": 0}, {"scale": 110, "x": 0, "y": 0}],
    },
    "chapters": {
        "file": None,
        "items": [],
        "title_telop": False,
        "title_ms": 3000,
        "style": {},
    },
    "layers": {"video": 1, "audio": 2, "telop": 4, "chapter": 5, "bgm": 9},
    "shortcuts": [],
    "output": {
        "dir": "./out",
        "report_csv": True,
        "cutlist_json": True,
        "timeline_json": True,
        "path_map": [],            # [["/mnt/c/", "C:\\"]] のように前方一致で置換
        "windows_paths": "auto",   # auto | true | false（区切り文字を \ にする）
        "open_after": False,
        "aviutl2_exe": None,
    },
    "ffmpeg": {
        "ffmpeg": "ffmpeg",
        "ffprobe": "ffprobe",
        "expected_version_sha256": None,
    },
    "cache": {"enabled": True, "dir": ".detcut_cache"},
}

SE_RULE_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "pattern": None,
    "file": None,
    "files": [],
    "dir": None,
    "pick": "first",        # first | hash
    "layer": 6,
    "volume": 80,
    "priority": 0,
    "min_interval_ms": 0,
    "min_cut_ms": 1000,
    "offset_ms": 0,
    "anchor": "match",      # match | telop_start
    "max_per_telop": 1,
    "duration_ms": None,
}

SHORTCUT_DEFAULTS: dict[str, Any] = {"label": None, "length_ms": 2000, "items": []}
SHORTCUT_ITEM_DEFAULTS: dict[str, Any] = {
    "text": None,
    "file": None,
    "layer": 0,
    "offset_ms": 0,
    "length_ms": None,
    "volume": 100,
    "x": 0,
    "y": 0,
    "scale": 100,
    "style": {},
}

# 結果に影響しない（ハッシュから除外する）項目
HASH_EXCLUDE: list[tuple[str, ...]] = [
    ("output", "dir"),
    ("output", "open_after"),
    ("output", "aviutl2_exe"),
    ("cache",),
    ("shortcuts",),
]

# ---------------------------------------------------------------- schema

def _obj(props: dict[str, Any], required: list[str] | None = None, extra: bool = False) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": extra}
    if required:
        s["required"] = required
    return s


_STR = {"type": "string"}
_STR_N = {"type": ["string", "null"]}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}
_NONNEG = {"type": "integer", "minimum": 0}
_COLOR = {"type": "string", "pattern": "^[0-9a-fA-F]{6}$"}
_LAYER = {"type": "integer", "minimum": 1, "maximum": 1000}
_RANGE = {"oneOf": [_STR, {"type": "array", "minItems": 2, "maxItems": 2}]}

_STYLE_SCHEMA = _obj({
    "font": _STR, "size": _NUM, "color": _COLOR, "outline_color": _COLOR,
    "decoration": {"enum": ["none", "shadow", "shadow_light", "outline", "outline_thin"]},
    "align": {"enum": [f"{h}_{v}" for v in ("top", "middle", "bottom") for h in ("left", "center", "right")]},
    "x": _NUM, "y": _NUM, "bold": _BOOL, "italic": _BOOL, "spacing_x": _INT, "spacing_y": _INT,
    "extra_aup2": {"type": "object"}, "extra_exo": {"type": "object"},
})

SCHEMA: dict[str, Any] = _obj({
    "version": {"const": 1},
    "paths": _obj({"base_dir": _STR}),
    "project": _obj({
        "target": {"enum": ["aup2", "exo", "both"]},
        "width": {"oneOf": [{"type": "integer", "minimum": 16}, {"const": "auto"}]},
        "height": {"oneOf": [{"type": "integer", "minimum": 16}, {"const": "auto"}]},
        "fps": {"type": ["string", "integer", "number"]},
        "audio_rate": {"type": "integer", "minimum": 8000},
        "audio_ch": {"enum": [1, 2]},
        "scene": _NONNEG,
        "template_aup2": _STR_N,
        "aup2_audio": {"enum": ["embedded", "separate"]},
        "object_samples_aup2": _STR_N,
        "object_samples_exo": _STR_N,
    }),
    "cut": _obj({
        "enabled": _BOOL,
        "mode": {"enum": ["jetcut", "compress"]},
        "speech_on_db": {"type": "number", "maximum": 0, "minimum": -120},
        "speech_off_db": {"type": "number", "maximum": 0, "minimum": -120},
        "min_silence_ms": _NONNEG, "min_speech_ms": _NONNEG,
        "pad_before_ms": _NONNEG, "pad_after_ms": _NONNEG,
        "merge_gap_ms": _NONNEG, "compress_to_ms": _NONNEG,
        "keep_ranges": {"type": "array", "items": _RANGE},
        "force_cut_ranges": {"type": "array", "items": _RANGE},
    }),
    "telop": _obj({
        "enabled": _BOOL,
        "transcript_file": _STR_N,
        "asr": _obj({
            "engine": {"enum": ["faster-whisper", "none"]},
            "model": _STR, "model_path": _STR_N, "model_sha256": _STR_N,
            "device": {"enum": ["cpu", "cuda", "auto"]},
            "compute_type": _STR, "cpu_threads": {"type": "integer", "minimum": 1},
            "language": _STR_N, "beam_size": {"type": "integer", "minimum": 1},
            "temperature": {"type": "number", "minimum": 0},
            "vad_filter": _BOOL, "condition_on_previous_text": _BOOL,
            "initial_prompt": _STR_N,
        }),
        "max_chars_per_line": {"type": "integer", "minimum": 1},
        "max_lines": {"type": "integer", "minimum": 1, "maximum": 10},
        "min_display_ms": _NONNEG, "gap_break_ms": _NONNEG, "fill_gap_ms": _NONNEG,
        "break_on_segment": _BOOL,
        "snap_to_cut_frames": _NONNEG,
        "strip_trailing": _STR, "break_after": _STR, "sentence_end": _STR,
        "particles": {"type": "array", "items": _STR},
        "no_line_start": _STR, "no_line_end": _STR,
        "style_template": _STR_N, "style_template_exo": _STR_N,
        "style": _STYLE_SCHEMA,
        "dictionary": _STR_N,
    }),
    "se": _obj({
        "enabled": _BOOL,
        "snap_to_cut_frames": _NONNEG,
        "min_gap_ms": _NONNEG,
        "rules": {"type": "array", "items": _obj({
            "id": _STR,
            "type": {"enum": ["keyword", "after_cut", "chapter"]},
            "enabled": _BOOL, "pattern": _STR_N, "file": _STR_N,
            "files": {"type": "array", "items": _STR}, "dir": _STR_N,
            "pick": {"enum": ["first", "hash"]},
            "layer": _LAYER, "volume": _NUM, "priority": _INT,
            "min_interval_ms": _NONNEG, "min_cut_ms": _NONNEG, "offset_ms": _INT,
            "anchor": {"enum": ["match", "telop_start"]},
            "max_per_telop": {"type": "integer", "minimum": 1},
            "duration_ms": {"type": ["integer", "null"], "minimum": 1},
        }, required=["id", "type"])},
    }),
    "bgm": _obj({
        "enabled": _BOOL, "file": _STR_N, "volume": _NUM, "duck": _BOOL,
        "duck_volume": _NUM, "duck_min_gap_ms": _NONNEG, "duck_fade_ms": _NONNEG,
    }),
    "zoom": _obj({
        "enabled": _BOOL, "min_shot_ms": _NONNEG, "split_long_ms": _NONNEG,
        "levels": {"type": "array", "minItems": 1, "items": _obj({"scale": _NUM, "x": _NUM, "y": _NUM})},
    }),
    "chapters": _obj({
        "file": _STR_N,
        "items": {"type": "array", "items": _obj({"at": {"type": ["string", "integer"]}, "title": _STR}, required=["at"])},
        "title_telop": _BOOL, "title_ms": _NONNEG,
        "style": {"type": "object"},
    }),
    "layers": _obj({k: _LAYER for k in ("video", "audio", "telop", "chapter", "bgm")}),
    "shortcuts": {"type": "array", "items": _obj({
        "id": {"type": "string", "pattern": "^[A-Za-z0-9_\\-]+$"},
        "label": _STR_N,
        "length_ms": {"type": "integer", "minimum": 1},
        "items": {"type": "array", "items": _obj({
            "type": {"enum": ["text", "se", "image", "template"]},
            "text": _STR_N, "file": _STR_N, "layer": _NONNEG, "offset_ms": _NONNEG,
            "length_ms": {"type": ["integer", "null"], "minimum": 1},
            "volume": _NUM, "x": _NUM, "y": _NUM, "scale": _NUM, "style": {"type": "object"},
        }, required=["type"])},
    }, required=["id"])},
    "output": _obj({
        "dir": _STR, "report_csv": _BOOL, "cutlist_json": _BOOL, "timeline_json": _BOOL,
        "path_map": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": _STR}},
        "windows_paths": {"enum": ["auto", True, False]},
        "open_after": _BOOL, "aviutl2_exe": _STR_N,
    }),
    "ffmpeg": _obj({"ffmpeg": _STR, "ffprobe": _STR, "expected_version_sha256": _STR_N}),
    "cache": _obj({"enabled": _BOOL, "dir": _STR}),
})


# ---------------------------------------------------------------- loading

def deep_merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = {k: copy.deepcopy(v) for k, v in base.items()}
        for k, v in over.items():
            out[k] = deep_merge(out[k], v) if k in out else copy.deepcopy(v)
        return out
    return copy.deepcopy(over)


def apply_override(data: dict[str, Any], expr: str) -> None:
    """'cut.speech_on_db=-40' の形式の上書きを適用する（値はYAMLとして解釈）。"""
    if "=" not in expr:
        raise DetCutError(f"--set は key=value の形式で指定してください: {expr!r}")
    key, raw = expr.split("=", 1)
    parts = [p for p in key.strip().split(".") if p]
    if not parts:
        raise DetCutError(f"--set のキーが空です: {expr!r}")
    try:
        value = yaml.safe_load(raw) if raw.strip() != "" else ""
    except yaml.YAMLError as e:
        raise DetCutError(f"--set の値を解釈できません: {expr!r} ({e})") from e
    cur: Any = data
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(cur, list):
            if not p.isdigit() or int(p) >= len(cur):
                raise DetCutError(f"--set のリスト番号が範囲外です: {expr!r}（0始まり）")
            if last:
                cur[int(p)] = value
            else:
                cur = cur[int(p)]
            continue
        if last:
            cur[p] = value
            break
        nxt = cur.get(p)
        if not isinstance(nxt, (dict, list)):
            nxt = {}
            cur[p] = nxt
        cur = nxt


def _validate(data: dict[str, Any], source: str) -> None:
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - 依存が入っていない環境向け
        return
    validator = jsonschema.Draft202012Validator(SCHEMA)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        lines = []
        for e in errors[:10]:
            where = ".".join(str(p) for p in e.absolute_path) or "(ルート)"
            lines.append(f"  - {where}: {e.message}")
        hint = ""
        if any("pattern" in str(e.schema) and "0-9a-fA-F" in str(e.schema) for e in errors):
            hint = "\n  ※色は \"ffffff\" のように引用符で囲んでください。"
        raise DetCutError(f"設定ファイルの内容に誤りがあります（{source}）:\n" + "\n".join(lines) + hint)


@dataclass
class Config:
    data: dict[str, Any]
    preset_path: str | None
    base_dir: str
    sha256: str = ""
    hashed_view: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, *path: str, default: Any = None) -> Any:
        cur: Any = self.data
        for p in path:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur


def load_config(preset: str | os.PathLike | None, overrides: list[str] | None = None) -> Config:
    raw: dict[str, Any] = {}
    preset_path: str | None = None
    if preset is not None:
        preset_path = os.path.abspath(os.fspath(preset))
        if not os.path.exists(preset_path):
            raise DetCutError(f"プリセットが見つかりません: {preset_path}")
        try:
            with open(preset_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise DetCutError(f"プリセットのYAMLを読めません: {preset_path}\n{e}") from e
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise DetCutError(f"プリセットの最上位はマッピングである必要があります: {preset_path}")
        raw = loaded
    for expr in overrides or []:
        apply_override(raw, expr)

    _validate(raw, preset_path or "--set")
    data = deep_merge(DEFAULTS, raw)
    _validate(data, preset_path or "既定値")

    preset_dir = os.path.dirname(preset_path) if preset_path else os.getcwd()
    base_dir = os.path.normpath(os.path.join(preset_dir, os.path.expanduser(data["paths"]["base_dir"])))
    data["paths"]["base_dir"] = base_dir
    _normalize(data, base_dir)

    cfg = Config(data=data, preset_path=preset_path, base_dir=base_dir)
    cfg.hashed_view = hashed_view(data)
    cfg.sha256 = sha256_text(canonical_json(cfg.hashed_view))
    return cfg


def hashed_view(data: dict[str, Any]) -> dict[str, Any]:
    view = copy.deepcopy(data)
    for path in HASH_EXCLUDE:
        cur = view
        for p in path[:-1]:
            cur = cur.get(p, {})
        cur.pop(path[-1], None)
    return view


# ---------------------------------------------------------------- normalization

def resolve_path(p: str | None, base_dir: str) -> str | None:
    if p is None or p == "":
        return None
    p = os.path.expanduser(os.path.expandvars(p))
    if not os.path.isabs(p):
        p = os.path.join(base_dir, p)
    return os.path.normpath(os.path.abspath(p))


def _num(v: Any) -> Any:
    """1.0 のような整数値の float を int に寄せ、表記ゆれでハッシュが変わらないようにする。"""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _normalize(data: dict[str, Any], base: str) -> None:
    pr = data["project"]
    for k in ("template_aup2", "object_samples_aup2", "object_samples_exo"):
        pr[k] = resolve_path(pr[k], base)
    if str(pr["fps"]).lower() != "auto":
        try:
            fr = parse_fraction(pr["fps"])
        except (ValueError, ZeroDivisionError) as e:
            raise DetCutError(f"project.fps を解釈できません: {pr['fps']!r}") from e
        if fr <= 0:
            raise DetCutError("project.fps は正の値にしてください")
        pr["fps"] = f"{fr.numerator}/{fr.denominator}"
    else:
        pr["fps"] = "auto"

    cut = data["cut"]
    for k in ("speech_on_db", "speech_off_db"):
        cut[k] = _num(float(cut[k]))
    if cut["speech_on_db"] < cut["speech_off_db"]:
        raise DetCutError("cut.speech_on_db は cut.speech_off_db 以上にしてください（ヒステリシス）")
    cut["keep_ranges"] = [list(parse_range_ms(r)) for r in cut["keep_ranges"]]
    cut["force_cut_ranges"] = [list(parse_range_ms(r)) for r in cut["force_cut_ranges"]]

    tel = data["telop"]
    for k in ("transcript_file", "style_template", "style_template_exo", "dictionary"):
        tel[k] = resolve_path(tel[k], base)
    tel["asr"]["model_path"] = resolve_path(tel["asr"]["model_path"], base)
    tel["asr"]["temperature"] = _num(float(tel["asr"]["temperature"]))
    tel["style"] = _normalize_style(deep_merge(DEFAULT_STYLE, tel["style"]))

    rules = []
    seen = set()
    for r in data["se"]["rules"]:
        rr = deep_merge(SE_RULE_DEFAULTS, r)
        if rr["id"] in seen:
            raise DetCutError(f"se.rules の id が重複しています: {rr['id']}")
        seen.add(rr["id"])
        rr["file"] = resolve_path(rr["file"], base)
        rr["files"] = [resolve_path(x, base) for x in rr["files"]]
        rr["dir"] = resolve_path(rr["dir"], base)
        rr["volume"] = _num(rr["volume"])
        if rr["type"] == "keyword" and not rr["pattern"]:
            raise DetCutError(f"se.rules[{rr['id']}]: keyword ルールには pattern が必要です")
        rules.append(rr)
    data["se"]["rules"] = rules

    bgm = data["bgm"]
    bgm["file"] = resolve_path(bgm["file"], base)
    for k in ("volume", "duck_volume"):
        bgm[k] = _num(bgm[k])

    data["zoom"]["levels"] = [
        {"scale": _num(lv.get("scale", 100)), "x": _num(lv.get("x", 0)), "y": _num(lv.get("y", 0))}
        for lv in data["zoom"]["levels"]
    ]

    ch = data["chapters"]
    ch["file"] = resolve_path(ch["file"], base)
    ch["style"] = _normalize_style(deep_merge(tel["style"], ch["style"]))

    shortcuts = []
    sc_seen = set()
    for sc in data["shortcuts"]:
        s = deep_merge(SHORTCUT_DEFAULTS, sc)
        if s["id"] in sc_seen:
            raise DetCutError(f"shortcuts の id が重複しています: {s['id']}")
        sc_seen.add(s["id"])
        items = []
        for it in s["items"]:
            ii = deep_merge(SHORTCUT_ITEM_DEFAULTS, it)
            ii["file"] = resolve_path(ii["file"], base)
            ii["style"] = _normalize_style(deep_merge(tel["style"], ii["style"]))
            items.append(ii)
        s["items"] = items
        if s["label"] is None:
            s["label"] = s["id"]
        shortcuts.append(s)
    data["shortcuts"] = shortcuts

    out = data["output"]
    out["dir"] = resolve_path(out["dir"], base)
    out["aviutl2_exe"] = resolve_path(out["aviutl2_exe"], base) if out["aviutl2_exe"] else None
    data["cache"]["dir"] = resolve_path(data["cache"]["dir"], base)


def _normalize_style(style: dict[str, Any]) -> dict[str, Any]:
    st = dict(style)
    for k in ("color", "outline_color"):
        v = st.get(k)
        if not isinstance(v, str) or len(v) != 6:
            raise DetCutError(f"style.{k} は \"ffffff\" のような6桁の16進文字列にしてください（引用符で囲む）: {v!r}")
        st[k] = v.lower()
    for k in ("size", "x", "y"):
        st[k] = _num(st[k])
    st["extra_aup2"] = {str(k): str(v) for k, v in (st.get("extra_aup2") or {}).items()}
    st["extra_exo"] = {str(k): str(v) for k, v in (st.get("extra_exo") or {}).items()}
    return st


def find_presets(*dirs: str | os.PathLike) -> list[Path]:
    seen: list[Path] = []
    for d in dirs:
        p = Path(d)
        if p.is_dir():
            for f in sorted(p.glob("*.yaml")) + sorted(p.glob("*.yml")):
                if f not in seen:
                    seen.append(f)
    return seen
