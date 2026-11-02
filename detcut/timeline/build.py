"""カットリスト・テロップ・SE・BGM・ズームから中間表現（Timeline）を組み立てる。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from detcut.edit.bgm import BgmPiece
from detcut.edit.cutlist import CutList
from detcut.edit.rules_se import SEEvent
from detcut.edit.telop import Telop
from detcut.edit.zoom import VideoPiece
from detcut.media.probe import MediaInfo
from detcut.timebase import TimeBase
from detcut.timeline.model import Clip, SourceRange, Timeline, make_params


@dataclass(frozen=True)
class ChapterTitle:
    start: int
    end: int
    title: str


def build_timeline(
    *,
    input_path: str,
    media: MediaInfo,
    tb: TimeBase,
    width: int,
    height: int,
    cfg: dict[str, Any],
    cl: CutList,
    pieces: list[VideoPiece],
    telops: list[Telop],
    chapter_titles: list[ChapterTitle],
    se_events: list[SEEvent],
    bgm_pieces: list[BgmPiece],
    meta: dict[str, Any],
) -> tuple[Timeline, list[str]]:
    pr = cfg["project"]
    layers = cfg["layers"]
    zoom = cfg["zoom"]
    keeps = {k.index: k for k in cl.keeps}
    tl = Timeline(fps=tb.fps, width=width, height=height, audio_rate=int(pr["audio_rate"]),
                  audio_ch=int(pr["audio_ch"]), meta=meta)
    tl.styles = {"telop": dict(cfg["telop"]["style"]), "chapter": dict(cfg["chapters"]["style"])}

    for i, p in enumerate(pieces):
        k = keeps[p.keep_index]
        lv = zoom["levels"][p.level] if zoom["enabled"] else {"scale": 100, "x": 0, "y": 0}
        src = SourceRange(tb.frame_to_sample(p.src_start_frame), tb.frame_to_sample(p.src_start_frame + p.n_frames))
        seek = tb.frame_to_seconds(p.src_start_frame)
        reason = f"keep#{k.index} {k.rule}" + (f" zoom={lv['scale']}" if zoom["enabled"] else "") + (" split" if p.split else "")
        end = p.tl_start + p.n_frames - 1
        if media.has_video:
            tl.clips.append(Clip(
                id=f"v{i + 1:04d}", kind="video", layer=int(layers["video"]), tl_start=p.tl_start, tl_end=end,
                src=src, file=input_path, reason=reason, group=i + 1,
                params=make_params(seek=seek, src_frame=p.src_start_frame, source_fps=media.fps,
                                   has_audio=media.has_audio, scale=lv["scale"], x=lv["x"], y=lv["y"]),
            ))
        if media.has_audio:
            tl.clips.append(Clip(
                id=f"a{i + 1:04d}", kind="audio", layer=int(layers["audio"]), tl_start=p.tl_start, tl_end=end,
                src=src, file=input_path, reason=reason, group=i + 1 if media.has_video else 0,
                params=make_params(seek=seek, linked=media.has_video, volume=100),
            ))

    for n, t in enumerate(telops):
        tl.clips.append(Clip(
            id=f"t{n + 1:04d}", kind="text", layer=int(layers["telop"]), tl_start=t.start, tl_end=t.end,
            reason="F7" + ("".join(f" {x}" for x in t.notes)),
            params=make_params(text=t.text, style_id="telop", use_template=True),
        ))
    for n, c in enumerate(chapter_titles):
        tl.clips.append(Clip(
            id=f"c{n + 1:04d}", kind="text", layer=int(layers["chapter"]), tl_start=c.start, tl_end=c.end,
            reason="chapter", params=make_params(text=c.title, style_id="chapter", use_template=False),
        ))
    n = 0
    for ev in se_events:
        if not ev.accepted:
            continue
        n += 1
        tl.clips.append(Clip(
            id=f"s{n:04d}", kind="se", layer=ev.layer, tl_start=ev.frame, tl_end=ev.end, file=ev.file,
            reason=f"F10:{ev.rule_id} {ev.reason}", params=make_params(seek=Fraction(0), volume=ev.volume),
        ))
    bgm_file = cfg["bgm"]["file"]
    for n, b in enumerate(bgm_pieces):
        tl.clips.append(Clip(
            id=f"b{n + 1:04d}", kind="bgm", layer=int(layers["bgm"]), tl_start=b.start, tl_end=b.end,
            file=bgm_file, reason=f"F11 loop#{b.loop}",
            params=make_params(seek=b.seek, volume=b.vol_start,
                               volume_end=b.vol_end if b.vol_end != b.vol_start else None),
        ))
    return tl, check_overlaps(tl)


def check_overlaps(tl: Timeline) -> list[str]:
    warnings = []
    by_layer: dict[int, list[Clip]] = {}
    for c in tl.clips:
        by_layer.setdefault(c.layer, []).append(c)
    for layer in sorted(by_layer):
        cs = sorted(by_layer[layer], key=lambda c: (c.tl_start, c.id))
        for a, b in zip(cs, cs[1:]):
            if b.tl_start <= a.tl_end:
                warnings.append(
                    f"レイヤー{layer}で {a.id}({a.kind}) と {b.id}({b.kind}) が重なっています。layers や se.rules[].layer を見直してください")
                break
    return warnings
