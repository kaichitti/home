"""雛形（テンプレート）の作成と削除（企画書5章 手順3、6章）。

雛形の作り方:
1. ベースの Redroid を、空の Docker ボリュームを /data にして1回だけ起動する
2. 言語・タイムゾーン・表示設定を反映し、取り込んだ APK を導入する
3. Android ID など端末固有の値を取り除いてから停止する（封印）
4. このボリュームを「共有層」として、以後は全インスタンスが読み取り専用で参照する
"""

from __future__ import annotations

import contextlib
import shlex
from typing import TYPE_CHECKING

from .boot import BootTarget, ensure_root_shell, wait_for_boot
from .identity import build_serial, device_props
from .images import VERSION_TO_SDK, image_ref
from .redroid import (
    DATA, LABEL_MANAGED, LABEL_ROLE, LABEL_TEMPLATE, ROLE_BUILD, BootOptions, Mount, RunSpec,
    adb_address, base_volume_name, boot_args, build_container_name, docker_run_args,
)
from .store import Template
from .util import DroidForkError, now_iso

if TYPE_CHECKING:
    from .app import App

# 封印時に消すファイル（各インスタンスの初回起動で Android が新しく作り直す）
SEAL_REMOVE_FILES = (
    "/data/system/users/0/settings_ssaid.xml",  # アプリから見える Android ID（SSAID）の元になる鍵
    "/data/system/entropy.dat",                  # 乱数の種
)
# 封印時に中身を空にするディレクトリ（雛形作成中のログ類）
SEAL_CLEAR_DIRS = ("/data/system/dropbox", "/data/tombstones", "/data/anr")
SECURE_SETTINGS_FILE = "/data/system/users/0/settings_secure.xml"

INSTALL_FAILURE_HINTS = {
    "INSTALL_FAILED_NO_MATCHING_ABIS":
        "ARM向けのネイティブコードを含むアプリです。ARM翻訳（libndk_translation）入りのイメージか、ARMのホストが必要です。",
    "INSTALL_FAILED_OLDER_SDK":
        "より新しいAndroidが必要なアプリです。capture --android で新しいバージョンを指定してください。",
    "INSTALL_FAILED_MISSING_SHARED_LIBRARY":
        "Google Play 開発者サービスなど、同梱しない共有ライブラリが必要なアプリです。",
    "INSTALL_FAILED_DEPRECATED_SDK_VERSION":
        "古いAndroid向けのアプリのため、新しいAndroidでは導入が制限されています。",
}


def failure_hint(message: str) -> str | None:
    for code, hint in INSTALL_FAILURE_HINTS.items():
        if code in message:
            return hint
    return None


def build_template(
    app: "App",
    name: str,
    *,
    image: str | None = None,
    force: bool = False,
    keep_on_error: bool = False,
) -> Template:
    store, cfg, console = app.store, app.cfg, app.console
    tpl = store.load_template(name)
    if tpl.sealed and not force:
        raise DroidForkError(f"テンプレート「{name}」は作成済みです。", hint="作り直す場合は --force を付けてください。")
    users = store.list_instances(template=name)
    if users:
        raise DroidForkError(
            f"テンプレート「{name}」を使うインスタンスが {len(users)} 台あるため作り直せません。",
            hint="共有層を差し替えると各インスタンスの差分層と食い違います。"
                 f"先に `droidfork rm -t {name}` でインスタンスを削除してください。",
        )
    app.docker.ensure_daemon()

    ref = image
    if ref is None:
        ref, note = image_ref(cfg.image_repo, tpl.android_version, cfg.image_variant)
        if note:
            console.warn(note)
    if app.docker.image_id(ref) is None:
        console.step(f"ベースイメージ {ref} を取得します")
        app.docker.pull(ref)
    image_id = app.docker.image_id(ref)
    if image_id is None:
        raise DroidForkError(f"イメージ {ref} を用意できませんでした。")

    volume = base_volume_name(name)
    container = build_container_name(name)
    app.docker.remove([container])
    app.docker.volume_rm(volume)
    app.docker.volume_create(volume, {LABEL_MANAGED: "1", LABEL_ROLE: "base", LABEL_TEMPLATE: name})
    tpl.state, tpl.image, tpl.image_id, tpl.install_results, tpl.built_at = "building", ref, image_id, {}, None
    store.save_template(tpl)

    port = app.free_port()
    addr = adb_address("127.0.0.1", port)
    options = BootOptions(
        display=tpl.display,
        gpu_mode=cfg.gpu_mode,
        use_memfd=app.use_memfd(),
        serialno=build_serial(),
        props=device_props(cfg.manufacturer, cfg.model),
        dns=list(cfg.dns),
        root_adb=True,
    )
    spec = RunSpec(
        name=container,
        image=image_id,
        labels={LABEL_MANAGED: "1", LABEL_ROLE: ROLE_BUILD, LABEL_TEMPLATE: name},
        bind_host="127.0.0.1",
        host_port=port,
        mounts=[Mount(volume, DATA)],
        boot_args=boot_args(options),
    )
    try:
        console.step(f"雛形用に Android {tpl.android_version} を起動します（初回は数分かかります）")
        started = app.clock()
        app.docker.run(docker_run_args(spec))
        seconds = wait_for_boot(app, BootTarget(name, addr, container, started), cfg.template_boot_timeout)
        console.info(f"起動しました（{seconds:.0f}秒）")
        ensure_root_shell(app, addr)
        apply_profile(app, addr, tpl)
        install_packages(app, addr, tpl)
        seal(app, addr, tpl)
        console.step("雛形を停止して固定します")
        app.adb.disconnect(addr)
        app.docker.stop([container], timeout=20)
        app.docker.remove([container])
    except BaseException:
        tpl.state = "failed"
        store.save_template(tpl)
        with contextlib.suppress(DroidForkError):
            app.adb.disconnect(addr)
        if keep_on_error:
            console.warn(f"調査用にコンテナ {container} を残しました（docker logs {container}、adb connect {addr}）。")
        else:
            with contextlib.suppress(DroidForkError):
                app.docker.remove([container])
        raise
    tpl.state, tpl.built_at = "sealed", now_iso()
    store.save_template(tpl)
    ok = sum(1 for v in tpl.install_results.values() if v == "ok")
    console.step(f"テンプレート「{name}」を作成しました（アプリ {ok}/{len(tpl.packages)} 個を導入）")
    return tpl


def _shell(app: "App", addr: str, command: str) -> bool:
    r = app.adb.cmd("shell", command, serial=addr, check=False, timeout=60)
    return r.ok


def apply_profile(app: "App", addr: str, tpl: Template) -> None:
    """実機から読んだ言語・タイムゾーン・表示設定を雛形に書き込む。"""
    app.console.step("言語・タイムゾーン・表示設定を反映します")
    commands = []
    if tpl.locale:
        commands.append(f"setprop persist.sys.locale {shlex.quote(tpl.locale)}")
    if tpl.timezone:
        commands.append("settings put global auto_time_zone 0")
        commands.append(f"setprop persist.sys.timezone {shlex.quote(tpl.timezone)}")
    for namespace, values in tpl.settings.items():
        for key, value in values.items():
            commands.append(f"settings put {shlex.quote(namespace)} {shlex.quote(key)} {shlex.quote(value)}")
    for command in commands:
        if not _shell(app, addr, command):
            note = f"設定を反映できませんでした: {command}"
            app.console.warn(note)
            tpl.notes.append(note)


def install_packages(app: "App", addr: str, tpl: Template) -> None:
    if not tpl.packages:
        app.console.info("導入するアプリはありません")
        return
    app.console.step(f"アプリ {len(tpl.packages)} 個を雛形に導入します")
    apk_root = app.store.apk_dir(tpl.name)
    image_sdk = VERSION_TO_SDK.get(tpl.android_version, 0)
    for i, pkg in enumerate(tpl.packages, 1):
        files = [apk_root / pkg.name / f for f in pkg.files]
        if not files or any(not f.exists() for f in files):
            ok, message = False, "APKファイルが見つかりません"
        else:
            ok, message = app.adb.install(addr, files)
            if not ok and "INSTALL_FAILED_DEPRECATED_SDK_VERSION" in message and image_sdk >= 34:
                ok, message = app.adb.install(addr, files, extra=["--bypass-low-target-sdk-block"])
        tpl.install_results[pkg.name] = "ok" if ok else message
        app.console.info(f"[{i}/{len(tpl.packages)}] {pkg.name}: " + ("導入しました" if ok else f"失敗（{message}）"))
    failed = {k: v for k, v in tpl.install_results.items() if v != "ok"}
    if failed:
        app.console.warn(f"{len(failed)} 個のアプリを導入できませんでした。")
        for hint in sorted({h for h in (failure_hint(v) for v in failed.values()) if h}):
            app.console.info(f"- {hint}")


def seal(app: "App", addr: str, tpl: Template) -> None:
    """雛形から端末固有の値を取り除く（企画書8章）。

    Android ID は「設定の android_id」と「アプリごとの SSAID の鍵（settings_ssaid.xml）」の2つ。
    どちらも雛形に残さず、各インスタンスの初回起動で Android 自身に新しく作らせる。
    """
    app.console.step("端末固有の値（Android ID など）を雛形から取り除きます")
    _shell(app, addr, "settings delete secure android_id")
    app.sleep(app.settle_seconds)       # 設定がファイルへ書き出されるのを待つ
    _shell(app, addr, "stop")           # フレームワークを止める（以後は設定が書き戻されない）
    app.sleep(app.settle_seconds)
    for path in SEAL_REMOVE_FILES:
        _shell(app, addr, f"rm -f {path}")
    for directory in SEAL_CLEAR_DIRS:
        _shell(app, addr, f"rm -rf {directory}/*")
    check = app.adb.shell(
        addr, f"grep -q android_id {SECURE_SETTINGS_FILE} && echo present || echo absent", check=False
    ).strip()
    if check == "present":
        note = ("Android ID が雛形の設定に残っている可能性があります。"
                "インスタンス起動後に `droidfork ids` で重複がないか確認してください。")
        app.console.warn(note)
        tpl.notes.append(note)
    _shell(app, addr, "sync")


def remove_template(app: "App", name: str, *, force: bool = False) -> int:
    """テンプレートを削除する。戻り値は一緒に削除したインスタンスの台数。"""
    from .instances import remove_instances  # 循環 import を避ける

    app.store.load_template(name)
    users = app.store.list_instances(template=name)
    if users and not force:
        raise DroidForkError(
            f"テンプレート「{name}」を使うインスタンスが {len(users)} 台あります。",
            hint="インスタンスごと削除する場合は --force を付けてください。",
        )
    app.docker.ensure_daemon()
    if users:
        remove_instances(app, users)
    app.docker.remove([build_container_name(name)])
    app.docker.volume_rm(base_volume_name(name))
    app.store.remove_template_files(name)
    return len(users)
