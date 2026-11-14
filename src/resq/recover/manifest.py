"""段ごとの復旧候補リスト（manifest.json）。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Candidate:
    stored: str                 # 案件ディレクトリからの相対パス
    method: str                 # "TSK" / "PhotoRec" / "商用:DMDE" など
    orig_path: str | None = None  # 元のパス（分かる場合）
    path_known: bool = False    # フォルダ階層まで分かっているか
    deleted: bool | None = None
    img_offset: int | None = None
    volume_offset: int | None = None  # セクタ単位
    extra: dict = field(default_factory=dict)

    @property
    def named(self) -> bool:
        return bool(self.orig_path)


@dataclass
class Manifest:
    stage: str
    image_id: int | None
    method: str
    candidates: list[Candidate] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def write(self, stage_dir: Path) -> Path:
        p = stage_dir / "manifest.json"
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1))
        return p

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        d = json.loads(path.read_text())
        cands = [Candidate(**c) for c in d.pop("candidates", [])]
        return cls(candidates=cands, **d)
