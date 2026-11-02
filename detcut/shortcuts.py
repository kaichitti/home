"""ショートカットボタン（F15）。

よく使う「テロップ・SE・画像・演出テンプレートの組み合わせ」をプリセットの shortcuts に定義しておき、
ボタン（GUI）またはコマンド（detcut shortcut ID）1つで、AviUtlにドラッグ&ドロップできるファイルを作る。

  shortcuts/<id>.exo           組み合わせ全体（AviUtl2・従来版の両方で読み込める）
  shortcuts/<id>.object        単体アイテムのとき（AviUtl2のオブジェクトエイリアス）
  shortcuts/<id>_<n>.object    複数アイテムのときは1つずつ
"""

from __future__ import annotations

import os
from fractions import Fraction
from typing import Any

from detcut.common import DetCutError, write_bytes
from detcut.config import Config
from detcut.media.probe import media_duration
from detcut.timebase import TimeBase
from detcut.timeline.model import Clip, Timeline, make_params
from detcut.writers.alias import build_object
from detcut.writers.aup2 import Aup2Writer
from detcut.writers.effects import load_samples, read_text_auto
from detcut.writers.exo import ExoWriter
from detcut.writers.ini import Section, parse_ini, serialize_ini
from detcut.writers.paths import output_path


def shortcut_fps(cfg: Config) -> Fraction:
    v = cfg["project"]["fps"]
    return Fraction(30) if v == "auto" else Fraction(v)


def build_shortcut(sc: dict[str, Any], cfg: Config, fps: Fraction | None = None) -> dict[str, bytes]:
    fps = fps or shortcut_fps(cfg)
    tb = TimeBase(fps=fps)
    pr = cfg["project"]
    width = pr["width"] if pr["width"] != "auto" else 1920
    height = pr["height"] if pr["height"] != "auto" else 1080
    tl = Timeline(fps=fps, width=int(width), height=int(height), audio_rate=int(pr["audio_rate"]),
                  audio_ch=int(pr["audio_ch"]))
    default_len = max(1, tb.ms_to_frames_ceil(int(sc["length_ms"])))
    templates: list[tuple[int, dict[str, Any]]] = []
    ffprobe = cfg["ffmpeg"]["ffprobe"]

    for n, it in enumerate(sc["items"]):
        start = tb.ms_to_frames_round(int(it["offset_ms"]))
        layer = 1 + int(it["layer"])
        if it["length_ms"]:
            length = max(1, tb.ms_to_frames_ceil(int(it["length_ms"])))
        elif it["type"] == "se" and it["file"]:
            d = media_duration(it["file"], ffprobe) if os.path.isfile(it["file"]) else None
            length = max(1, tb.seconds_to_frames_ceil(d)) if d else max(1, default_len - start)
        else:
            length = max(1, default_len - start)
        end = start + length - 1
        cid = f"x{n + 1:02d}"
        t = it["type"]
        if t in ("se", "image", "template") and not it["file"]:
            raise DetCutError(f"shortcuts[{sc['id']}] の {n + 1} 番目（{t}）に file がありません")
        if t in ("se", "image", "template") and not os.path.isfile(it["file"]):
            raise DetCutError(f"shortcuts[{sc['id']}] のファイルが見つかりません: {it['file']}")
        if t == "text":
            sid = f"{sc['id']}_{n}"
            tl.styles[sid] = dict(it["style"])
            x = it["style"]["x"] + it["x"]
            y = it["style"]["y"] + it["y"]
            tl.clips.append(Clip(id=cid, kind="text", layer=layer, tl_start=start, tl_end=end,
                                 params=make_params(text=it["text"] or "", style_id=sid, x=x, y=y)))
        elif t == "se":
            tl.clips.append(Clip(id=cid, kind="se", layer=layer, tl_start=start, tl_end=end, file=it["file"],
                                 params=make_params(seek=Fraction(0), volume=it["volume"])))
        elif t == "image":
            tl.clips.append(Clip(id=cid, kind="image", layer=layer, tl_start=start, tl_end=end, file=it["file"],
                                 params=make_params(x=it["x"], y=it["y"], scale=it["scale"])))
        elif t == "template":
            templates.append((n, it))

    o = cfg["output"]
    path_fn = lambda p: output_path(p, o["path_map"], o["windows_paths"])  # noqa: E731
    out: dict[str, bytes] = {}

    aw = Aup2Writer(tl, samples=load_samples(pr["object_samples_aup2"]), path_fn=path_fn)
    clips = tl.sorted_clips()
    if len(clips) == 1 and not templates:
        out[f"{sc['id']}.object"] = build_object(aw, clips[0]).encode("utf-8")
    else:
        for c in clips:
            out[f"{sc['id']}_{c.id[1:]}.object"] = build_object(aw, c).encode("utf-8")

    ew = ExoWriter(tl, samples=load_samples(pr["object_samples_exo"]), path_fn=path_fn)
    exo_sections = parse_ini(ew.build())
    for n, it in templates:
        f = it["file"]
        if f.lower().endswith(".exo"):
            exo_sections = merge_exo(exo_sections, parse_ini(read_text_auto(f)),
                                     layer_offset=int(it["layer"]),
                                     frame_offset=tb.ms_to_frames_round(int(it["offset_ms"])))
        elif f.lower().endswith(".object"):
            out[f"{sc['id']}_{n + 1:02d}.object"] = open(f, "rb").read()
        else:
            raise DetCutError(f"template には .exo か .object を指定してください: {f}")
    length = 0
    for s in exo_sections:
        if s.name.isdigit():
            length = max(length, int(s.get("end") or 0))
    head = next(s for s in exo_sections if s.name == "exedit")
    head.set("length", str(max(1, length)))
    out[f"{sc['id']}.exo"] = serialize_ini(exo_sections, "\r\n").encode("cp932")
    return out


def merge_exo(base: list[Section], extra: list[Section], layer_offset: int, frame_offset: int) -> list[Section]:
    """base の後ろに extra のオブジェクトを番号を振り直して追加する（レイヤー・開始位置をずらす）。"""
    n = sum(1 for s in base if s.name.isdigit())
    mapping: dict[str, str] = {}
    out = list(base)
    for s in extra:
        if s.name == "exedit":
            continue
        head, _, sub = s.name.partition(".")
        if not head.isdigit():
            continue
        if head not in mapping:
            mapping[head] = str(n)
            n += 1
        new = Section(mapping[head] + (f".{sub}" if sub else ""), list(s.entries))
        if not sub:
            for key, off in (("start", frame_offset), ("end", frame_offset), ("layer", layer_offset)):
                v = new.get(key)
                if v is not None and v.lstrip("-").isdigit():
                    new.set(key, str(int(v) + off))
        out.append(new)
    return out


def write_shortcut(sc: dict[str, Any], cfg: Config, out_dir: str, fps: Fraction | None = None) -> list[str]:
    files = build_shortcut(sc, cfg, fps)
    paths = []
    for name, data in sorted(files.items()):
        p = os.path.join(out_dir, "shortcuts", name)
        write_bytes(p, data)
        paths.append(p)
    return paths


def find_shortcut(cfg: Config, sid: str) -> dict[str, Any]:
    for sc in cfg["shortcuts"]:
        if sc["id"] == sid:
            return sc
    ids = ", ".join(s["id"] for s in cfg["shortcuts"]) or "（なし）"
    raise DetCutError(f"ショートカット {sid!r} がプリセットにありません。定義済み: {ids}")
