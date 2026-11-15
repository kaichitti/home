"""外部ツールの所在の解決（Linux / Windows 共通）。

Windows 版の TestDisk / PhotoRec は testdisk_win.exe / photorec_win.exe という名前で配布されるため、
別名も探す。見つからないツールを使う段は、パイプラインで「未インストールのため省略」として記録する。
"""
from __future__ import annotations

import shutil

ALIASES: dict[str, tuple[str, ...]] = {
    "photorec": ("photorec", "photorec_win"),
    "testdisk": ("testdisk", "testdisk_win"),
    "fusermount": ("fusermount", "fusermount3"),   # Ubuntu 24.04 は fuse3
}

# 段ごとに必要なツール
STAGE_TOOLS: dict[str, tuple[str, ...]] = {
    "S2": ("fls", "icat"),
    "S4": ("vshadowinfo", "vshadowmount", "fusermount"),
    "S5": ("photorec",),
}


def resolve(name: str) -> str:
    """実行に使う名前を返す。見つからなければ元の名前（実行時に『見つかりません』になる）。"""
    for cand in ALIASES.get(name, (name,)):
        if shutil.which(cand):
            return cand
    return name


def available(name: str) -> bool:
    return any(shutil.which(c) for c in ALIASES.get(name, (name,)))


def missing_for_stage(stage: str) -> list[str]:
    return [t for t in STAGE_TOOLS.get(stage, ()) if not available(t)]
