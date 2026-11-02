"""編集点吸着（F9）：テロップやSEの端を、近くのカット編集点（しきい値フレーム以内）に吸着させる。"""

from __future__ import annotations

import bisect


def snap_frame(f: int, points: list[int], tolerance: int) -> int:
    """points（昇順）のうち f に最も近い点が tolerance 以内ならその点を返す。同距離なら早い方。"""
    if tolerance <= 0 or not points:
        return f
    i = bisect.bisect_left(points, f)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(points):
            d = abs(points[j] - f)
            if d <= tolerance and (best is None or d < best[0]):
                best = (d, points[j])
    return best[1] if best else f


def boundary_points(edit_points: list[int], total_frames: int) -> list[int]:
    return sorted(set([0, *edit_points, total_frames]))
