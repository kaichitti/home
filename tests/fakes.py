"""テスト用の偽物: adb と docker、実機、Redroid コンテナをメモリ上で模擬する。

本物の Redroid はカーネルの binder が必要で CI では動かせないため、
コマンドの組み立てと手順（取り込み→雛形→複製→起動→リセット）をこの偽物で検証する。

コンテナの /data は「キー → 値」の辞書で表し、インスタンスは
共有層（下）＋差分層（上）を重ねて読む。差分層の値 None は削除（ホワイトアウト）を表す。
"""

from __future__ import annotations

import hashlib
import io
import json
import secrets
import shlex
import threading
from pathlib import Path

from droidfork.app import App
from droidfork.config import load_config
from droidfork.util import CommandError, CommandResult, Console

SSAID_FILE = "file:/data/system/users/0/settings_ssaid.xml"
IMAGE_REF = "redroid/redroid:14.0.0-latest"
IMAGE_ID = "sha256:" + "a" * 64


class FakePhone:
    serial = "R5CT10ABCDE"

    def __init__(self) -> None:
        self.state = "device"
        self.props = {
            "ro.build.version.release": "14",
            "ro.build.version.sdk": "34",
            "ro.product.model": "SM-S911C",
            "ro.product.manufacturer": "samsung",
            "ro.product.cpu.abi": "arm64-v8a",
            "ro.serialno": self.serial,
            "persist.sys.locale": "ja-JP",
            "persist.sys.timezone": "Asia/Tokyo",
        }
        self.wm_size = "Physical size: 1080x2340\n"
        self.wm_density = "Physical density: 450\nOverride density: 420\n"
        self.settings = {"system": {"font_scale": "1.1", "time_12_24": "24"}}
        self.packages = {
            "com.example.shop": ["/data/app/~~a1==/com.example.shop-b2==/base.apk"],
            "com.example.split": [
                "/data/app/~~c3==/com.example.split-d4==/base.apk",
                "/data/app/~~c3==/com.example.split-d4==/split_config.arm64_v8a.apk",
                "/data/app/~~c3==/com.example.split-d4==/split_config.ja.apk",
            ],
            "com.example.armonly": ["/data/app/~~e5==/com.example.armonly-f6==/base.apk"],
            "jp.co.sample.tool": ["/data/app/~~g7==/jp.co.sample.tool-h8==/base.apk"],
        }

    def shell(self, command: str) -> tuple[int, str, str]:
        t = shlex.split(command)
        if command == "getprop":
            return 0, "".join(f"[{k}]: [{v}]\n" for k, v in self.props.items()), ""
        if t[0] == "getprop":
            return 0, self.props.get(t[1], "") + "\n", ""
        if command == "wm size":
            return 0, self.wm_size, ""
        if command == "wm density":
            return 0, self.wm_density, ""
        if t[:2] == ["settings", "get"]:
            return 0, self.settings.get(t[2], {}).get(t[3], "null") + "\n", ""
        if command == "pm list packages -3":
            return 0, "".join(f"package:{p}\n" for p in self.packages), ""
        if t[:2] == ["pm", "path"]:
            return 0, "".join(f"package:{p}\n" for p in self.packages.get(t[2], [])), ""
        if t[:2] == ["dumpsys", "package"]:
            return 0, (f"Packages:\n  Package [{t[2]}]\n    versionCode=42 minSdk=26 targetSdk=34\n"
                       "    versionName=1.2.3\n"), ""
        return 127, "", f"/system/bin/sh: {command}: not found"


class FakeContainer:
    def __init__(self, world: "FakeWorld", name: str, image: str, labels: dict, bind: str, port: int,
                 mounts: list, mac: str | None, boot_args: list[str]) -> None:
        self.world = world
        self.name = name
        self.image = image
        self.labels = labels
        self.bind = bind
        self.port = port
        self.mounts = mounts
        self.mac = mac
        self.boot_args = boot_args
        self.boot = dict(a.split("=", 1) for a in boot_args)
        self.state = "running"
        self.polls = 0
        self.framework = True
        self.root = self.boot.get("ro.secure") == "0"
        targets = {target: (vol, ro) for vol, target, ro in mounts}
        if "/data" in targets:
            self.lower = None
            self.upper = world.volumes[targets["/data"][0]]["data"]
        else:
            assert self.boot.get("androidboot.use_redroid_overlayfs") == "1", "overlay の指定がない"
            self.lower = world.volumes[targets["/data-base"][0]]["data"]
            self.upper = world.volumes[targets["/data-diff"][0]]["data"]
            self.base_readonly = targets["/data-base"][1]
        # 初回起動: Android ID と SSAID の鍵が無ければ Android 自身が作る
        if self.get("settings/secure/android_id") is None:
            self.set("settings/secure/android_id", secrets.token_hex(8))
        if self.get(SSAID_FILE) is None:
            self.set(SSAID_FILE, secrets.token_hex(16))
        self.set("file:/data/system/entropy.dat", secrets.token_hex(4))

    # 重ね合わせた /data の読み書き
    def get(self, key: str):
        if key in self.upper:
            return self.upper[key]
        return self.lower.get(key) if self.lower is not None else None

    def set(self, key: str, value) -> None:
        self.upper[key] = value

    def delete(self, key: str) -> None:
        if self.lower is not None and key in self.lower:
            self.upper[key] = None
        else:
            self.upper.pop(key, None)

    def keys(self) -> set[str]:
        merged = dict(self.lower or {})
        merged.update(self.upper)
        return {k for k, v in merged.items() if v is not None}

    @property
    def addr(self) -> str:
        return f"127.0.0.1:{self.port}"

    def shell(self, command: str) -> tuple[int, str, str]:
        t = shlex.split(command)
        if command == "getprop sys.boot_completed":
            self.polls += 1
            return 0, ("1\n" if self.polls >= self.world.boot_polls else "\n"), ""
        if t[0] == "getprop" and len(t) == 2:
            key = t[1]
            if key == "ro.serialno":
                value = self.boot.get("ro.serialno") or self.boot.get("androidboot.serialno", "")
            elif key.startswith("persist."):
                value = self.get(f"prop/{key}") or ""
            else:
                value = self.boot.get(key, "")
            return 0, value + "\n", ""
        if command == "id -u":
            return 0, ("0\n" if self.root else "2000\n"), ""
        if t[0] == "setprop":
            if not self.root:
                return 1, "", "Failed to set property"
            self.set(f"prop/{t[1]}", t[2])
            return 0, "", ""
        if t[:2] == ["settings", "put"]:
            self.set(f"settings/{t[2]}/{t[3]}", t[4])
            return 0, "", ""
        if t[:2] == ["settings", "get"]:
            if t[2:4] == ["secure", "android_id"]:
                # shell から見た Android ID は SSAID の鍵から作られる（無ければその場で生成）
                key = self.get(SSAID_FILE)
                if key is None:
                    key = secrets.token_hex(16)
                    self.set(SSAID_FILE, key)
                return 0, hashlib.sha256(f"{key}:shell".encode()).hexdigest()[:16] + "\n", ""
            return 0, str(self.get(f"settings/{t[2]}/{t[3]}") or "null") + "\n", ""
        if t[:2] == ["settings", "delete"]:
            if self.world.seal_effective:
                self.delete(f"settings/{t[2]}/{t[3]}")
            return 0, "Deleted 1 rows\n", ""
        if command == "stop":
            self.framework = False
            return 0, "", ""
        if t[0] == "rm":
            for path in t[1:]:
                if path.startswith("-"):
                    continue
                if path.endswith("/*"):
                    prefix = "file:" + path[:-1]
                    for k in [k for k in self.keys() if k.startswith(prefix)]:
                        self.delete(k)
                else:
                    self.delete("file:" + path)
            return 0, "", ""
        if command.startswith("grep -q android_id"):
            return 0, ("present\n" if self.get("settings/secure/android_id") else "absent\n"), ""
        if command == "sync":
            return 0, "", ""
        if command == "cat /sys/class/net/eth0/address":
            return 0, (self.mac or "02:42:ac:11:00:02") + "\n", ""
        return 127, "", f"/system/bin/sh: {command}: not found"

    def install(self, args: list[str]) -> tuple[int, str, str]:
        files = [a for a in args if not a.startswith("-")]
        for f in files:
            if not Path(f).exists():
                return 1, "", f"adb: cannot stat '{f}': No such file or directory"
        package = Path(files[0]).parent.name
        failure = self.world.install_failures.get(package)
        if failure:
            return 1, "Performing Streamed Install\n", f"adb: failed to install {files[0]}: Failure [{failure}]\n"
        self.set(f"pkg/{package}", len(files))
        return 0, "Performing Streamed Install\nSuccess\n", ""


class FakeWorld:
    """Runner と同じメソッドを持ち、adb と docker の呼び出しを受け付ける。"""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.calls: list[list[str]] = []
        self.spawned: list[list[str]] = []
        self.passthrough_calls: list[list[str]] = []
        self.binaries = {"adb", "docker", "scrcpy"}
        self.docker_up = True
        self.registry = {IMAGE_REF: (IMAGE_ID, 2_100_000_000)}
        self.local_images: dict[str, tuple[str, int]] = {}
        self.volumes: dict[str, dict] = {}
        self.containers: dict[str, FakeContainer] = {}
        self.connected: set[str] = set()
        self.phone: FakePhone | None = FakePhone()
        self.boot_polls = 2
        self.install_failures = {
            "com.example.armonly": "INSTALL_FAILED_NO_MATCHING_ABIS: Failed to extract native libraries, res=-113"
        }
        self.seal_effective = True
        self.crash_on_start: set[str] = set()
        self.now = 1000.0

    # ---- 時計 ----
    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 1.0)

    # ---- Runner インターフェース ----
    def run(self, args, *, check=True, timeout=None, input=None) -> CommandResult:
        argv = [str(a) for a in args]
        with self.lock:
            self.calls.append(argv)
            prog = Path(argv[0]).name
            if prog not in self.binaries:
                from droidfork.util import not_found_error
                raise not_found_error(argv[0])
            if prog == "adb":
                rc, out, err = self.adb(argv[1:])
            elif prog == "docker":
                rc, out, err = self.docker(argv[1:])
            else:
                rc, out, err = 127, "", "unknown"
        result = CommandResult(argv, rc, out, err)
        if check and rc != 0:
            raise CommandError(result)
        return result

    def passthrough(self, args) -> int:
        self.passthrough_calls.append([str(a) for a in args])
        return 0

    def spawn(self, args) -> None:
        self.spawned.append([str(a) for a in args])

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if Path(name).name in self.binaries else None

    # ---- 便利関数 ----
    def docker_calls(self, sub: str) -> list[list[str]]:
        return [c for c in self.calls if Path(c[0]).name == "docker" and c[1:2] == [sub]]

    def adb_calls(self) -> list[list[str]]:
        return [c for c in self.calls if Path(c[0]).name == "adb"]

    def container_by_addr(self, addr: str) -> FakeContainer | None:
        for c in self.containers.values():
            if c.addr == addr:
                return c
        return None

    # ---- adb ----
    def adb(self, args: list[str]) -> tuple[int, str, str]:
        serial = None
        if args[:1] == ["-s"]:
            serial, args = args[1], args[2:]
        cmd = args[0]
        if cmd == "version":
            return 0, "Android Debug Bridge version 1.0.41\nVersion 35.0.2\n", ""
        if cmd == "devices":
            lines = ["List of devices attached"]
            if self.phone is not None:
                lines.append(f"{self.phone.serial}       {self.phone.state} usb:1-1 product:dm1q model:SM_S911C device:dm1q transport_id:1")
            for addr in sorted(self.connected):
                c = self.container_by_addr(addr)
                if c and c.state == "running":
                    lines.append(f"{addr}        device product:redroid_x86_64 model:DroidFork_Virtual device:redroid_x86_64 transport_id:9")
            return 0, "\n".join(lines) + "\n\n", ""
        if cmd == "connect":
            addr = args[1]
            c = self.container_by_addr(addr)
            if c is None or c.state != "running":
                return 1, f"failed to connect to '{addr}': Connection refused\n", ""
            already = addr in self.connected
            self.connected.add(addr)
            return 0, ("already connected to " if already else "connected to ") + addr + "\n", ""
        if cmd == "disconnect":
            self.connected.discard(args[1])
            return 0, f"disconnected {args[1]}\n", ""

        if self.phone is not None and serial == self.phone.serial:
            if cmd == "shell":
                return self.phone.shell(args[1])
            if cmd == "pull":
                remote, local = args[1], Path(args[2])
                local.write_text(f"APK {remote}")
                return 0, f"{remote}: 1 file pulled\n", ""
            return 1, "", "unsupported"
        c = self.container_by_addr(serial or "")
        if c is None or c.state != "running" or serial not in self.connected:
            return 1, "", f"adb: device '{serial}' not found"
        if cmd == "shell":
            return c.shell(args[1])
        if cmd in ("install", "install-multiple"):
            return c.install(args[1:])
        if cmd == "root":
            c.root = True
            return 0, "adbd is already running as root\n", ""
        return 1, "", "unsupported"

    # ---- docker ----
    def docker(self, args: list[str]) -> tuple[int, str, str]:
        if not self.docker_up:
            return 1, "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
        cmd = args[0]
        if cmd == "version":
            return 0, "29.0.0\n", ""
        if cmd == "info":
            return 0, "/var/lib/docker\n", ""
        if cmd == "image" and args[1] == "inspect":
            fmt, ref = args[3], args[4]
            for r, (iid, size) in self.local_images.items():
                if ref in (r, iid):
                    return 0, (iid if "Id" in fmt else str(size)) + "\n", ""
            return 1, "", f"Error: No such image: {ref}"
        if cmd == "pull":
            if args[1] not in self.registry:
                return 1, "", "manifest unknown"
            self.local_images[args[1]] = self.registry[args[1]]
            return 0, "Status: Downloaded newer image\n", ""
        if cmd == "volume":
            return self._volume(args[1:])
        if cmd == "run":
            return self._run(args[1:])
        if cmd == "inspect":
            name = args[-1]
            c = self.containers.get(name)
            return (0, c.state + "\n", "") if c else (1, "", f"Error: No such container: {name}")
        if cmd == "ps":
            label = args[args.index("--filter") + 1].split("=", 1)[1]
            k, v = label.split("=", 1)
            lines = [f"{c.name}\t{c.state}" for c in self.containers.values() if c.labels.get(k) == v]
            return 0, "\n".join(lines) + ("\n" if lines else ""), ""
        if cmd == "stop":
            for name in args[3:]:
                if name in self.containers:
                    self.containers[name].state = "exited"
            return 0, "\n".join(args[3:]) + "\n", ""
        if cmd == "rm":
            for name in args[2:]:
                c = self.containers.pop(name, None)
                if c:
                    self.connected.discard(c.addr)
            return 0, "", ""
        if cmd == "logs":
            return 0, "init: starting service 'zygote'...\n", ""
        if cmd == "stats":
            names = args[4:]
            return 0, "".join(f"{n}\t812.5MiB / 15.6GiB\t3.20%\n" for n in names
                              if n in self.containers and self.containers[n].state == "running"), ""
        if cmd == "system" and args[1] == "df":
            vols = []
            for name, v in self.volumes.items():
                live = sum(1 for val in v["data"].values() if val is not None)
                base = 850_000_000 if v["labels"].get("droidfork.role") == "base" else 0
                vols.append({"Name": name, "Size": f"{(base + live * 1_000_000) / 1e6:.1f}MB", "Links": "1"})
            return 0, json.dumps({"Images": [], "Containers": [], "Volumes": vols, "BuildCache": []}) + "\n", ""
        return 1, "", f"unsupported docker command: {args}"

    def _volume(self, args: list[str]) -> tuple[int, str, str]:
        sub = args[0]
        if sub == "inspect":
            return (0, "[{}]\n", "") if args[1] in self.volumes else (1, "", "no such volume")
        if sub == "create":
            labels = {}
            rest = args[1:]
            while rest and rest[0] == "--label":
                k, v = rest[1].split("=", 1)
                labels[k] = v
                rest = rest[2:]
            self.volumes.setdefault(rest[0], {"labels": labels, "data": {}})
            return 0, rest[0] + "\n", ""
        if sub == "rm":
            name = args[1]
            for c in self.containers.values():
                if any(vol == name for vol, _, _ in c.mounts):
                    return 1, "", f"Error response from daemon: remove {name}: volume is in use"
            self.volumes.pop(name, None)
            return 0, name + "\n", ""
        return 1, "", "unsupported"

    def _run(self, args: list[str]) -> tuple[int, str, str]:
        name = labels = bind = port = mac = None
        labels, mounts = {}, []
        privileged = False
        i = 0
        while i < len(args) and args[i].startswith("-"):
            flag = args[i]
            if flag == "-d":
                i += 1
            elif flag == "--privileged":
                privileged = True
                i += 1
            elif flag == "--name":
                name = args[i + 1]
                i += 2
            elif flag == "--label":
                k, v = args[i + 1].split("=", 1)
                labels[k] = v
                i += 2
            elif flag == "-p":
                host, hport, cport = args[i + 1].rsplit(":", 2)
                assert cport == "5555"
                bind, port = host, int(hport)
                i += 2
            elif flag == "--mac-address":
                mac = args[i + 1]
                i += 2
            elif flag == "-v":
                parts = args[i + 1].split(":")
                mounts.append((parts[0], parts[1], len(parts) > 2 and parts[2] == "ro"))
                i += 2
            else:
                return 1, "", f"unknown flag {flag}"
        image, boot_args = args[i], args[i + 1:]
        assert privileged, "Redroid には --privileged が必要"
        if name in self.containers:
            return 125, "", f'Conflict. The container name "/{name}" is already in use'
        if not any(image in (r, iid) for r, (iid, _) in self.local_images.items()):
            return 125, "", f"Unable to find image '{image}' locally"
        for c in self.containers.values():
            if c.state == "running" and c.port == port:
                return 125, "", f"Bind for {bind}:{port} failed: port is already allocated"
        for vol, _, _ in mounts:
            self.volumes.setdefault(vol, {"labels": {}, "data": {}})
        c = FakeContainer(self, name, image, labels, bind, port, mounts, mac, boot_args)
        if name in self.crash_on_start:
            c.state = "exited"
        self.containers[name] = c
        return 0, secrets.token_hex(32) + "\n", ""


class FakeHost:
    def __init__(self) -> None:
        self.files = {
            "/proc/filesystems": "nodev\tsysfs\nnodev\tbinder\nnodev\toverlay\n\text4\n",
            "/proc/version": "Linux version 6.8.0-45-generic (buildd@lcy02) #45-Ubuntu SMP",
            "/proc/meminfo": "MemTotal:       16303428 kB\nMemFree:         9000000 kB\nMemAvailable:   12000000 kB\n",
            "/sys/kernel/mm/ksm/run": "0\n",
            "/sys/kernel/mm/ksm/pages_sharing": "0\n",
        }
        self.paths: set[str] = set()
        self.busy_ports: set[int] = set()

    def read_text(self, path: str):
        return self.files.get(path)

    def exists(self, path: str) -> bool:
        return path in self.paths or path in self.files

    def system(self) -> str:
        return "Linux"

    def release(self) -> str:
        return "6.8.0-45-generic"

    def machine(self) -> str:
        return "x86_64"

    def disk_free(self, path: str):
        return 200 * 1024**3

    def port_free(self, host: str, port: int) -> bool:
        return port not in self.busy_ports


def make_app(home: Path, world: FakeWorld, host: FakeHost | None = None, answers: list[str] | None = None) -> App:
    console = Console(out=io.StringIO(), err=io.StringIO())
    answers = list(answers or [])
    ports = iter(range(40001, 40100))
    return App(
        cfg=load_config(home=home, env={}),
        console=console,
        runner=world,  # type: ignore[arg-type]
        host=host or FakeHost(),  # type: ignore[arg-type]
        sleep=world.sleep,
        clock=world.clock,
        ask=lambda prompt: answers.pop(0) if answers else None,
        free_port=lambda: next(ports),
        poll_interval=1.0,
        settle_seconds=0.0,
    )


def out(app: App) -> str:
    return app.console.out.getvalue()  # type: ignore[attr-defined]


def err(app: App) -> str:
    return app.console.err.getvalue()  # type: ignore[attr-defined]
