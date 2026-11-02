"""エフェクト（オブジェクトの構成要素）のキー表と、実機サンプルからの採取。

組み込みのキー表は、実機で保存されたファイルの公開情報から作ったもの:
  - AviUtl2 (.aup2/.object): 2.00 beta53a 前後で保存された .aup2 の記録
    （動画ファイル＋音声付き、再生位置 = "開始,終了,再生範囲,0" など）
  - 従来版 (.exo): 拡張編集 0.92 のエクスポート形式
AviUtl2 の更新でキー名が変わることがあるので、実機で保存したサンプルを
project.object_samples_aup2 / object_samples_exo に指定すると、そのキー構成を優先する
（`detcut harvest` で組み込み表との差分を確認できる）。
"""

from __future__ import annotations

from typing import Iterable

from detcut.writers.ini import Section, clean_value, parse_ini

# ---------------------------------------------------------------- AviUtl2 built-in

_TRANSFORM_2 = [
    ("X", "0.00"), ("Y", "0.00"), ("Z", "0.00"), ("Group", "1"),
    ("中心X", "0.00"), ("中心Y", "0.00"), ("中心Z", "0.00"),
    ("X軸回転", "0.00"), ("Y軸回転", "0.00"), ("Z軸回転", "0.00"), ("Group2", "1"),
    ("拡大率", "100.000"), ("縦横比", "0.000"), ("透明度", "0.00"), ("合成モード", "通常"),
]

AUP2_BUILTIN: dict[str, list[tuple[str, str]]] = {
    "動画ファイル": [
        ("再生位置", "0.000,0.000,再生範囲,0"), ("再生速度", "100.00"), ("ファイル", ""),
        ("トラック", "0"), ("ループ再生", "0"), ("音声付き", "1"), ("YUV", ""),
    ],
    "映像再生": _TRANSFORM_2 + [("音量", "100.00"), ("左右", "0.00")],
    "音声ファイル": [
        ("再生位置", "0.000,0.000,再生範囲,0"), ("再生速度", "100.00"), ("ファイル", ""),
        ("トラック", "0"), ("ループ再生", "0"),
    ],
    "音声再生": [("音量", "100.00"), ("左右", "0.00")],
    "画像ファイル": [
        ("ファイル", ""), ("表示番号", "0,0,再生範囲,0"), ("再生速度", "100.00"),
        ("ループ再生", "0"), ("連番ファイル", "0"),
    ],
    "テキスト": [
        ("サイズ", "48.00"), ("字間", "0.00"), ("行間", "0.00"), ("表示速度", "0.00"),
        ("フォント", "メイリオ"), ("文字色", "ffffff"), ("影・縁色", "000000"),
        ("文字装飾", "標準文字"), ("文字揃え", "左寄せ[上]"), ("B", "0"), ("I", "0"),
        ("テキスト", ""), ("文字毎に個別オブジェクト", "0"), ("自動スクロール", "0"),
        ("移動座標上に表示", "0"), ("オブジェクトの長さを自動調節", "0"),
    ],
    "標準描画": list(_TRANSFORM_2),
}

# ---------------------------------------------------------------- AviUtl 1.10 + 拡張編集 0.92 built-in

EXO_BUILTIN: dict[str, list[tuple[str, str]]] = {
    "動画ファイル": [
        ("再生位置", "1"), ("再生速度", "100.0"), ("ループ再生", "0"),
        ("アルファチャンネルを読み込む", "0"), ("file", ""),
    ],
    "標準描画": [
        ("X", "0.0"), ("Y", "0.0"), ("Z", "0.0"), ("拡大率", "100.00"),
        ("透明度", "0.0"), ("回転", "0.00"), ("blend", "0"),
    ],
    "音声ファイル": [
        ("再生位置", "0.00"), ("再生速度", "100.0"), ("ループ再生", "0"),
        ("動画ファイルと連携", "0"), ("file", ""),
    ],
    "標準再生": [("音量", "100.0"), ("左右", "0.0")],
    "画像ファイル": [("file", "")],
    "テキスト": [
        ("サイズ", "34"), ("表示速度", "0.0"), ("文字毎に個別オブジェクト", "0"),
        ("移動座標上に表示する", "0"), ("自動スクロール", "0"), ("B", "0"), ("I", "0"),
        ("type", "0"), ("autoadjust", "0"), ("soft", "1"), ("monospace", "0"), ("align", "0"),
        ("spacing_x", "0"), ("spacing_y", "0"), ("precision", "1"), ("color", "ffffff"),
        ("color2", "000000"), ("font", "MS UI Gothic"), ("text", "0" * 4096),
    ],
}

# スタイル名 → 各形式の値
DECORATION_AUP2 = {
    "none": "標準文字", "shadow": "影付き文字", "shadow_light": "影付き文字(薄)",
    "outline": "縁取り文字", "outline_thin": "縁取り文字(細)",
}
DECORATION_EXO = {"none": "0", "shadow": "1", "shadow_light": "2", "outline": "3", "outline_thin": "4"}
_H = {"left": ("左寄せ", 0), "center": ("中央揃え", 1), "right": ("右寄せ", 2)}
_V = {"top": ("上", 0), "middle": ("中", 1), "bottom": ("下", 2)}


def align_aup2(align: str) -> str:
    h, v = align.split("_")
    return f"{_H[h][0]}[{_V[v][0]}]"


def align_exo(align: str) -> str:
    h, v = align.split("_")
    return str(_V[v][1] * 3 + _H[h][1])


# ---------------------------------------------------------------- effect bank

class EffectBank:
    """エフェクトのキー構成（組み込み表 or 実機サンプル）を持ち、値を上書きして組み立てる。"""

    def __init__(self, builtin: dict[str, list[tuple[str, str]]], samples: dict[str, list[tuple[str, str]]] | None,
                 name_key: str):
        self.builtin = builtin
        self.samples = samples or {}
        self.name_key = name_key  # "effect.name" (aup2) / "_name" (exo)
        self.warnings: list[str] = []

    def _warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def build(self, name: str, overrides: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
        from_sample = name in self.samples
        base = self.samples.get(name) or self.builtin.get(name)
        if base is None:
            self._warn(f"エフェクト「{name}」のキー表がありません（指定値だけで書き出します）")
            base = []
        entries = [(k, v) for k, v in base if k != self.name_key]
        index = {k: i for i, (k, _) in enumerate(entries)}
        for k, v in overrides:
            v = clean_value(v)
            if k in index:
                entries[index[k]] = (k, v)
            else:
                if from_sample:
                    self._warn(f"実機サンプルの「{name}」にキー「{k}」がありません（AviUtl側で名前が変わった可能性）")
                index[k] = len(entries)
                entries.append((k, v))
        return [(self.name_key, name)] + entries


# ---------------------------------------------------------------- samples (harvest)

def effects_from_sections(sections: list[Section], name_key: str) -> dict[str, list[tuple[str, str]]]:
    """各エフェクト名について、最初に現れたセクションのキー構成を採取する。"""
    out: dict[str, list[tuple[str, str]]] = {}
    for s in sections:
        if "." not in s.name:
            continue
        name = s.get(name_key)
        if not name or name in out:
            continue
        out[name] = [(k, v if v is not None else "") for k, v in s.entries if k != name_key]
    return out


def read_text_auto(path: str) -> str:
    data = open(path, "rb").read()
    if path.lower().endswith(".exo"):
        return data.decode("cp932", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp932", errors="replace")


def load_samples(path: str | None) -> dict[str, list[tuple[str, str]]] | None:
    if not path:
        return None
    text = read_text_auto(path)
    sections = parse_ini(text)
    key = "_name" if path.lower().endswith(".exo") else "effect.name"
    return effects_from_sections(sections, key)


def diff_against_builtin(samples: dict[str, list[tuple[str, str]]], builtin: dict[str, list[tuple[str, str]]]) -> list[str]:
    lines = []
    for name in sorted(set(samples) | set(builtin)):
        if name not in samples:
            lines.append(f"[{name}] サンプルに無し（組み込み表を使用）")
            continue
        if name not in builtin:
            lines.append(f"[{name}] 組み込み表に無し（サンプルから {len(samples[name])} キー）")
            continue
        sk = [k for k, _ in samples[name]]
        bk = [k for k, _ in builtin[name]]
        missing = [k for k in bk if k not in sk]
        extra = [k for k in sk if k not in bk]
        if not missing and not extra:
            lines.append(f"[{name}] 一致（{len(sk)} キー）")
        else:
            if missing:
                lines.append(f"[{name}] 組み込み表にあってサンプルに無いキー: {', '.join(missing)}")
            if extra:
                lines.append(f"[{name}] サンプルにだけあるキー: {', '.join(extra)}")
    return lines
