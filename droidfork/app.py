"""コマンド間で共有する実行コンテキスト。テストでは各部品を偽物に差し替える。"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from .adb import Adb
from .config import Config
from .docker import Docker
from .hostcheck import HostProbe
from .store import Store
from .util import Console, DroidForkError, Runner, pick_free_port


def _default_ask(prompt: str) -> str | None:
    if not sys.stdin.isatty():
        return None
    try:
        return input(prompt)
    except EOFError:
        return None


@dataclass
class App:
    cfg: Config
    console: Console
    runner: Runner
    host: HostProbe = field(default_factory=HostProbe)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    ask: Callable[[str], "str | None"] = _default_ask
    free_port: Callable[[], int] = pick_free_port
    poll_interval: float = 3.0
    settle_seconds: float = 3.0   # 設定の書き込みを待つ時間（雛形の封印時）

    def __post_init__(self) -> None:
        self.docker = Docker(self.runner, self.cfg.docker)
        self.adb = Adb(self.runner, self.cfg.adb)
        self.store = Store(self.cfg)

    def confirm(self, prompt: str, assume_yes: bool) -> None:
        """取り消せない操作の前に確認する。対話できないときは --yes を求める。"""
        if assume_yes:
            return
        answer = self.ask(f"{prompt} [y/N]: ")
        if answer is None:
            raise DroidForkError("確認が必要な操作です。", hint="内容を確認のうえ --yes を付けて実行してください。")
        if answer.strip().lower() not in ("y", "yes"):
            raise DroidForkError("中止しました。")

    def use_memfd(self) -> bool:
        mode = self.cfg.use_memfd
        if mode == "true":
            return True
        if mode == "false":
            return False
        return not self.host.exists("/dev/ashmem")
