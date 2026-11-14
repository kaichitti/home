"""インスタンスの複製・起動・停止・リセット・削除（企画書5章 手順4〜5、6章）。

各インスタンスは
- 共有層（雛形のボリューム）を /data-base に読み取り専用でマウントし、
- 自分だけの差分層（空のボリュームから始まる）を /data-diff にマウントする。
複製時にディスクはコピーしないので一瞬で終わり、リセットは差分層を作り直すだけで終わる。
"""

from __future__ import annotations

import contextlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from .boot import BootTarget, wait_for_boot_many
from .capture import apk_groups
from .identity import device_props, new_mac, new_serial
from .redroid import (
    DATA_BASE, DATA_DIFF, LABEL_INSTANCE, LABEL_MANAGED, LABEL_ROLE, LABEL_TEMPLATE, ROLE_INSTANCE,
    BootOptions, Mount, RunSpec, adb_address, base_volume_name, boot_args, container_name,
    diff_volume_name, docker_run_args,
)
from .store import Instance, Template
from .util import DroidForkError, not_found_error, now_iso

if TYPE_CHECKING:
    from .app import App

MAX_CREATE = 200
STATE_LABELS = {
    "running": "起動中",
    "exited": "異常終了",
    "dead": "異常終了",
    "created": "作成中",
    "restarting": "再起動中",
    "paused": "一時停止",
    None: "停止",
}
INSTANCE_LABEL = f"{LABEL_ROLE}={ROLE_INSTANCE}"


def instance_addr(app: "App", inst: Instance) -> str:
    return adb_address(app.cfg.adb_bind, inst.adb_port)


def select_instances(
    app: "App",
    ids: Sequence[str] = (),
    *,
    all_: bool = False,
    template: str | None = None,
    default_all: bool = False,
) -> list[Instance]:
    if ids:
        return [app.store.load_instance(i) for i in dict.fromkeys(ids)]
    if template:
        app.store.load_template(template)
        return app.store.list_instances(template=template)
    if all_ or default_all:
        return app.store.list_instances()
    raise DroidForkError(
        "対象のインスタンスを指定してください。",
        hint="ID を並べるか、--template（-t）または --all を付けてください。",
    )


def container_states(app: "App") -> dict[str, str]:
    return app.docker.containers(INSTANCE_LABEL)


# ---- 複製 ----

def _allocate_port(app: "App", taken: set[int]) -> int:
    cfg = app.cfg
    for port in range(cfg.adb_port_base, cfg.adb_port_base + cfg.adb_port_count):
        if port not in taken and app.host.port_free(cfg.adb_bind, port):
            return port
    raise DroidForkError(
        "空いている ADB ポートがありません。",
        hint="設定 adb_port_base / adb_port_count で範囲を広げてください。",
    )


def create_instances(
    app: "App",
    template_name: str,
    count: int,
    *,
    scale: float = 1.0,
    fps: int | None = None,
) -> list[Instance]:
    if not 1 <= count <= MAX_CREATE:
        raise DroidForkError(f"台数は 1〜{MAX_CREATE} で指定してください。")
    if not 0.2 <= scale <= 1.0:
        raise DroidForkError("--scale は 0.2〜1.0 で指定してください。")
    if fps is not None and not 1 <= fps <= 120:
        raise DroidForkError("--fps は 1〜120 で指定してください。")
    tpl = app.store.load_template(template_name)
    if not tpl.sealed:
        raise DroidForkError(
            f"テンプレート「{tpl.name}」はまだ作成されていません（状態: {tpl.state}）。",
            hint=f"`droidfork template build {tpl.name}` で作成してください。",
        )
    app.docker.ensure_daemon()
    display = tpl.display.with_fps(fps).scaled(scale)

    created: list[Instance] = []
    with app.store.lock():
        existing = app.store.list_instances()
        ports = {i.adb_port for i in existing}
        serials = {i.serialno for i in existing}
        macs = {i.mac for i in existing}
        next_index = max((i.index for i in existing if i.template == tpl.name), default=0) + 1
        for k in range(count):
            index = next_index + k
            inst = Instance(
                id=f"{tpl.name}-{index:02d}",
                template=tpl.name,
                index=index,
                adb_port=_allocate_port(app, ports),
                serialno=new_serial(index, serials),
                mac=new_mac(macs),
                display=display,
                created_at=now_iso(),
            )
            ports.add(inst.adb_port)
            serials.add(inst.serialno)
            macs.add(inst.mac)
            diff = diff_volume_name(inst.id)
            app.docker.volume_rm(diff)  # 以前の残骸があれば消す
            app.docker.volume_create(diff, {LABEL_MANAGED: "1", LABEL_ROLE: "diff",
                                            LABEL_INSTANCE: inst.id, LABEL_TEMPLATE: tpl.name})
            app.store.save_instance(inst)
            created.append(inst)
    return created


# ---- 起動 ----

def resolve_image(app: "App", tpl: Template) -> str:
    """雛形を作ったときと同じイメージを使う（タグが更新されていても中身を固定する）。"""
    if tpl.image_id and app.docker.image_id(tpl.image_id):
        return tpl.image_id
    if not tpl.image:
        raise DroidForkError(f"テンプレート「{tpl.name}」のイメージ情報がありません。")
    app.console.step(f"イメージ {tpl.image} を取得します")
    app.docker.pull(tpl.image)
    image_id = app.docker.image_id(tpl.image)
    if image_id is None or (tpl.image_id and image_id != tpl.image_id):
        raise DroidForkError(
            f"テンプレート「{tpl.name}」を作成したときのイメージが見つかりません（タグ {tpl.image} の中身が変わっています）。",
            hint=f"インスタンスを削除して作り直してください: droidfork rm -t {tpl.name} → "
                 f"droidfork template build {tpl.name} --force",
        )
    return image_id


def instance_run_spec(app: "App", inst: Instance, tpl: Template, image: str, use_memfd: bool) -> RunSpec:
    cfg = app.cfg
    options = BootOptions(
        display=inst.display,
        gpu_mode=cfg.gpu_mode,
        use_memfd=use_memfd,
        overlay=True,
        serialno=inst.serialno,
        props=device_props(cfg.manufacturer, cfg.model),
        dns=list(cfg.dns),
    )
    return RunSpec(
        name=container_name(inst.id),
        image=image,
        labels={LABEL_MANAGED: "1", LABEL_ROLE: ROLE_INSTANCE, LABEL_INSTANCE: inst.id, LABEL_TEMPLATE: tpl.name},
        bind_host=cfg.adb_bind,
        host_port=inst.adb_port,
        mounts=[
            Mount(base_volume_name(tpl.name), DATA_BASE, readonly=cfg.base_readonly),
            Mount(diff_volume_name(inst.id), DATA_DIFF),
        ],
        boot_args=boot_args(options),
        mac=inst.mac,
    )


def _run_error(exc: DroidForkError, inst: Instance) -> DroidForkError:
    text = str(exc).lower()
    if "port is already allocated" in text or "address already in use" in text:
        return DroidForkError(
            f"{inst.id}: ADB ポート {inst.adb_port} が他のプログラムに使われています。",
            hint=f"そのポートを空けるか、`droidfork rm {inst.id}` で削除してから作り直してください。",
        )
    return DroidForkError(f"{inst.id}: {exc}", hint=exc.hint)


def start_instances(
    app: "App",
    instances: Sequence[Instance],
    *,
    wait: bool = True,
    timeout: float | None = None,
) -> dict[str, object]:
    """起動する。戻り値は ID → 起動秒数 / 状態の文字列 / エラー。"""
    app.docker.ensure_daemon()
    states = container_states(app)
    use_memfd = app.use_memfd()
    images: dict[str, str] = {}
    templates: dict[str, Template] = {}
    results: dict[str, object] = {}
    targets: list[BootTarget] = []
    for inst in instances:
        name, addr = container_name(inst.id), instance_addr(app, inst)
        state = states.get(name)
        if state == "running":
            with contextlib.suppress(DroidForkError):
                app.adb.connect(addr)
            results[inst.id] = "起動済み"
            continue
        if state is not None:
            app.docker.remove([name])  # 異常終了したコンテナの残骸
        try:
            tpl = templates.get(inst.template) or app.store.load_template(inst.template)
            templates[tpl.name] = tpl
            if tpl.name not in images:
                if not app.docker.volume_exists(base_volume_name(tpl.name)):
                    raise DroidForkError(
                        f"テンプレート「{tpl.name}」の共有層（ボリューム {base_volume_name(tpl.name)}）が見つかりません。",
                        hint=f"droidfork rm -t {tpl.name} → droidfork template build {tpl.name} --force で作り直してください。",
                    )
                images[tpl.name] = resolve_image(app, tpl)
            diff = diff_volume_name(inst.id)
            if not app.docker.volume_exists(diff):
                app.docker.volume_create(diff, {LABEL_MANAGED: "1", LABEL_ROLE: "diff",
                                                LABEL_INSTANCE: inst.id, LABEL_TEMPLATE: tpl.name})
            spec = instance_run_spec(app, inst, tpl, images[tpl.name], use_memfd)
            app.console.info(f"{inst.id}: 起動します（adb {addr}）")
            started = app.clock()
            app.docker.run(docker_run_args(spec))
        except DroidForkError as exc:
            results[inst.id] = _run_error(exc, inst)
            continue
        inst.last_started_at = now_iso()
        app.store.save_instance(inst)
        targets.append(BootTarget(inst.id, addr, name, started))

    if targets and wait:
        app.console.step(f"{len(targets)} 台の起動完了を待っています")
        booted = wait_for_boot_many(app, targets, timeout or app.cfg.boot_timeout)
        for key, value in booted.items():
            if isinstance(value, float):
                inst = app.store.load_instance(key)
                inst.last_boot_seconds = value
                app.store.save_instance(inst)
            results[key] = value
    else:
        for target in targets:
            results[target.key] = "起動処理中"
    return results


# ---- 停止・リセット・削除 ----

def stop_instances(app: "App", instances: Sequence[Instance]) -> list[str]:
    app.docker.ensure_daemon()
    states = container_states(app)
    names = []
    for inst in instances:
        name = container_name(inst.id)
        state = states.get(name)
        if state is None:
            continue
        if state == "running":
            addr = instance_addr(app, inst)
            with contextlib.suppress(DroidForkError):
                if app.adb.connect(addr):
                    app.adb.shell(addr, "sync", check=False, timeout=15)  # 書き込み途中のデータを差分層へ
                app.adb.disconnect(addr)
        names.append(name)
    if names:
        app.docker.stop(names)
        app.docker.remove(names)
    return names


def reset_instances(app: "App", instances: Sequence[Instance], *, restart: bool = True) -> dict[str, object]:
    """差分層を空にして雛形の状態に戻す。シリアル・MAC・ポートはそのまま。"""
    states = container_states(app)
    was_running = [i for i in instances if states.get(container_name(i.id)) == "running"]
    stop_instances(app, instances)
    for inst in instances:
        diff = diff_volume_name(inst.id)
        app.docker.volume_rm(diff)
        app.docker.volume_create(diff, {LABEL_MANAGED: "1", LABEL_ROLE: "diff",
                                        LABEL_INSTANCE: inst.id, LABEL_TEMPLATE: inst.template})
        inst.last_boot_seconds = None
        app.store.save_instance(inst)
    if restart and was_running:
        return start_instances(app, was_running)
    return {}


def remove_instances(app: "App", instances: Sequence[Instance]) -> None:
    stop_instances(app, instances)
    with app.store.lock():
        for inst in instances:
            app.docker.volume_rm(diff_volume_name(inst.id))
            app.store.remove_instance_file(inst.id)


# ---- 一覧・確認 ----

def instance_rows(app: "App", instances: Sequence[Instance]) -> list[list[str]]:
    try:
        states: dict[str, str] | None = container_states(app)
    except DroidForkError:
        states = None
    try:
        adb_states = {d.serial: d.state for d in app.adb.devices()}
    except DroidForkError:
        adb_states = {}
    rows = []
    for inst in instances:
        state = states.get(container_name(inst.id)) if states is not None else "?"
        label = "不明" if state == "?" else STATE_LABELS.get(state, state or "停止")
        addr = instance_addr(app, inst)
        adb_state = adb_states.get(addr, "未接続") if state == "running" else "-"
        boot = f"{inst.last_boot_seconds:.0f}秒" if inst.last_boot_seconds else "-"
        rows.append([inst.id, inst.template, label, addr, adb_state, inst.serialno, inst.display.label(), boot])
    return rows


INSTANCE_HEADERS = ["ID", "テンプレート", "状態", "ADB", "ADB状態", "シリアル", "画面", "前回起動"]


def running(app: "App", instances: Sequence[Instance]) -> list[Instance]:
    states = container_states(app)
    return [i for i in instances if states.get(container_name(i.id)) == "running"]


def connect_instances(app: "App", instances: Sequence[Instance]) -> list[tuple[str, str, bool]]:
    result = []
    for inst in running(app, instances):
        addr = instance_addr(app, inst)
        result.append((inst.id, addr, app.adb.connect(addr)))
    return result


def collect_ids(app: "App", instances: Sequence[Instance]) -> list[dict[str, object]]:
    """起動中のインスタンスから識別子を読み、重複がないか調べる（企画書8章の確認用）。"""
    rows: list[dict[str, object]] = []
    for inst in running(app, instances):
        addr = instance_addr(app, inst)
        app.adb.connect(addr)

        def sh(command: str, addr: str = addr) -> str:
            return app.adb.shell(addr, command, check=False, timeout=20).strip()

        rows.append({
            "id": inst.id,
            "serialno": sh("getprop ro.serialno"),
            # shell から見た Android ID。アプリごとの値は同じ鍵から作られるので、ここが重複しなければよい
            "android_id": sh("settings get secure android_id"),
            "mac": sh("cat /sys/class/net/eth0/address"),
            "model": sh("getprop ro.product.model"),
            "duplicates": [],
        })
    for key in ("serialno", "android_id", "mac"):
        counts = Counter(r[key] for r in rows if r[key] and r[key] != "null")
        for r in rows:
            if r[key] and counts.get(r[key], 0) > 1:
                r["duplicates"].append(key)  # type: ignore[union-attr]
    return rows


def bulk_install(app: "App", instances: Sequence[Instance], paths: Sequence[Path]) -> list[tuple[str, str, bool, str]]:
    """APKを起動中の全台へ一括導入する。同じ端末へは順番に、端末どうしは並列に入れる。"""
    groups = apk_groups(paths)
    targets = running(app, instances)
    if not targets:
        raise DroidForkError("起動中のインスタンスがありません。", hint="`droidfork start` で起動してから実行してください。")

    def work(inst: Instance) -> list[tuple[str, str, bool, str]]:
        addr = instance_addr(app, inst)
        app.adb.connect(addr)
        out = []
        for label, files in groups:
            ok, message = app.adb.install(addr, files)
            out.append((inst.id, label, ok, message))
        return out

    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        results = list(pool.map(work, targets))
    return [row for chunk in results for row in chunk]


def open_screens(app: "App", instances: Sequence[Instance], extra_args: Sequence[str] = ()) -> list[str]:
    """scrcpy で画面を開く（インスタンスごとに1ウィンドウ）。"""
    binary = app.cfg.scrcpy
    if app.runner.which(binary) is None:
        raise not_found_error(binary)
    targets = running(app, instances)
    if not targets:
        raise DroidForkError("起動中のインスタンスがありません。")
    opened = []
    for inst in targets:
        addr = instance_addr(app, inst)
        app.adb.connect(addr)
        app.runner.spawn([binary, "-s", addr, "--window-title", f"DroidFork {inst.id}", *extra_args])
        opened.append(inst.id)
    return opened
