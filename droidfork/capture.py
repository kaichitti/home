"""実機からの取り込み（企画書5章 手順1〜2、7章）。

取り込むもの: Android バージョン、画面解像度・DPI、言語・タイムゾーン、一部の表示設定、
ユーザーがインストールしたアプリの APK（分割APKを含む）。
取り込まないもの: アプリ内データ・ログイン状態、プリインアプリ、IMEI・シリアルなどの識別子。
root は不要で、adb で読み取るだけ。
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Sequence

from .adb import AdbDevice, parse_int, parse_package_info, parse_package_list, parse_pm_paths, parse_resolution, parse_wm
from .images import VERSION_TO_SDK, choose_version, parse_version_arg
from .redroid import Display, adb_address
from .store import PackageEntry, Template
from .util import DroidForkError, now_iso, slugify, validate_name, write_json

if TYPE_CHECKING:
    from .app import App

# 取り込む設定（Settings の名前空間 → キー）。画面まわりの見た目に関わるものだけ。
SETTINGS_TO_CAPTURE = {"system": ("font_scale", "time_12_24")}

SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9._,+/-]{1,64}$")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
APK_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.apk$")
DEFAULT_DISPLAY = (720, 1280, 320)

USB_HINT = (
    "実機をUSBケーブルで接続し、「開発者向けオプション」で「USBデバッグ」を有効にしてください。"
    "接続状況は `droidfork devices` で確認できます。"
)


@dataclass
class DeviceProfile:
    release: str | None
    sdk: int | None
    display: Display
    locale: str | None
    timezone: str | None
    settings: dict[str, dict[str, str]]
    source: dict[str, object]
    notes: list[str] = field(default_factory=list)


def managed_addresses(app: "App") -> set[str]:
    return {adb_address(app.cfg.adb_bind, i.adb_port) for i in app.store.list_instances()}


def select_device(app: "App", serial: str | None = None) -> AdbDevice:
    managed = managed_addresses(app)
    devices = [d for d in app.adb.devices()
               if d.serial not in managed and not d.is_emulator and not d.is_local_tcp]
    if serial:
        matches = [d for d in devices if d.serial == serial]
        if not matches:
            raise DroidForkError(f"指定の端末 {serial} が見つかりません。", hint=USB_HINT)
        device = matches[0]
    else:
        if not devices:
            raise DroidForkError("取り込み元の実機が見つかりません。", hint=USB_HINT)
        if len(devices) > 1:
            listing = ", ".join(f"{d.serial}（{d.model or d.state}）" for d in devices)
            raise DroidForkError("複数の端末が接続されています。", hint=f"--serial で取り込み元を指定してください: {listing}")
        device = devices[0]
    if device.state == "unauthorized":
        raise DroidForkError(
            "端末側でUSBデバッグが許可されていません。",
            hint="端末の画面に出る「USBデバッグを許可しますか？」で「許可」を押してから、もう一度実行してください。",
        )
    if device.state == "no permissions":
        raise DroidForkError("この端末にアクセスする権限がありません。",
                             hint="udev ルールを設定してください（例: sudo apt install android-sdk-platform-tools-common）。")
    if device.state != "device":
        raise DroidForkError(f"端末の状態が「{device.state}」のため取り込めません。", hint="ケーブルを挿し直してください。")
    return device


def _safe(value: str | None) -> str | None:
    if value and SAFE_VALUE_RE.match(value):
        return value
    return None


def read_profile(app: "App", serial: str) -> DeviceProfile:
    adb = app.adb
    notes: list[str] = []
    props = adb.getprops(serial)
    release = props.get("ro.build.version.release") or None
    sdk = parse_int(props.get("ro.build.version.sdk"))

    size_physical, size_override = parse_wm(adb.shell(serial, "wm size", check=False))
    dpi_physical, dpi_override = parse_wm(adb.shell(serial, "wm density", check=False))
    resolution = parse_resolution(size_override) or parse_resolution(size_physical)
    dpi = parse_int(dpi_override) or parse_int(dpi_physical)
    if resolution is None or dpi is None:
        notes.append("画面サイズを読み取れなかったため 720x1280 / 320dpi を使います。")
        resolution, dpi = DEFAULT_DISPLAY[:2], DEFAULT_DISPLAY[2]
    display = Display(resolution[0], resolution[1], dpi, fps=app.cfg.fps)

    locale = props.get("persist.sys.locale") or props.get("ro.product.locale")
    if not locale and props.get("persist.sys.language"):
        locale = "-".join(filter(None, [props.get("persist.sys.language"), props.get("persist.sys.country")]))
    timezone = props.get("persist.sys.timezone")

    settings: dict[str, dict[str, str]] = {}
    for namespace, keys in SETTINGS_TO_CAPTURE.items():
        for key in keys:
            value = adb.shell(serial, f"settings get {namespace} {key}", check=False, timeout=15).strip()
            if value and value != "null" and _safe(value):
                settings.setdefault(namespace, {})[key] = value

    # 表示用メモ。シリアル番号・IMEI などは取り込まない（企画書8章）
    source = {
        "manufacturer": props.get("ro.product.manufacturer"),
        "model": props.get("ro.product.model"),
        "android_release": release,
        "sdk": sdk,
        "abi": props.get("ro.product.cpu.abi"),
        "screen_physical": size_physical,
        "density_physical": dpi_physical,
        "captured_at": now_iso(),
    }
    return DeviceProfile(release, sdk, display, _safe(locale), _safe(timezone), settings, source, notes)


def list_user_packages(app: "App", serial: str, include: Sequence[str] = (), exclude: Sequence[str] = ()) -> list[str]:
    names = [n for n in parse_package_list(app.adb.shell(serial, "pm list packages -3")) if PACKAGE_RE.match(n)]
    if include:
        names = [n for n in names if any(fnmatch.fnmatch(n, p) for p in include)]
    if exclude:
        names = [n for n in names if not any(fnmatch.fnmatch(n, p) for p in exclude)]
    return names


def pull_package(app: "App", serial: str, package: str, dest_root: Path) -> PackageEntry:
    paths = parse_pm_paths(app.adb.shell(serial, f"pm path {package}", check=False))
    if not paths:
        raise DroidForkError(f"{package} のAPKの場所が分かりません。")
    info = parse_package_info(app.adb.shell(serial, f"dumpsys package {package}", check=False, timeout=90))
    pkg_dir = dest_root / package
    pkg_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for i, remote in enumerate(paths):
        name = PurePosixPath(remote).name
        if not APK_NAME_RE.match(name) or name in files:
            name = f"part{i}.apk"
        app.adb.pull(serial, remote, pkg_dir / name)
        files.append(name)
    return PackageEntry(name=package, files=files, **info)  # type: ignore[arg-type]


def unique_template_name(app: "App", base: str) -> str:
    base = slugify(base)[:30]
    name, n = base, 2
    while app.store.template_exists(name):
        name, n = f"{base}-{n}", n + 1
    return name


def _check_new_name(app: "App", name: str) -> str:
    validate_name(name, "テンプレート名")
    if app.store.template_exists(name):
        raise DroidForkError(
            f"テンプレート「{name}」はすでにあります。",
            hint="別の --name を指定するか、`droidfork template rm` で削除してください。",
        )
    return name


def _commit(app: "App", staging: Path, template: Template) -> Template:
    """一時ディレクトリに作った雛形を正式な場所へ移す（途中で失敗しても半端な雛形を残さない）。"""
    write_json(staging / "template.json", template.to_dict())
    final = app.store.template_dir(template.name)
    if final.exists():
        raise DroidForkError(f"テンプレート「{template.name}」はすでにあります。")
    os.replace(staging, final)
    return template


def _staging_dir(app: "App", name: str) -> Path:
    path = app.cfg.templates_dir / f".staging-{name}-{os.getpid()}"
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def capture(
    app: "App",
    *,
    serial: str | None = None,
    name: str | None = None,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    with_apks: bool = True,
    android: str | None = None,
) -> Template:
    device = select_device(app, serial)
    app.console.step(f"実機を読み取ります: {device.model or '機種名不明'}")
    profile = read_profile(app, device.serial)
    model = str(profile.source.get("model") or "device")
    name = _check_new_name(app, name) if name else unique_template_name(app, model)

    choice = choose_version(profile.sdk, profile.release)
    version = choice.version
    notes = list(profile.notes)
    if android:
        version = parse_version_arg(android)
        if version != choice.version:
            notes.append(f"実機は Android {profile.release} ですが、指定により Android {version} のイメージを使います。")
    elif choice.note:
        notes.append(choice.note)

    template = Template(
        name=name, state="captured", created_at=now_iso(),
        android_version=version, android_sdk=profile.sdk, display=profile.display,
        locale=profile.locale, timezone=profile.timezone, settings=profile.settings,
        source=profile.source, notes=notes,
    )
    app.console.info(f"Android {profile.release}（API {profile.sdk}）→ イメージ {version}")
    app.console.info(f"画面 {profile.display.width}x{profile.display.height} {profile.display.dpi}dpi / "
                     f"言語 {profile.locale or '不明'} / タイムゾーン {profile.timezone or '不明'}")

    staging = _staging_dir(app, name)
    try:
        if with_apks:
            packages = list_user_packages(app, device.serial, include, exclude)
            app.console.step(f"ユーザーがインストールしたアプリ {len(packages)} 個のAPKを取得します")
            image_sdk = VERSION_TO_SDK.get(version, 0)
            for i, package in enumerate(packages, 1):
                try:
                    entry = pull_package(app, device.serial, package, staging / "apks")
                except DroidForkError as exc:
                    shutil.rmtree(staging / "apks" / package, ignore_errors=True)
                    app.console.warn(f"{package}: APKを取得できませんでした（{str(exc).splitlines()[0]}）")
                    template.notes.append(f"{package}: APKを取得できなかったため取り込んでいません。")
                    continue
                if entry.min_sdk and entry.min_sdk > image_sdk:
                    template.notes.append(f"{package}: API {entry.min_sdk} 以上が必要なため、導入に失敗する可能性があります。")
                template.packages.append(entry)
                app.console.info(f"[{i}/{len(packages)}] {package}（{len(entry.files)} ファイル）")
        _commit(app, staging, template)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    for note in template.notes:
        app.console.warn(note)
    app.console.step(f"テンプレート「{name}」に取り込みました（アプリ {len(template.packages)} 個）")
    return template


def _apk_group(path: Path) -> tuple[str, list[Path]]:
    if path.is_dir():
        files = sorted(path.glob("*.apk"))
        if not files:
            raise DroidForkError(f"{path} にAPKがありません。")
        return path.name, files
    if path.is_file() and path.suffix.lower() == ".apk":
        return path.stem, [path]
    raise DroidForkError(
        f"{path} はAPKではありません。",
        hint="APKファイルか、分割APKをまとめたフォルダを指定してください（.apks/.xapk は展開してから指定）。",
    )


def apk_groups(paths: Sequence[Path]) -> list[tuple[str, list[Path]]]:
    return [_apk_group(Path(p)) for p in paths]


def new_template(
    app: "App",
    name: str,
    *,
    android: str,
    size: str = "720x1280",
    dpi: int = 320,
    locale: str | None = None,
    timezone: str | None = None,
    apks: Sequence[Path] = (),
) -> Template:
    """実機なしで雛形を定義する（PoCや研修用。中身は手元のAPKと指定値）。"""
    _check_new_name(app, name)
    version = parse_version_arg(android)
    resolution = parse_resolution(size)
    if resolution is None:
        raise DroidForkError(f"画面サイズ「{size}」を読めません。", hint="720x1280 のように指定してください。")
    for label, value in (("言語", locale), ("タイムゾーン", timezone)):
        if value is not None and not _safe(value):
            raise DroidForkError(f"{label}「{value}」は使えません。")
    groups = apk_groups(apks)
    template = Template(
        name=name, state="captured", created_at=now_iso(),
        android_version=version, android_sdk=VERSION_TO_SDK[version],
        display=Display(resolution[0], resolution[1], dpi, fps=app.cfg.fps),
        locale=locale, timezone=timezone, source={"manual": True},
    )
    staging = _staging_dir(app, name)
    try:
        used: set[str] = set()
        for label, files in groups:
            pkg = re.sub(r"[^A-Za-z0-9_.]", "_", label) or "app"
            base, n = pkg, 2
            while pkg in used:
                pkg, n = f"{base}_{n}", n + 1
            used.add(pkg)
            dest = staging / "apks" / pkg
            dest.mkdir(parents=True)
            names = []
            for i, f in enumerate(files):
                target = f.name if APK_NAME_RE.match(f.name) else f"part{i}.apk"
                shutil.copy2(f, dest / target)
                names.append(target)
            template.packages.append(PackageEntry(name=pkg, files=names, source="local"))
        _commit(app, staging, template)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    app.console.step(f"テンプレート「{name}」を定義しました（Android {version}、アプリ {len(template.packages)} 個）")
    return template
