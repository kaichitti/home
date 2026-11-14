"""WSL2 で実機を USB でつなぐ（Windows 側の usbipd-win を WSL から呼ぶ）。

WSL2 の中からは USB 機器が直接見えないため、usbipd-win で Windows から WSL へ機器を渡す。
初回だけ「共有（bind）」に管理者権限が要るので、Windows の権限確認（UAC）を出して実行する。
"""

from __future__ import annotations

import re
import webbrowser
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .hostcheck import is_wsl
from .util import DroidForkError

if TYPE_CHECKING:
    from .app import App

_ROW_RE = re.compile(r"^(\d+-[\d.]+)\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+(.*?)\s{2,}(\S.*)$")
# Android の ADB として見えることが多い機器の目印
ANDROID_HINTS = re.compile(r"android|adb|pixel|galaxy|samsung|xperia|aquos|arrows|oppo|xiaomi|motorola|sharp|sony|google", re.I)

USBIPD_HINT = (
    "Windows に usbipd-win を入れてください（PowerShell で: winget install usbipd）。"
    "DroidFork の Windows 版インストーラは自動で入れます。"
)


@dataclass
class UsbDevice:
    busid: str
    vid_pid: str
    name: str
    state: str          # Not shared / Shared / Attached

    @property
    def looks_android(self) -> bool:
        return bool(ANDROID_HINTS.search(self.name))

    @property
    def state_label(self) -> str:
        s = self.state.lower()
        if s.startswith("attached"):
            return "WSLに接続中"
        if s.startswith("shared"):
            return "共有済み（未接続）"
        return "未共有"


def parse_usbipd_list(text: str) -> list[UsbDevice]:
    devices = []
    in_connected = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("connected"):
            in_connected = True
            continue
        if stripped.lower().startswith("persisted"):
            in_connected = False
            continue
        if not in_connected:
            continue
        m = _ROW_RE.match(stripped)
        if m:
            devices.append(UsbDevice(m.group(1), m.group(2).lower(), m.group(3).strip(), m.group(4).strip()))
    return devices


def _require_wsl(app: "App") -> str:
    if not is_wsl(app.host):
        raise DroidForkError("この操作は Windows（WSL2）でだけ使います。", hint="Linux では実機を USB でつなぐだけで認識されます。")
    binary = app.cfg.usbipd
    if app.runner.which(binary) is None:
        raise DroidForkError("usbipd-win が見つかりません。", hint=USBIPD_HINT)
    return binary


def list_devices(app: "App") -> list[UsbDevice]:
    binary = _require_wsl(app)
    return parse_usbipd_list(app.runner.run([binary, "list"], timeout=60).stdout)


def attach(app: "App", busid: str) -> UsbDevice:
    """機器を WSL へつなぐ。未共有なら Windows の権限確認を出して共有してからつなぐ。"""
    binary = _require_wsl(app)
    devices = {d.busid: d for d in list_devices(app)}
    device = devices.get(busid)
    if device is None:
        raise DroidForkError(f"BUSID {busid} の機器が見つかりません。", hint="`droidfork usb list` で確認してください。")
    if device.state.lower().startswith("attached"):
        return device
    if device.state.lower().startswith("not shared"):
        app.console.step("Windows の権限確認が表示されたら「はい」を選んでください（初回だけ）")
        ps = f"Start-Process -FilePath usbipd -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList 'bind','--busid','{busid}'"
        app.runner.run(["powershell.exe", "-NoProfile", "-Command", ps], timeout=300)
    r = app.runner.run([binary, "attach", "--wsl", "--busid", busid], check=False, timeout=120)
    if not r.ok:
        raise DroidForkError(
            f"機器 {busid} を WSL へつなげませんでした。\n{r.output.strip()}",
            hint=f"Windows の管理者 PowerShell で `usbipd bind --busid {busid}` を実行してから、もう一度試してください。",
        )
    return UsbDevice(device.busid, device.vid_pid, device.name, "Attached")


def detach(app: "App", busid: str) -> None:
    binary = _require_wsl(app)
    app.runner.run([binary, "detach", "--busid", busid], timeout=60)


def open_url(app: "App", url: str) -> bool:
    """URL をブラウザで開く。WSL では Windows 側のブラウザを使う。"""
    if is_wsl(app.host):
        for cmd in (["wslview", url], ["explorer.exe", url]):
            if app.runner.which(cmd[0]):
                app.runner.spawn(cmd)
                return True
        return False
    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False
