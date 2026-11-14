"""雛形（テンプレート）とインスタンスの情報を JSON で保存する。"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, ContextManager

from .config import Config
from .redroid import Display
from .util import DroidForkError, file_lock, read_json, write_json

TEMPLATE_STATE_LABELS = {
    "captured": "取り込み済み（未作成）",
    "building": "作成中",
    "sealed": "作成済み",
    "failed": "作成失敗",
}


@dataclass
class PackageEntry:
    name: str
    files: list[str]
    version_name: str | None = None
    version_code: str | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None
    source: str = "device"  # device = 実機から取得 / local = 手元のAPKから追加


@dataclass
class Template:
    name: str
    state: str
    created_at: str
    android_version: str          # Redroid イメージのバージョン（例 "14.0.0"）
    android_sdk: int | None       # 実機の API レベル（表示用）
    display: Display
    locale: str | None = None
    timezone: str | None = None
    settings: dict[str, dict[str, str]] = field(default_factory=dict)
    packages: list[PackageEntry] = field(default_factory=list)
    # 表示用メモ（機種名など）。シリアル・IMEI などの識別子は保存しない（企画書8章）
    source: dict[str, Any] = field(default_factory=dict)
    image: str | None = None
    image_id: str | None = None
    built_at: str | None = None
    install_results: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def sealed(self) -> bool:
        return self.state == "sealed"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["display"] = self.display.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Template":
        d = dict(data)
        d["display"] = Display.from_dict(d["display"])
        d["packages"] = [PackageEntry(**p) for p in d.get("packages", [])]
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Instance:
    id: str
    template: str
    index: int
    adb_port: int
    serialno: str
    mac: str
    display: Display
    created_at: str
    last_started_at: str | None = None
    last_boot_seconds: float | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["display"] = self.display.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Instance":
        d = dict(data)
        d["display"] = Display.from_dict(d["display"])
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


class Store:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def lock(self) -> ContextManager[None]:
        return file_lock(self.cfg.lock_path)

    # ---- テンプレート ----

    def template_dir(self, name: str) -> Path:
        return self.cfg.templates_dir / name

    def template_file(self, name: str) -> Path:
        return self.template_dir(name) / "template.json"

    def apk_dir(self, name: str) -> Path:
        return self.template_dir(name) / "apks"

    def template_exists(self, name: str) -> bool:
        return self.template_file(name).exists()

    def load_template(self, name: str) -> Template:
        path = self.template_file(name)
        if not path.exists():
            raise DroidForkError(
                f"テンプレート「{name}」が見つかりません。",
                hint="`droidfork template list` で一覧を確認できます。",
            )
        return Template.from_dict(read_json(path))

    def save_template(self, template: Template) -> None:
        write_json(self.template_file(template.name), template.to_dict())

    def list_templates(self) -> list[Template]:
        root = self.cfg.templates_dir
        if not root.exists():
            return []
        return [
            Template.from_dict(read_json(p / "template.json"))
            for p in sorted(root.iterdir())
            if not p.name.startswith(".") and (p / "template.json").exists()
        ]

    def remove_template_files(self, name: str) -> None:
        shutil.rmtree(self.template_dir(name), ignore_errors=True)

    # ---- インスタンス ----

    def instance_file(self, instance_id: str) -> Path:
        return self.cfg.instances_dir / f"{instance_id}.json"

    def load_instance(self, instance_id: str) -> Instance:
        path = self.instance_file(instance_id)
        if not path.exists():
            raise DroidForkError(
                f"インスタンス「{instance_id}」が見つかりません。",
                hint="`droidfork list` で一覧を確認できます。",
            )
        return Instance.from_dict(read_json(path))

    def save_instance(self, instance: Instance) -> None:
        write_json(self.instance_file(instance.id), instance.to_dict())

    def list_instances(self, template: str | None = None) -> list[Instance]:
        root = self.cfg.instances_dir
        if not root.exists():
            return []
        items = [Instance.from_dict(read_json(p)) for p in root.glob("*.json") if not p.name.startswith(".")]
        if template is not None:
            items = [i for i in items if i.template == template]
        return sorted(items, key=lambda i: (i.template, i.index))

    def remove_instance_file(self, instance_id: str) -> None:
        self.instance_file(instance_id).unlink(missing_ok=True)
