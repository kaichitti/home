"""S4 シャドウコピー（Windows の復元ポイント等、libvshadow）。

NTFS ボリュームにボリュームシャドウコピー（VSS）があれば、各ストアを読み取り専用で展開し、
S2 と同じ処理（TSK）にかけて旧版を回収する。

  vshadowinfo -o <バイトオフセット> <イメージ>         ストア数の確認
  vshadowmount -o <バイトオフセット> <イメージ> <dir>  dir/vss1, vss2 … にストアを読み取り専用で展開（FUSE）
  fusermount -u <dir>                                  展開の解除

FUSE が使える作業機で実行する。開発機では「ストアなし」の判定とコマンド生成までをテストする。
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import audit
from ..errors import CommandError
from . import tsk
from .manifest import Manifest

STORES_RE = re.compile(r"Number of stores:\s*(\d+)")
NO_STORES = "No Volume Shadow Snapshots found"


def parse_info(text: str) -> int:
    if NO_STORES in text:
        return 0
    m = STORES_RE.search(text)
    return int(m.group(1)) if m else 0


def mount_commands(image: Path, offset_bytes: int, mnt: Path) -> tuple[list[str], list[str]]:
    return (["vshadowmount", "-o", str(offset_bytes), str(image), str(mnt)],
            ["fusermount", "-u", str(mnt)])


def run(case, image_id: int, image: Path, volumes: list[dict], stage_dir: Path) -> Manifest:
    man = Manifest(stage="S4", image_id=image_id, method="VSS")
    for vol in volumes:
        if vol.get("fstype", "").lower() != "ntfs":
            continue
        off_b = vol["offset"] * 512
        try:
            r = audit.run(["vshadowinfo", "-o", str(off_b), image], op="recover.S4.info", ctx=case.ctx,
                          check=False)
        except CommandError as e:
            man.info["note"] = str(e)
            break
        n = parse_info(r.stdout + r.stderr)
        man.info[f"vol{vol['offset']}_stores"] = n
        if n == 0:
            continue
        mnt = stage_dir / f"mnt{vol['offset']}"
        mnt.mkdir(parents=True, exist_ok=True)
        mount, umount = mount_commands(image, off_b, mnt)
        audit.run(mount, op="recover.S4.mount", ctx=case.ctx)
        try:
            for i in range(1, n + 1):
                store = mnt / f"vss{i}"
                if not store.exists():
                    continue
                man.candidates += tsk.extract(case, store, [{"offset": 0, "fstype": "ntfs"}],
                                              stage_dir / f"vol{vol['offset']}" / f"vss{i}",
                                              method=f"VSS{i}", op="recover.S4")
        finally:
            audit.run(umount, op="recover.S4.umount", ctx=case.ctx, check=False)
    man.write(stage_dir)
    return man
