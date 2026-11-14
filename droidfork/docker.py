"""docker コマンドの薄いラッパー。"""

from __future__ import annotations

import json
from typing import Sequence

from .util import CommandResult, DroidForkError, Runner, parse_size


class Docker:
    def __init__(self, runner: Runner, binary: str = "docker") -> None:
        self.runner = runner
        self.binary = binary

    def cmd(self, *args: object, check: bool = True, timeout: float | None = 120) -> CommandResult:
        return self.runner.run([self.binary, *args], check=check, timeout=timeout)

    # ---- デーモン ----

    def server_version(self) -> str | None:
        try:
            r = self.cmd("version", "--format", "{{.Server.Version}}", check=False, timeout=30)
        except DroidForkError:
            return None
        version = r.stdout.strip()
        return version if r.ok and version else None

    def ensure_daemon(self) -> None:
        if self.server_version() is None:
            raise DroidForkError(
                "Docker デーモンに接続できません。",
                hint="Docker を起動し（sudo systemctl start docker）、このユーザーで docker コマンドが"
                     "使えることを確認してください（docker グループへの追加など）。",
            )

    def root_dir(self) -> str | None:
        r = self.cmd("info", "--format", "{{.DockerRootDir}}", check=False, timeout=30)
        return r.stdout.strip() or None if r.ok else None

    # ---- イメージ ----

    def image_id(self, ref: str) -> str | None:
        r = self.cmd("image", "inspect", "--format", "{{.Id}}", ref, check=False, timeout=30)
        return (r.stdout.strip() or None) if r.ok else None

    def image_size(self, ref: str) -> int | None:
        r = self.cmd("image", "inspect", "--format", "{{.Size}}", ref, check=False, timeout=30)
        try:
            return int(r.stdout.strip()) if r.ok else None
        except ValueError:
            return None

    def pull(self, ref: str) -> None:
        self.cmd("pull", ref, timeout=None)

    # ---- ボリューム ----

    def volume_exists(self, name: str) -> bool:
        return self.cmd("volume", "inspect", name, check=False, timeout=30).ok

    def volume_create(self, name: str, labels: dict[str, str] | None = None) -> None:
        args: list[str] = ["volume", "create"]
        for key, value in (labels or {}).items():
            args += ["--label", f"{key}={value}"]
        args.append(name)
        self.cmd(*args, timeout=60)

    def volume_rm(self, name: str) -> None:
        if self.volume_exists(name):
            self.cmd("volume", "rm", name, timeout=300)

    def volume_sizes(self) -> dict[str, int]:
        """ボリュームごとの使用量（バイト）。差分層の実サイズ＝1台あたりのディスク増分。"""
        r = self.cmd("system", "df", "-v", "--format", "{{json .}}", check=False, timeout=600)
        sizes: dict[str, int] = {}
        if not r.ok:
            return sizes
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            volumes = data.get("Volumes") if isinstance(data, dict) else None
            if not isinstance(volumes, list):
                continue
            for v in volumes:
                if not isinstance(v, dict):
                    continue
                size = parse_size(str(v.get("Size", "")))
                if v.get("Name") and size is not None:
                    sizes[str(v["Name"])] = size
        return sizes

    # ---- コンテナ ----

    def run(self, args: Sequence[str]) -> str:
        return self.cmd(*args, timeout=600).stdout.strip()

    def container_status(self, name: str) -> str | None:
        r = self.cmd("inspect", "--type", "container", "--format", "{{.State.Status}}", name,
                     check=False, timeout=30)
        return (r.stdout.strip() or None) if r.ok else None

    def containers(self, label: str) -> dict[str, str]:
        """ラベルで絞り込んだコンテナ名 → 状態（running / exited など）。"""
        r = self.cmd("ps", "-a", "--filter", f"label={label}", "--format", "{{.Names}}\t{{.State}}", timeout=30)
        result = {}
        for line in r.stdout.splitlines():
            name, _, state = line.partition("\t")
            if name.strip():
                result[name.strip()] = state.strip()
        return result

    def stop(self, names: Sequence[str], timeout: int = 15) -> None:
        if names:
            self.cmd("stop", "-t", str(timeout), *names, check=False, timeout=timeout + 120)

    def remove(self, names: Sequence[str]) -> None:
        if names:
            self.cmd("rm", "-f", *names, check=False, timeout=120)

    def logs_tail(self, name: str, lines: int = 30) -> str:
        r = self.cmd("logs", "--tail", str(lines), name, check=False, timeout=30)
        return r.output.strip()

    def stats(self, names: Sequence[str]) -> dict[str, dict[str, object]]:
        if not names:
            return {}
        r = self.cmd("stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}", *names,
                     check=False, timeout=120)
        result: dict[str, dict[str, object]] = {}
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            used = parts[1].split("/")[0].strip()
            result[parts[0].strip()] = {"mem": parse_size(used), "cpu": parts[2].strip()}
        return result
