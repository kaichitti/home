"""ホスト環境の確認（droidfork doctor）。"""

from __future__ import annotations

import os
import platform
import re
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import LOOPBACK_BINDS
from .util import format_bytes, is_port_free

if TYPE_CHECKING:
    from .app import App

OK, WARN, NG, INFO = "OK", "注意", "NG", "情報"


class HostProbe:
    """ホストの情報を読む窓口。テストでは偽物に差し替える。"""

    def read_text(self, path: str) -> str | None:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def system(self) -> str:
        return platform.system()

    def release(self) -> str:
        return platform.release()

    def machine(self) -> str:
        return platform.machine()

    def disk_free(self, path: str) -> int | None:
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return None

    def port_free(self, host: str, port: int) -> bool:
        return is_port_free(host, port)


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str | None = None


def meminfo(probe: HostProbe) -> dict[str, int]:
    """/proc/meminfo の値（バイト）。"""
    text = probe.read_text("/proc/meminfo") or ""
    result = {}
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s+(\d+)\s*kB", line)
        if m:
            result[m.group(1)] = int(m.group(2)) * 1024
    return result


def ksm_status(probe: HostProbe) -> dict[str, int] | None:
    """Linux の同一ページ統合（KSM）の状態。企画書10章のメモリ重複排除の検証用。"""
    run = probe.read_text("/sys/kernel/mm/ksm/run")
    if run is None:
        return None
    sharing = probe.read_text("/sys/kernel/mm/ksm/pages_sharing") or "0"
    try:
        return {"run": int(run.strip()), "pages_sharing": int(sharing.strip())}
    except ValueError:
        return None


def has_binder(probe: HostProbe) -> bool:
    filesystems = probe.read_text("/proc/filesystems") or ""
    return bool(re.search(r"\bbinder\b", filesystems)) or probe.exists("/dev/binder")


def is_wsl(probe: HostProbe) -> bool:
    return "microsoft" in (probe.read_text("/proc/version") or "").lower()


def run_checks(app: "App") -> list[Check]:
    probe, cfg = app.host, app.cfg
    checks: list[Check] = []
    wsl = is_wsl(probe)

    system = probe.system()
    if system != "Linux":
        checks.append(Check("ホストOS", NG, system, "Linux が必要です（Windows では WSL2 の中で実行します）。"))
    else:
        checks.append(Check("ホストOS", OK, f"Linux {probe.release()} ({probe.machine()})" + (" / WSL2" if wsl else "")))

    # Docker
    if app.runner.which(cfg.docker) is None:
        checks.append(Check("Docker", NG, "docker コマンドが見つかりません", "Docker Engine を入れてください。"))
    else:
        version = app.docker.server_version()
        if version:
            checks.append(Check("Docker", OK, f"デーモン {version}"))
        else:
            checks.append(Check("Docker", NG, "デーモンに接続できません",
                                "sudo systemctl start docker を実行し、このユーザーを docker グループに入れてください。"))

    # binder（Android のプロセス間通信。コンテナ型Androidの必須機能）
    if has_binder(probe):
        checks.append(Check("binder", OK, "カーネルが binder に対応しています"))
    elif wsl:
        checks.append(Check("binder", NG, "WSL2 の標準カーネルには binder がありません",
                            "CONFIG_ANDROID_BINDER_IPC と CONFIG_ANDROID_BINDERFS を有効にしたカスタムカーネルを"
                            ".wslconfig の kernel= で指定してください。"))
    else:
        checks.append(Check("binder", NG, "binder が見つかりません",
                            'sudo modprobe binder_linux devices="binder,hwbinder,vndbinder" を実行してください'
                            "（Ubuntu では先に sudo apt install linux-modules-extra-$(uname -r)）。"))

    # ashmem / memfd
    if probe.exists("/dev/ashmem"):
        checks.append(Check("共有メモリ", OK, "ashmem を使用"))
    else:
        mode = "memfd を使用（androidboot.use_memfd=true）" if cfg.use_memfd != "false" else "ashmem も memfd も無効"
        status = INFO if cfg.use_memfd != "false" else NG
        checks.append(Check("共有メモリ", status, f"/dev/ashmem なし → {mode}",
                            None if status == INFO else "設定 use_memfd を auto にしてください。"))

    # overlayfs（雛形＋差分の仕組みに必要）
    filesystems = probe.read_text("/proc/filesystems") or ""
    if re.search(r"\boverlay\b", filesystems):
        checks.append(Check("overlayfs", OK, "差分層を使えます"))
    else:
        checks.append(Check("overlayfs", NG, "overlay が見つかりません", "sudo modprobe overlay を実行してください。"))

    # adb / scrcpy
    adb_version = app.adb.version() if app.runner.which(cfg.adb) else None
    if adb_version:
        checks.append(Check("adb", OK, adb_version))
    else:
        checks.append(Check("adb", NG, "adb が見つかりません", "sudo apt install adb などで入れてください。"))
    if app.runner.which(cfg.scrcpy):
        checks.append(Check("scrcpy", OK, "画面表示（droidfork screen）が使えます"))
    else:
        checks.append(Check("scrcpy", WARN, "見つかりません（画面表示を使うときだけ必要）", "sudo apt install scrcpy"))

    # メモリ
    mem = meminfo(probe)
    if mem.get("MemTotal"):
        checks.append(Check("メモリ", INFO, f"合計 {format_bytes(mem['MemTotal'])} / 空き {format_bytes(mem.get('MemAvailable'))}"))

    ksm = ksm_status(probe)
    if ksm is not None:
        state = "有効" if ksm["run"] == 1 else "無効"
        checks.append(Check("KSM（同一ページ統合）", INFO, f"{state}（統合中 {ksm['pages_sharing']} ページ）"))

    # ディスク
    root = app.docker.root_dir() if app.runner.which(cfg.docker) else None
    if root:
        free = probe.disk_free(root)
        if free is not None:
            checks.append(Check("ディスク", INFO if free > 20 * 1024**3 else WARN,
                                f"{root} の空き {format_bytes(free)}",
                                None if free > 20 * 1024**3 else "ベースイメージと雛形で 10GB 前後を使います。"))

    # ADB の待ち受け
    if cfg.adb_bind in LOOPBACK_BINDS:
        checks.append(Check("ADB の公開範囲", OK, f"{cfg.adb_bind} のみで待ち受け"))
    else:
        checks.append(Check("ADB の公開範囲", WARN, f"{cfg.adb_bind} で待ち受け（外部から接続できます）",
                            "ADB を公開ネットワークに出すと端末やホストを乗っ取られるおそれがあります。"
                            "必要がなければ adb_bind を 127.0.0.1 に戻してください。"))
    return checks
