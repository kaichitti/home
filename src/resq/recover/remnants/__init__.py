"""S3 管理情報の残骸からの再構築（P9）。

S1 で見つけた各ボリュームについて、FS 別のスキャナで残骸を集め、フォルダツリーを再構築して取り出す。
全エントリ（中身を取り出せなかったものも含む）とボリュームの幾何情報を remnants.json に保存する。
S6（名前の付け直し）はこの情報を使う。
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ... import safety
from ..manifest import Candidate, Manifest
from . import common, exfat, fat, ntfs

SCANNERS = {"fat12": fat, "fat16": fat, "fat32": fat, "fat": fat, "exfat": exfat, "ntfs": ntfs}
MAX_EXTRACT = 64 * 1024 ** 3


def scan_volume(image: Path, vol: dict):
    mod = SCANNERS.get(vol.get("fstype", "").lower())
    if mod is None:
        return None
    return mod.scan(image, vol["offset"] * 512)


def run(case, image_id: int, image: Path, volumes: list[dict], stage_dir: Path) -> Manifest:
    man = Manifest(stage="S3", image_id=image_id, method="残骸スキャン")
    report = {"volumes": []}
    for vol in volumes:
        res = scan_volume(image, vol)
        if res is None:
            continue
        geo, entries, roots = res
        entries = common.dedupe(entries)
        paths = common.build_paths(entries, roots)
        vdir = stage_dir / f"vol{vol['offset']}"
        vrep = {"offset": vol["offset"], "geometry": asdict(geo), "entries": []}
        for e in entries:
            parts, known = paths[id(e)]
            ej = e.to_json()
            ej["path"] = "/".join(parts)
            ej["path_known"] = known
            vrep["entries"].append(ej)
            if e.is_dir or not e.size or e.size > MAX_EXTRACT:
                continue
            dest = safety.safe_join(vdir, *parts)
            n = 1
            while dest.exists():
                dest = dest.with_name(f"{Path(parts[-1]).stem}~{n}{Path(parts[-1]).suffix}")
                n += 1
            safety.assert_writable_target(dest, case_dir=case.dir, source=image)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(common.read_runs(image, e))
            ej["stored"] = str(dest.relative_to(case.dir))
            man.candidates.append(Candidate(
                stored=ej["stored"], method=f"残骸:{geo.fs}", orig_path="/".join(parts), path_known=known,
                deleted=e.deleted, img_offset=e.data_offset, volume_offset=vol["offset"],
                extra={"fs": geo.fs, "start_cluster": e.start_cluster, **e.meta}))
        report["volumes"].append(vrep)
    (stage_dir / "remnants.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    man.write(stage_dir)
    return man
