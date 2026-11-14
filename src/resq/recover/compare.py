"""段（手法）どうしの回収結果の比較。

例: 自作の残骸スキャン（S3）と商用エンジン（COM1）を同じイメージで比べ、件数と差分を記録する
（P9 の完了条件「DMDE の結果と件数を比較し、差分を記録」）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import validate as V
from ..db import now
from ..hashing import sha256_file
from .manifest import Manifest, has_folder_info


def _load(case, stage: str) -> list[tuple[str, dict]]:
    out = []
    for p in sorted((case.dir / "stages").glob(f"img*/{stage}/manifest.json")):
        man = Manifest.read(p)
        for c in man.candidates:
            f = case.dir / c.stored
            if not f.is_file():
                continue
            r = V.validate(f, Path(c.orig_path).name if c.orig_path else None)
            if r.status in V.NOT_RECOVERED:
                continue
            out.append((sha256_file(f), {"path": c.orig_path, "folder": c.path_known or has_folder_info(c.orig_path),
                                         "status": r.status}))
    return out


def compare(case, a: str, b: str) -> dict:
    ra, rb = _load(case, a), _load(case, b)
    da = {h: v for h, v in ra}
    db_ = {h: v for h, v in rb}
    only_a = sorted(set(da) - set(db_))
    only_b = sorted(set(db_) - set(da))
    both = set(da) & set(db_)
    report = {
        "created_at": now(), "a": a, "b": b,
        "count": {a: len(da), b: len(db_), "both": len(both), f"only_{a}": len(only_a), f"only_{b}": len(only_b)},
        "with_folder": {a: sum(1 for v in da.values() if v["folder"]), b: sum(1 for v in db_.values() if v["folder"])},
        f"only_{a}": [da[h]["path"] or h[:12] for h in only_a],
        f"only_{b}": [db_[h]["path"] or h[:12] for h in only_b],
    }
    out = case.sub("stages") / f"compare_{a}_{b}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    case.db.add_event(case.id, "recover.compare", json.dumps(report["count"], ensure_ascii=False), 0)
    report["path"] = str(out)
    return report
