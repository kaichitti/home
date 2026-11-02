"""SE自動挿入（F10）。

ルール:
  keyword   テロップの文字列が正規表現に一致したら、その文字のフレーム（またはテロップ先頭）に配置
  after_cut 一定以上の長さのカットの直後（編集点）に配置
  chapter   章マーカーの位置に配置
候補が重なったら「優先度（大きい方）→ 時刻 → ルール定義順」で採用し、乱択はしない。
複数ファイルから選ぶときは pick: first（ファイル名の昇順で先頭）または
pick: hash（SHA-256(ルールID:フレーム) mod 候補数 = 決定論的な「ランダム感」）。
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable

from detcut.common import stable_int_hash
from detcut.edit.cutlist import CutList
from detcut.edit.snap import boundary_points, snap_frame
from detcut.edit.telop import Telop
from detcut.timebase import TimeBase

AUDIO_EXT = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus")


@dataclass
class SEEvent:
    rule_id: str
    frame: int
    end: int          # 含む
    file: str
    layer: int
    volume: Any
    priority: int
    order: int
    reason: str
    accepted: bool = True
    note: str = ""


def rule_files(rule: dict[str, Any], warnings: list[str]) -> list[str]:
    files: list[str] = []
    if rule.get("file"):
        files.append(rule["file"])
    files.extend(rule.get("files") or [])
    if rule.get("dir"):
        for ext in AUDIO_EXT:
            files.extend(glob.glob(os.path.join(glob.escape(rule["dir"]), "*" + ext)))
    uniq = sorted(set(os.path.normpath(f) for f in files), key=lambda p: (os.path.basename(p).lower(), p))
    exist = [f for f in uniq if os.path.isfile(f)]
    for f in uniq:
        if f not in exist:
            warnings.append(f"SEファイルが見つかりません（ルール {rule['id']}）: {f}")
    return exist


def build_se(
    se_cfg: dict[str, Any],
    telops: list[Telop],
    cl: CutList,
    chapter_frames: list[int],
    tb: TimeBase,
    duration_fn: Callable[[str], Fraction | None],
    warnings: list[str],
) -> list[SEEvent]:
    total = cl.total_tl_frames
    if total <= 0:
        return []
    points = boundary_points(cl.edit_points, total)
    tol = int(se_cfg["snap_to_cut_frames"])
    dur_cache: dict[str, int] = {}

    def length_of(f: str, rule: dict[str, Any]) -> int:
        if f not in dur_cache:
            d = duration_fn(f)
            if d is None or d <= 0:
                ms = rule.get("duration_ms") or 1000
                warnings.append(f"SEの長さを取得できません（{ms}ms として配置）: {f}")
                dur_cache[f] = max(1, tb.ms_to_frames_ceil(int(ms)))
            else:
                dur_cache[f] = max(1, tb.seconds_to_frames_ceil(d))
        return dur_cache[f]

    candidates: list[SEEvent] = []
    for order, rule in enumerate(se_cfg["rules"]):
        if not rule["enabled"]:
            continue
        files = rule_files(rule, warnings)
        if not files:
            warnings.append(f"SEルール {rule['id']} に使えるファイルがないためスキップしました")
            continue
        raw: list[tuple[int, str]] = []
        if rule["type"] == "keyword":
            rx = re.compile(rule["pattern"])
            for t in telops:
                n = 0
                for m in rx.finditer(t.flat):
                    if m.end() <= m.start():
                        continue
                    f = t.char_frames[m.start()] if rule["anchor"] == "match" else t.start
                    raw.append((max(t.start, min(f, t.end)), f"keyword '{m.group(0)}' telop#{t.index}"))
                    n += 1
                    if n >= rule["max_per_telop"]:
                        break
        elif rule["type"] == "after_cut":
            for c in cl.cuts:
                if c.src_start_frame == 0 or c.src_end_frame >= cl.total_src_frames:
                    continue  # 先頭・末尾の無音は対象外
                dur_ms = (c.src_end_sample - c.src_start_sample) * 1000 // cl.tb.sample_rate
                if dur_ms >= rule["min_cut_ms"]:
                    raw.append((c.tl_frame, f"after_cut {dur_ms}ms"))
        elif rule["type"] == "chapter":
            for i, f in enumerate(chapter_frames):
                raw.append((f, f"chapter#{i}"))

        off = tb.ms_to_frames_round(abs(int(rule["offset_ms"]))) * (1 if rule["offset_ms"] >= 0 else -1)
        interval = tb.ms_to_frames_ceil(int(rule["min_interval_ms"]))
        last: int | None = None
        for f, why in sorted(raw):
            f2 = snap_frame(max(0, f + off), points, tol)
            if f2 >= total:
                continue
            if last is not None and f2 - last < interval:
                continue
            last = f2
            if rule["pick"] == "hash":
                file = files[stable_int_hash(f"{rule['id']}:{f2}") % len(files)]
            else:
                file = files[0]
            n = length_of(file, rule)
            candidates.append(SEEvent(
                rule_id=rule["id"], frame=f2, end=min(total - 1, f2 + n - 1), file=file,
                layer=int(rule["layer"]), volume=rule["volume"], priority=int(rule["priority"]),
                order=order, reason=why + (f" snap {f + off}->{f2}" if f2 != max(0, f + off) else ""),
            ))

    # 重なりの解決（同じレイヤーでは重ねない・全体の最小間隔）
    gap = tb.ms_to_frames_ceil(int(se_cfg.get("min_gap_ms", 0)))
    accepted: list[SEEvent] = []
    for ev in sorted(candidates, key=lambda e: (-e.priority, e.frame, e.order)):
        clash = next((a for a in accepted if a.layer == ev.layer and not (ev.end < a.frame or ev.frame > a.end)), None)
        if clash is None and gap > 0:
            clash = next((a for a in accepted if abs(a.frame - ev.frame) < gap), None)
        if clash is not None:
            ev.accepted = False
            ev.note = f"dropped: {clash.rule_id}@{clash.frame} と重なり"
        else:
            accepted.append(ev)
    return sorted(candidates, key=lambda e: (e.layer, e.frame, e.order))
