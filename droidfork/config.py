"""設定と保存先パス。

保存先（DROIDFORK_HOME、既定は ~/.local/share/droidfork）:
    config.json            任意の設定（無くてもよい）
    templates/<名前>/      雛形の情報（template.json）と取り込んだAPK
    instances/<ID>.json    インスタンスの割り当て（ポート・識別子など）

雛形の共有層と各インスタンスの差分層は Docker のボリュームに置く（redroid.py の命名を参照）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Mapping

from .identity import is_valid_prop_value
from .util import DroidForkError

GPU_MODES = ("guest", "host", "auto")
MEMFD_MODES = ("auto", "true", "false")
IMAGE_VARIANTS = ("", "_64only")
LOOPBACK_BINDS = ("127.0.0.1", "::1", "localhost")


@dataclass
class Config:
    home: Path
    adb_port_base: int = 15555          # 5555〜5585 は adb がエミュレータとして自動検出するので避ける
    adb_port_count: int = 1000
    adb_bind: str = "127.0.0.1"         # 既定はローカルホストのみで待ち受け（企画書10章）
    image_repo: str = "redroid/redroid"
    image_variant: str = ""             # "_64only" で 32bit を省いた軽量イメージ（Android 12 以降）
    gpu_mode: str = "guest"             # guest = ソフト描画
    fps: int = 30
    use_memfd: str = "auto"             # auto: /dev/ashmem が無ければ memfd を使う
    base_readonly: bool = True          # 共有層を読み取り専用でマウントする
    boot_timeout: int = 300
    template_boot_timeout: int = 900
    manufacturer: str = "DroidFork"
    model: str = "DroidFork-Virtual"
    dns: list = field(default_factory=list)
    adb: str = "adb"
    docker: str = "docker"
    scrcpy: str = "scrcpy"

    @property
    def templates_dir(self) -> Path:
        return self.home / "templates"

    @property
    def instances_dir(self) -> Path:
        return self.home / "instances"

    @property
    def lock_path(self) -> Path:
        return self.home / "lock"

    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["home"] = str(self.home)
        return data


USER_KEYS = [f.name for f in fields(Config) if f.name != "home"]


def default_home(env: Mapping[str, str]) -> Path:
    if env.get("DROIDFORK_HOME"):
        return Path(env["DROIDFORK_HOME"]).expanduser()
    base = env.get("XDG_DATA_HOME") or os.path.join(
        env.get("HOME") or os.path.expanduser("~"), ".local", "share"
    )
    return Path(base).expanduser() / "droidfork"


def _type_ok(default: object, value: object) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return False


def load_config(home: str | Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    cfg = Config(home=Path(home).expanduser() if home else default_home(env))
    path = cfg.config_path
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DroidForkError(f"設定ファイルを読めません: {path}: {exc}") from None
        if not isinstance(data, dict):
            raise DroidForkError(f"設定ファイルの形式が正しくありません（JSONオブジェクトにしてください）: {path}")
        for key, value in data.items():
            if key not in USER_KEYS:
                raise DroidForkError(
                    f"設定ファイルに不明な項目があります: {key}",
                    hint="使える項目: " + ", ".join(USER_KEYS),
                )
            if key == "use_memfd" and isinstance(value, bool):
                value = "true" if value else "false"
            if not _type_ok(getattr(cfg, key), value):
                raise DroidForkError(f"設定 {key} の型が正しくありません: {value!r}")
            setattr(cfg, key, value)
    for key, name in (("adb", "DROIDFORK_ADB"), ("docker", "DROIDFORK_DOCKER"), ("scrcpy", "DROIDFORK_SCRCPY")):
        if env.get(name):
            setattr(cfg, key, env[name])
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    def bad(key: str, allowed: str) -> DroidForkError:
        return DroidForkError(f"設定 {key} の値が正しくありません: {getattr(cfg, key)!r}", hint=allowed)

    if cfg.gpu_mode not in GPU_MODES:
        raise bad("gpu_mode", "guest / host / auto のいずれかです。")
    if cfg.use_memfd not in MEMFD_MODES:
        raise bad("use_memfd", "auto / true / false のいずれかです。")
    if cfg.image_variant not in IMAGE_VARIANTS:
        raise bad("image_variant", '"" か "_64only" です。')
    for key in ("manufacturer", "model"):
        if not is_valid_prop_value(getattr(cfg, key)):
            raise bad(key, "英数字と「-」「_」「.」のみ、空白なし・64文字以内にしてください。")
    if not (1024 <= cfg.adb_port_base and cfg.adb_port_count >= 1 and cfg.adb_port_base + cfg.adb_port_count <= 65536):
        raise bad("adb_port_base", "1024〜65535 の範囲に収まるようにしてください。")
    if not (1 <= cfg.fps <= 120):
        raise bad("fps", "1〜120 にしてください。")
    for dns in cfg.dns:
        if not re.match(r"^[0-9A-Fa-f:.]+$", dns):
            raise DroidForkError(f"設定 dns の値が正しくありません: {dns!r}", hint="IPアドレスで指定してください。")
