"""adb コマンドの薄いラッパーと、出力のパーサー。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .util import CommandResult, DroidForkError, Runner


@dataclass
class AdbDevice:
    serial: str
    state: str
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def is_emulator(self) -> bool:
        return self.serial.startswith("emulator-")

    @property
    def is_usb(self) -> bool:
        return "usb" in self.attrs

    @property
    def is_local_tcp(self) -> bool:
        return self.serial.startswith(("127.0.0.1:", "localhost:", "[::1]:"))

    @property
    def model(self) -> str:
        return self.attrs.get("model", "").replace("_", " ")


_ATTR_RE = re.compile(r"^(usb|product|model|device|transport_id):(.+)$")
_PROP_RE = re.compile(r"^\[([^\]]+)\]: \[(.*)\]$")


def parse_devices(text: str) -> list[AdbDevice]:
    devices = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state, rest = parts[0], parts[1], parts[2:]
        if state == "no" and rest[:1] == ["permissions"]:
            state = "no permissions"
        attrs = {}
        for token in rest:
            m = _ATTR_RE.match(token)
            if m:
                attrs[m.group(1)] = m.group(2)
        devices.append(AdbDevice(serial, state, attrs))
    return devices


def parse_getprop(text: str) -> dict[str, str]:
    props = {}
    for line in text.splitlines():
        m = _PROP_RE.match(line.strip())
        if m:
            props[m.group(1)] = m.group(2)
    return props


def parse_wm(text: str) -> tuple[str | None, str | None]:
    """`wm size` / `wm density` の出力から（Physical, Override）を取り出す。"""
    physical = override = None
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        if key.startswith("physical"):
            physical = value.strip()
        elif key.startswith("override"):
            override = value.strip()
    return physical, override


def parse_resolution(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    m = re.match(r"^(\d+)\s*x\s*(\d+)$", value.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    m = re.match(r"^\s*(\d+)\s*$", value)
    return int(m.group(1)) if m else None


def parse_package_list(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            value = line[len("package:"):]
            names.append(value.rsplit("=", 1)[-1] if "=" in value else value)
    return sorted(set(names))


def parse_pm_paths(text: str) -> list[str]:
    return [line.strip()[len("package:"):] for line in text.splitlines() if line.strip().startswith("package:")]


def parse_package_info(text: str) -> dict[str, object]:
    def find(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None

    min_sdk = find(r"\bminSdk=(\d+)")
    target_sdk = find(r"\btargetSdk=(\d+)")
    return {
        "version_name": find(r"\bversionName=(\S+)"),
        "version_code": find(r"\bversionCode=(\d+)"),
        "min_sdk": int(min_sdk) if min_sdk else None,
        "target_sdk": int(target_sdk) if target_sdk else None,
    }


def install_outcome(result: CommandResult) -> tuple[bool, str]:
    text = result.output
    m = re.search(r"Failure \[([^\]]+)\]", text)
    if m:
        return False, m.group(1).strip()
    if re.search(r"^Success\s*$", text, re.M):
        return True, "Success"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return False, lines[-1] if lines else f"終了コード {result.returncode}"


class Adb:
    def __init__(self, runner: Runner, binary: str = "adb") -> None:
        self.runner = runner
        self.binary = binary

    def cmd(self, *args: object, serial: str | None = None, check: bool = True,
            timeout: float | None = 60) -> CommandResult:
        argv: list[object] = [self.binary]
        if serial:
            argv += ["-s", serial]
        argv += list(args)
        return self.runner.run(argv, check=check, timeout=timeout)

    def version(self) -> str | None:
        try:
            r = self.cmd("version", check=False, timeout=15)
        except DroidForkError:
            return None
        if not r.ok:
            return None
        lines = r.stdout.strip().splitlines()
        return lines[0] if lines else "不明"

    def devices(self) -> list[AdbDevice]:
        return parse_devices(self.cmd("devices", "-l", timeout=30).stdout)

    def connect(self, addr: str) -> bool:
        r = self.cmd("connect", addr, check=False, timeout=20)
        text = r.output.lower()
        return "connected to" in text and not any(w in text for w in ("failed", "cannot", "unable"))

    def disconnect(self, addr: str) -> None:
        self.cmd("disconnect", addr, check=False, timeout=20)

    def shell(self, serial: str, command: str, *, check: bool = True, timeout: float | None = 60) -> str:
        return self.cmd("shell", command, serial=serial, check=check, timeout=timeout).stdout

    def getprops(self, serial: str) -> dict[str, str]:
        return parse_getprop(self.shell(serial, "getprop"))

    def getprop(self, serial: str, key: str) -> str:
        return self.shell(serial, f"getprop {key}", check=False, timeout=15).strip()

    def pull(self, serial: str, remote: str, local: Path) -> None:
        self.cmd("pull", remote, str(local), serial=serial, timeout=None)

    def install(self, serial: str, apks: Sequence[str | Path], extra: Sequence[str] = ()) -> tuple[bool, str]:
        verb = "install-multiple" if len(apks) > 1 else "install"
        r = self.cmd(verb, "-r", *extra, *[str(a) for a in apks], serial=serial, check=False, timeout=900)
        return install_outcome(r)

    def root(self, serial: str) -> CommandResult:
        return self.cmd("root", serial=serial, check=False, timeout=30)
