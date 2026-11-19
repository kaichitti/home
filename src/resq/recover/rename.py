"""S6 名前の付け直し（P10）。

PhotoRec（S5）が名前なしで回収したファイルの「イメージ内の位置」と、S3 の残骸から分かる
「元のファイルのデータ位置」を突き合わせ、一致したものに元の名前とパスを付ける。

照合のしかた:
  1. 完全一致   : 回収位置 == 残骸エントリのデータ先頭位置、かつサイズが 1 クラスタ以内で一致
  2. FAT32 上位ワード消失 : Windows は FAT32 で削除すると開始クラスタの上位 16 ビットを消す。
     回収位置のクラスタ番号の下位 16 ビットが、削除エントリの開始クラスタ（上位 0）と一致し、
     サイズも一致するものを対応づける（候補が 1 つに絞れたときだけ）
回収ファイルそのものは S5 のものを指す（コピーしない）。S8 で同じハッシュとして束ねられ、名前付きの版が採用される。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .manifest import Candidate, Manifest
from .remnants.common import VolumeGeometry


def _size_ok(carved: int, entry_size: int, cs: int) -> bool:
    return abs(carved - entry_size) <= cs


def run(case, image_id: int, s3_dir: Path, s5_manifest: Manifest, stage_dir: Path) -> Manifest:
    man = Manifest(stage="S6", image_id=image_id, method="名前の付け直し")
    rep_path = s3_dir / "remnants.json"
    if not rep_path.exists():
        man.info["note"] = "S3 の結果がないため実行しませんでした"
        man.write(stage_dir)
        return man
    rep = json.loads(rep_path.read_text(encoding="utf-8"))

    exact: dict[int, list[dict]] = defaultdict(list)
    lo16: dict[tuple[int, int], list[dict]] = defaultdict(list)
    geos: list[VolumeGeometry] = []
    for vol in rep["volumes"]:
        geo = VolumeGeometry(**vol["geometry"])
        geos.append(geo)
        for e in vol["entries"]:
            if e["is_dir"] or not e["size"]:
                continue
            e["_cs"] = geo.cluster_size
            if e.get("data_offset") is not None:
                exact[e["data_offset"]].append(e)
            if geo.fs == "fat32" and e["deleted"] and (e.get("meta") or {}).get("hi") == 0 and e["start_cluster"]:
                lo16[(geo.volume_offset, e["start_cluster"] & 0xFFFF)].append(e)

    renamed = 0
    for c in s5_manifest.candidates:
        if c.img_offset is None:
            continue
        f = case.dir / c.stored
        if not f.is_file():
            continue
        size = f.stat().st_size
        matches = [e for e in exact.get(c.img_offset, []) if _size_ok(size, e["size"], e["_cs"])]
        how = "exact"
        if not matches:
            for geo in geos:
                if geo.fs != "fat32":
                    continue
                cl = geo.cluster_at(c.img_offset)
                if cl is None or cl <= 0xFFFF:
                    continue
                matches += [e for e in lo16.get((geo.volume_offset, cl & 0xFFFF), [])
                            if _size_ok(size, e["size"], e["_cs"])]
            how = "fat32_hiword"
        paths = {m["path"] for m in matches}
        if len(paths) != 1:
            continue
        m = matches[0]
        man.candidates.append(Candidate(
            stored=c.stored, method="PhotoRec+名前復元", orig_path=m["path"], path_known=m["path_known"],
            deleted=m["deleted"], img_offset=c.img_offset,
            extra={"carved_name": Path(c.stored).name, "match": how, "fs": m["fs"]}))
        renamed += 1
    man.info["renamed"] = renamed
    man.write(stage_dir)
    return man
