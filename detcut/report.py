"""レポート（F6）：すべてのカット・配置に「なぜそうしたか」を残す。"""

from __future__ import annotations

import csv
import io

from detcut.common import fmt_ms
from detcut.edit.bgm import BgmPiece
from detcut.edit.cutlist import CutList
from detcut.edit.rules_se import SEEvent
from detcut.edit.telop import TelopResult
from detcut.timeline.model import Timeline

HEADER = ["type", "id", "layer", "tl_start", "tl_end", "src_start", "src_end", "duration_ms", "rule", "detail"]


def build_report_csv(cl: CutList, telops: TelopResult | None, se_events: list[SEEvent],
                     bgm: list[BgmPiece], timeline: Timeline) -> bytes:
    tb = cl.tb
    sr = tb.sample_rate
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(HEADER)
    events = []
    for k in cl.keeps:
        events.append((k.src_start_frame, 0, [
            "keep", f"keep#{k.index}", "", k.tl_start_frame, k.tl_end_frame,
            fmt_ms(tb.frame_to_ms(k.src_start_frame)), fmt_ms(tb.frame_to_ms(k.src_end_frame)),
            tb.frame_to_ms(k.src_end_frame) - tb.frame_to_ms(k.src_start_frame), k.rule,
            f"speech {fmt_ms(k.src_start_sample * 1000 // sr)}-{fmt_ms(k.src_end_sample * 1000 // sr)}",
        ]))
    for c in cl.cuts:
        events.append((c.src_start_frame, 1, [
            "cut", f"cut#{c.index}", "", c.tl_frame, "",
            fmt_ms(tb.frame_to_ms(c.src_start_frame)), fmt_ms(tb.frame_to_ms(c.src_end_frame)),
            tb.frame_to_ms(c.src_end_frame) - tb.frame_to_ms(c.src_start_frame), c.rule, c.reason,
        ]))
    for _, _, row in sorted(events, key=lambda e: (e[0], e[1])):
        w.writerow(row)
    clips = {c.id: c for c in timeline.clips}
    for c in timeline.sorted_clips():
        if c.kind in ("text",):
            w.writerow(["telop" if c.id.startswith("t") else "chapter", c.id, c.layer, c.tl_start, c.tl_end, "", "",
                        tb.frame_to_ms(c.length), c.reason.split(" ")[0], c.p("text", "").replace("\n", "⏎")])
    if telops:
        for ms, text in telops.dropped:
            w.writerow(["telop_dropped", "", "", "", "", fmt_ms(ms), "", "", "F7", f"カット区間内の発話のため除外: {text}"])
    for ev in se_events:
        w.writerow(["se" if ev.accepted else "se_dropped", ev.rule_id, ev.layer, ev.frame, ev.end, "", "",
                    tb.frame_to_ms(ev.end - ev.frame + 1), "F10", f"{ev.reason} file={ev.file} {ev.note}".strip()])
    for i, b in enumerate(bgm):
        vol = f"{float(b.vol_start):g}" + (f"->{float(b.vol_end):g}" if b.vol_end != b.vol_start else "")
        w.writerow(["bgm", f"b{i + 1:04d}", clips[f"b{i + 1:04d}"].layer if f"b{i + 1:04d}" in clips else "",
                    b.start, b.end, "", "", tb.frame_to_ms(b.end - b.start + 1), "F11",
                    f"loop#{b.loop} seek={float(b.seek):.3f}s volume={vol}"])
    for c in timeline.sorted_clips():
        if c.kind == "video" and (c.p("scale", 100) != 100 or "split" in c.reason):
            w.writerow(["zoom", c.id, c.layer, c.tl_start, c.tl_end, "", "", tb.frame_to_ms(c.length), "F12",
                        f"scale={c.p('scale')} x={c.p('x')} y={c.p('y')}"])
    return buf.getvalue().encode("utf-8-sig")
