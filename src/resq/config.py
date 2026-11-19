"""作業領域（ワークスペース）の場所と案件ディレクトリの配置。

RESQ_HOME 環境変数で作業領域のルートを指定する（既定: ./resq-data）。
本番では案件ごとの暗号化コンテナ（LUKS）をこの配下にマウントする想定（P5）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    root: Path

    @classmethod
    def from_env(cls) -> "Workspace":
        return cls(Path(os.environ.get("RESQ_HOME", "resq-data")).resolve())

    @property
    def db_path(self) -> Path:
        return self.root / "resq.db"

    @property
    def log_path(self) -> Path:
        return self.root / "logs" / "audit.jsonl"

    def case_dir(self, case_id: str) -> Path:
        return self.root / "cases" / case_id

    def ensure(self) -> "Workspace":
        (self.root / "cases").mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(parents=True, exist_ok=True)
        return self


CASE_SUBDIRS = ("images", "stages", "catalog", "logs", "deliver")
