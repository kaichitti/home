"""スマホ吸い出し（P8）。

前提: 端末が起動し、持ち主がロックを解除できる状態（ロック解除・回避は請け負わない）。
手順の各段階で、持ち主本人が操作したことを確認するチェックを必須にしている。
吸い出した結果は案件の stages/img0/MOB<n>/ に置き、S8 の統合・一覧化にそのまま乗る。
"""
from __future__ import annotations

from pathlib import Path

from ..errors import ResqError


def require_confirmations(steps: list[str], confirmed: dict[str, bool]) -> None:
    missing = [s for s in steps if not confirmed.get(s)]
    if missing:
        raise ResqError("持ち主による操作の確認が済んでいません: " + " / ".join(missing))


def next_stage_dir(case) -> Path:
    base = case.sub("stages") / "img0"
    base.mkdir(parents=True, exist_ok=True)
    n = len(list(base.glob("MOB*"))) + 1
    d = base / f"MOB{n}"
    d.mkdir()
    return d
