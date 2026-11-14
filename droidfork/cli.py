"""コマンドライン（droidfork <コマンド>）。"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Callable, Sequence

from . import __version__
from .app import App
from .capture import add_apks, capture, clone_template, new_template, remove_apk
from .config import load_config
from .hostcheck import NG, run_checks
from .instances import (
    INSTANCE_HEADERS, bulk_install, collect_ids, connect_instances, create_instances, instance_rows,
    open_screens, remove_instances, reset_instances, select_instances, set_limits, start_instances,
    stop_instances,
)
from .schedule import (
    ACTIONS, add_schedule, install_timer, linger_hint, list_schedules, remove_schedule, run_due,
    set_enabled, uninstall_timer,
)
from .snapshots import create_snapshot, remove_snapshots, restore_snapshot, snapshot_volume_name
from .usb import attach as usb_attach, detach as usb_detach, list_devices as usb_list
from .redroid import adb_address, container_name
from .stats import collect_stats, render_stats
from .store import TEMPLATE_STATE_LABELS
from .template import build_template, failure_hint, remove_template
from .util import Console, DroidForkError, Runner, format_bytes, format_table

EPILOG = """\
基本の流れ（3ステップ）:
  1. 実機をUSBでつなぎ、USBデバッグを許可する
  2. droidfork up -n 5        取り込み → 雛形作成 → 5台複製 → 起動
  3. adb devices              5台が別々の端末として並ぶ

個別の手順:
  droidfork capture → droidfork template build <名前> → droidfork create <名前> -n 5 → droidfork start --all
"""


# ---- 共通の表示 ----

def print_start_results(app: App, results: dict[str, object]) -> int:
    rows, errors = [], []
    for key, value in results.items():
        if isinstance(value, float):
            text = f"起動完了（{value:.0f}秒）"
        elif isinstance(value, DroidForkError):
            text = "失敗"
            errors.append(value)
        else:
            text = str(value)
        rows.append([key, text])
    if rows:
        app.console.print(format_table(["ID", "結果"], rows))
    for err in errors:
        app.console.warn(str(err))
        if err.hint:
            app.console.info(f"ヒント: {err.hint}")
    return 1 if errors else 0


def print_instances(app: App, instances) -> None:
    if not instances:
        app.console.print("インスタンスはまだありません。`droidfork up -n 3` などで作成できます。")
        return
    app.console.print(format_table(INSTANCE_HEADERS, instance_rows(app, instances)))


def _targets(app: App, args: argparse.Namespace, *, default_all: bool = False):
    return select_instances(app, args.ids, all_=args.all, template=args.template, default_all=default_all)


# ---- コマンド ----

def cmd_doctor(app: App, args: argparse.Namespace) -> int:
    checks = run_checks(app)
    app.console.print(format_table(["項目", "結果", "内容"], [[c.name, c.status, c.detail] for c in checks]))
    hints = [c for c in checks if c.hint and c.status != "OK"]
    if hints:
        app.console.print("")
        for c in hints:
            app.console.print(f"・{c.name}: {c.hint}")
    failed = [c for c in checks if c.status == NG]
    if failed:
        app.console.print("")
        app.console.print(f"NG が {len(failed)} 件あります。解消してから使ってください。")
        return 1
    return 0


def cmd_devices(app: App, args: argparse.Namespace) -> int:
    managed = {adb_address(app.cfg.adb_bind, i.adb_port): i.id for i in app.store.list_instances()}
    rows = []
    for d in app.adb.devices():
        if d.serial in managed:
            kind = f"DroidFork（{managed[d.serial]}）"
        elif d.is_emulator:
            kind = "エミュレータ"
        elif d.is_usb:
            kind = "実機（USB）"
        else:
            kind = "その他（ネットワーク）"
        rows.append([d.serial, d.state, d.model or "-", kind])
    if not rows:
        app.console.print("adb に接続された端末はありません。")
        return 0
    app.console.print(format_table(["シリアル", "状態", "機種", "種別"], rows))
    return 0


def cmd_capture(app: App, args: argparse.Namespace) -> int:
    tpl = capture(app, serial=args.serial, name=args.name, include=args.include or (),
                  exclude=args.exclude or (), with_apks=not args.no_apks, android=args.android)
    app.console.print(f"次の手順: droidfork template build {tpl.name}")
    return 0


def cmd_template_list(app: App, args: argparse.Namespace) -> int:
    templates = app.store.list_templates()
    if not templates:
        app.console.print("テンプレートはまだありません。`droidfork capture` で実機から取り込めます。")
        return 0
    counts: dict[str, int] = {}
    for inst in app.store.list_instances():
        counts[inst.template] = counts.get(inst.template, 0) + 1
    rows = [[t.name, TEMPLATE_STATE_LABELS.get(t.state, t.state), t.android_version, t.display.label(),
             len(t.packages), counts.get(t.name, 0), t.source.get("model") or "-"] for t in templates]
    app.console.print(format_table(["名前", "状態", "Android", "画面", "アプリ", "台数", "取り込み元（メモ）"], rows))
    return 0


def cmd_template_show(app: App, args: argparse.Namespace) -> int:
    t = app.store.load_template(args.name)
    if args.json:
        app.console.print(json.dumps(t.to_dict(), ensure_ascii=False, indent=2))
        return 0
    settings = ", ".join(f"{ns}.{k}={v}" for ns, kv in t.settings.items() for k, v in kv.items()) or "-"
    lines = [
        ["名前", t.name],
        ["状態", TEMPLATE_STATE_LABELS.get(t.state, t.state)],
        ["Android（イメージ）", t.android_version],
        ["イメージ", f"{t.image or '-'}" + (f"（{t.image_id[:19]}）" if t.image_id else "")],
        ["画面", t.display.label()],
        ["言語 / タイムゾーン", f"{t.locale or '-'} / {t.timezone or '-'}"],
        ["表示設定", settings],
        ["取り込み元（メモ）", " ".join(str(v) for v in (t.source.get("manufacturer"), t.source.get("model"),
                                                    f"Android {t.source.get('android_release')}" if t.source.get("android_release") else None) if v) or "-"],
        ["作成日時", t.built_at or "-"],
        ["インスタンス", f"{len(app.store.list_instances(template=t.name))} 台"],
    ]
    app.console.print(format_table(["項目", "値"], lines))
    if t.packages:
        app.console.print("")
        rows = []
        for p in t.packages:
            result = t.install_results.get(p.name)
            status = "-" if result is None else ("導入済み" if result == "ok" else f"失敗: {result}")
            rows.append([p.name, p.version_name or "-", len(p.files), status])
        app.console.print(format_table(["アプリ", "バージョン", "APK数", "雛形への導入"], rows))
        hints = sorted({h for h in (failure_hint(v) for v in t.install_results.values() if v != "ok") if h})
        for h in hints:
            app.console.print(f"・{h}")
    if t.notes:
        app.console.print("")
        app.console.print("注記:")
        for note in t.notes:
            app.console.print(f"・{note}")
    return 0


def cmd_template_new(app: App, args: argparse.Namespace) -> int:
    tpl = new_template(app, args.name, android=args.android, size=args.size, dpi=args.dpi,
                       locale=args.locale, timezone=args.timezone, apks=[Path(p) for p in args.apk or []])
    app.console.print(f"次の手順: droidfork template build {tpl.name}")
    return 0


def cmd_template_build(app: App, args: argparse.Namespace) -> int:
    tpl = build_template(app, args.name, image=args.image, force=args.force, keep_on_error=args.keep_on_error)
    app.console.print(f"次の手順: droidfork create {tpl.name} -n 3")
    return 0


def cmd_template_rm(app: App, args: argparse.Namespace) -> int:
    users = app.store.list_instances(template=args.name)
    app.store.load_template(args.name)
    what = f"テンプレート「{args.name}」" + (f"と、それを使うインスタンス {len(users)} 台" if users and args.force else "")
    app.confirm(f"{what}を削除します。よろしいですか？", args.yes)
    removed = remove_template(app, args.name, force=args.force)
    app.console.print(f"テンプレート「{args.name}」を削除しました" + (f"（インスタンス {removed} 台も削除）" if removed else "") + "。")
    return 0


def cmd_create(app: App, args: argparse.Namespace) -> int:
    created = create_instances(app, args.template_name, args.count, scale=args.scale, fps=args.fps,
                               cpus=args.cpus, memory=args.memory)
    app.console.step(f"{len(created)} 台を作成しました（ディスクはコピーしていません）")
    print_instances(app, created)
    app.console.print(f"次の手順: droidfork start -t {args.template_name}")
    return 0


def cmd_up(app: App, args: argparse.Namespace) -> int:
    name = args.template
    if name and app.store.template_exists(name):
        tpl = app.store.load_template(name)
    else:
        tpl = capture(app, serial=args.serial, name=name, include=args.include or (),
                      exclude=args.exclude or (), android=args.android)
    if not tpl.sealed:
        tpl = build_template(app, tpl.name, force=tpl.state == "failed")
    created = create_instances(app, tpl.name, args.count, scale=args.scale, fps=args.fps,
                               cpus=args.cpus, memory=args.memory)
    app.console.step(f"{len(created)} 台を作成しました。起動します")
    results = start_instances(app, created, wait=not args.no_wait, timeout=args.timeout)
    code = print_start_results(app, results)
    app.console.print("")
    print_instances(app, [app.store.load_instance(i.id) for i in created])  # 起動時間を記録した後の値で表示
    app.console.print("")
    app.console.print("各台は adb で別々の端末として見えます（adb devices）。画面は droidfork screen <ID> で開けます。")
    return code


def cmd_list(app: App, args: argparse.Namespace) -> int:
    instances = app.store.list_instances(template=args.template)
    print_instances(app, instances)
    return 0


def cmd_start(app: App, args: argparse.Namespace) -> int:
    instances = _targets(app, args)
    return print_start_results(app, start_instances(app, instances, wait=not args.no_wait, timeout=args.timeout))


def cmd_stop(app: App, args: argparse.Namespace) -> int:
    stopped = stop_instances(app, _targets(app, args))
    app.console.print(f"{len(stopped)} 台を停止しました。")
    return 0


def cmd_restart(app: App, args: argparse.Namespace) -> int:
    instances = _targets(app, args)
    stop_instances(app, instances)
    return print_start_results(app, start_instances(app, instances, wait=not args.no_wait, timeout=args.timeout))


def cmd_reset(app: App, args: argparse.Namespace) -> int:
    instances = _targets(app, args)
    if not instances:
        app.console.print("対象のインスタンスがありません。")
        return 0
    app.confirm(f"{len(instances)} 台の差分（アプリ内データ・ログインなど）を消して雛形の状態に戻します。よろしいですか？", args.yes)
    results = reset_instances(app, instances, restart=not args.no_start)
    app.console.print(f"{len(instances)} 台をリセットしました（シリアル・MAC・ポートはそのまま、Android ID は次回起動で作り直されます）。")
    return print_start_results(app, results) if results else 0


def cmd_rm(app: App, args: argparse.Namespace) -> int:
    instances = _targets(app, args)
    if not instances:
        app.console.print("対象のインスタンスがありません。")
        return 0
    app.confirm(f"{len(instances)} 台（{', '.join(i.id for i in instances[:5])}{' ほか' if len(instances) > 5 else ''}）を削除します。よろしいですか？", args.yes)
    remove_instances(app, instances)
    app.console.print(f"{len(instances)} 台を削除しました。")
    return 0


def cmd_connect(app: App, args: argparse.Namespace) -> int:
    rows = connect_instances(app, _targets(app, args, default_all=True))
    if not rows:
        app.console.print("起動中のインスタンスがありません。")
        return 0
    app.console.print(format_table(["ID", "ADB", "接続"], [[i, a, "OK" if ok else "失敗"] for i, a, ok in rows]))
    return 0 if all(ok for _, _, ok in rows) else 1


def cmd_ids(app: App, args: argparse.Namespace) -> int:
    rows = collect_ids(app, _targets(app, args, default_all=True))
    if not rows:
        app.console.print("起動中のインスタンスがありません。")
        return 0
    if args.json:
        app.console.print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        table = [[r["id"], r["model"], r["serialno"], r["android_id"], r["mac"],
                  "重複: " + ",".join(r["duplicates"]) if r["duplicates"] else "OK"] for r in rows]  # type: ignore[arg-type]
        app.console.print(format_table(["ID", "機種名", "シリアル", "Android ID", "MAC", "判定"], table))
    if any(r["duplicates"] for r in rows):
        app.console.warn("重複した識別子があります。テンプレートの封印が効いていない可能性があります。")
        return 1
    return 0


def cmd_install(app: App, args: argparse.Namespace) -> int:
    instances = _targets(app, args, default_all=True)
    results = bulk_install(app, instances, [Path(p) for p in args.apks])
    app.console.print(format_table(["ID", "APK", "結果"], [[i, label, "成功" if ok else f"失敗: {msg}"] for i, label, ok, msg in results]))
    return 0 if all(ok for _, _, ok, _ in results) else 1


def cmd_screen(app: App, args: argparse.Namespace) -> int:
    extra = shlex.split(args.scrcpy_args) if args.scrcpy_args else []
    opened = open_screens(app, _targets(app, args, default_all=False), extra)
    app.console.print(f"{len(opened)} 台の画面を開きました: {', '.join(opened)}")
    return 0


def cmd_logs(app: App, args: argparse.Namespace) -> int:
    inst = app.store.load_instance(args.id)
    argv = [app.cfg.docker, "logs", "--tail", str(args.tail)]
    if args.follow:
        argv.append("-f")
    argv.append(container_name(inst.id))
    return app.runner.passthrough(argv)


def cmd_stats(app: App, args: argparse.Namespace) -> int:
    data = collect_stats(app)
    app.console.print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render_stats(data))
    return 0


def cmd_limit(app: App, args: argparse.Namespace) -> int:
    if args.cpus is None and args.memory is None and not args.no_cpus and not args.no_memory:
        rows = [[i.id, f"{i.cpus:g}" if i.cpus else "-", i.memory or "-"] for i in _targets(app, args, default_all=True)]
        app.console.print(format_table(["ID", "CPU上限", "メモリ上限"], rows))
        return 0
    results = set_limits(app, _targets(app, args), cpus=args.cpus, memory=args.memory,
                         clear_cpus=args.no_cpus, clear_memory=args.no_memory)
    app.console.print(format_table(["ID", "結果"], [[k, v] for k, v in results.items()]))
    return 0


def cmd_template_clone(app: App, args: argparse.Namespace) -> int:
    tpl = clone_template(app, args.source, args.name)
    app.console.print(f"テンプレート「{tpl.name}」を作りました（アプリ {len(tpl.packages)} 個）。"
                      f"次の手順: droidfork template build {tpl.name}")
    return 0


def cmd_template_add_apk(app: App, args: argparse.Namespace) -> int:
    entries = add_apks(app, args.name, [Path(p) for p in args.apks])
    app.console.print(f"{len(entries)} 個のアプリを追加しました: {', '.join(e.name for e in entries)}")
    app.console.print(f"反映するには: droidfork template build {args.name} --force")
    return 0


def cmd_template_rm_apk(app: App, args: argparse.Namespace) -> int:
    remove_apk(app, args.name, args.package)
    app.console.print(f"アプリ「{args.package}」を外しました。反映するには: droidfork template build {args.name} --force")
    return 0


def cmd_snapshot_create(app: App, args: argparse.Namespace) -> int:
    snap = create_snapshot(app, app.store.load_instance(args.id), args.name, args.note)
    app.console.print(f"スナップショット「{snap.name}」を保存しました（{snap.source} の差分）。")
    return 0


def cmd_snapshot_list(app: App, args: argparse.Namespace) -> int:
    snaps = app.store.list_snapshots(template=args.template)
    if not snaps:
        app.console.print("スナップショットはまだありません。`droidfork snapshot create <ID>` で保存できます。")
        return 0
    try:
        sizes = app.docker.volume_sizes()
    except DroidForkError:
        sizes = {}
    rows = [[s.name, s.template, s.source, s.created_at, format_bytes(sizes.get(snapshot_volume_name(s.name))), s.note or ""]
            for s in snaps]
    app.console.print(format_table(["名前", "テンプレート", "保存元", "日時", "サイズ", "メモ"], rows))
    return 0


def cmd_snapshot_restore(app: App, args: argparse.Namespace) -> int:
    snap = app.store.load_snapshot(args.snapshot)
    if args.ids or args.template or args.all:
        targets = _targets(app, args)
    else:
        targets = [app.store.load_instance(snap.source)]
    others = [t.id for t in targets if t.id != snap.source]
    message = f"{len(targets)} 台（{', '.join(t.id for t in targets)}）の今の差分を、スナップショット「{snap.name}」で置き換えます。"
    if others:
        message += " 保存元以外の台では Android ID を作り直します。"
    app.confirm(message + "よろしいですか？", args.yes)
    results = restore_snapshot(app, snap, targets)
    app.console.print(f"{len(targets)} 台に戻しました。")
    return print_start_results(app, results) if results else 0


def cmd_snapshot_rm(app: App, args: argparse.Namespace) -> int:
    snaps = [app.store.load_snapshot(n) for n in dict.fromkeys(args.names)]
    app.confirm(f"スナップショット {len(snaps)} 個を削除します。よろしいですか？", args.yes)
    app.docker.ensure_daemon()
    remove_snapshots(app, snaps)
    app.console.print(f"{len(snaps)} 個を削除しました。")
    return 0


def cmd_schedule_add(app: App, args: argparse.Namespace) -> int:
    s = add_schedule(app, action=args.action, at=args.at, days=args.days, template=args.template,
                     ids=args.ids, all_=args.all)
    app.console.print(f"予定 {s.id} を追加しました: {s.days_label()} {s.at} に {s.target_label()} を{ACTIONS[s.action]}")
    if not app.cfg.schedules_path.with_name(".timer-installed").exists():
        app.console.print("予定を自動で実行するには `droidfork schedule install` を一度実行してください。")
    return 0


def cmd_schedule_list(app: App, args: argparse.Namespace) -> int:
    items = list_schedules(app)
    if not items:
        app.console.print("予定はありません。`droidfork schedule add --at 09:00 --action start -t <テンプレート>` で追加できます。")
        return 0
    rows = [[s.id, "有効" if s.enabled else "無効", s.days_label(), s.at, ACTIONS[s.action], s.target_label(),
             f"{s.last_run or '-'} {s.last_result or ''}".strip()] for s in items]
    app.console.print(format_table(["ID", "状態", "曜日", "時刻", "動作", "対象", "前回"], rows))
    return 0


def cmd_schedule_rm(app: App, args: argparse.Namespace) -> int:
    for sid in args.schedule_ids:
        remove_schedule(app, sid)
    app.console.print(f"{len(args.schedule_ids)} 件の予定を削除しました。")
    return 0


def cmd_schedule_enable(app: App, args: argparse.Namespace) -> int:
    set_enabled(app, args.schedule_id, args.enabled)
    app.console.print(f"予定 {args.schedule_id} を{'有効' if args.enabled else '無効'}にしました。")
    return 0


def cmd_schedule_run_due(app: App, args: argparse.Namespace) -> int:
    if not args.loop:
        run_due(app)
        return 0
    app.console.step("予定の確認を続けます（Ctrl+C で終了）")
    while True:
        try:
            run_due(app)
        except DroidForkError as exc:
            app.console.warn(str(exc))
        app.sleep(30)


def cmd_schedule_install(app: App, args: argparse.Namespace) -> int:
    unit_dir = install_timer(app)
    app.cfg.schedules_path.parent.mkdir(parents=True, exist_ok=True)
    app.cfg.schedules_path.with_name(".timer-installed").write_text(str(unit_dir))
    app.console.print(f"1分ごとに予定を確認するタイマーを登録しました（{unit_dir}）。")
    hint = linger_hint()
    if hint:
        app.console.print(hint)
    return 0


def cmd_schedule_uninstall(app: App, args: argparse.Namespace) -> int:
    uninstall_timer(app)
    app.cfg.schedules_path.with_name(".timer-installed").unlink(missing_ok=True)
    app.console.print("タイマーを止めました（予定そのものは残っています）。")
    return 0


def cmd_usb_list(app: App, args: argparse.Namespace) -> int:
    devices = usb_list(app)
    if not devices:
        app.console.print("USB機器が見つかりません。")
        return 0
    rows = [[d.busid, d.vid_pid, d.name, d.state_label, "○" if d.looks_android else ""] for d in devices]
    app.console.print(format_table(["BUSID", "VID:PID", "機器", "状態", "Android?"], rows))
    app.console.print("実機をつなぐには: droidfork usb attach <BUSID>")
    return 0


def cmd_usb_attach(app: App, args: argparse.Namespace) -> int:
    device = usb_attach(app, args.busid)
    app.console.print(f"{device.name} を WSL へつなぎました。`droidfork devices` で確認できます。")
    return 0


def cmd_usb_detach(app: App, args: argparse.Namespace) -> int:
    usb_detach(app, args.busid)
    app.console.print(f"{args.busid} を Windows へ戻しました。")
    return 0


def cmd_ui(app: App, args: argparse.Namespace) -> int:
    from .config import LOOPBACK_BINDS
    from .ui import make_server, serve
    from .usb import open_url

    host = args.host
    port = args.port or app.cfg.ui_port
    token = args.token or os.environ.get("DROIDFORK_UI_TOKEN") or None
    if host not in LOOPBACK_BINDS:
        app.console.warn(f"管理画面を {host} で公開します。同じネットワークの他の機器からも開けます（トークンは必要）。")
    try:
        server = make_server(app.with_console, host, port, token)
    except OSError as exc:
        raise DroidForkError(f"ポート {port} で待ち受けできません: {exc}", hint="--port で別の番号を指定してください。") from None
    shown = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = f"http://{shown}:{server.port}/?token={server.state.token}"
    app.console.print(f"管理画面: {url}")
    app.console.print("終了するには Ctrl+C を押してください。")
    if args.open:
        open_url(app, url)
    serve(server, app.console)
    return 0


def cmd_config(app: App, args: argparse.Namespace) -> int:
    app.console.print(f"# 設定ファイル: {app.cfg.config_path}")
    data = app.cfg.to_dict()
    data.pop("home", None)
    app.console.print(json.dumps({"home": str(app.cfg.home), **data}, ensure_ascii=False, indent=2))
    return 0


# ---- 引数の定義 ----

def _add_selection(p: argparse.ArgumentParser, *, default_all: bool = False) -> None:
    p.add_argument("ids", nargs="*", metavar="ID", help="インスタンスID（複数可）")
    p.add_argument("-t", "--template", help="このテンプレートのインスタンスすべて")
    p.add_argument("--all", action="store_true",
                   help="すべてのインスタンス" + ("（省略時もすべて）" if default_all else ""))


def _add_capture_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("-s", "--serial", help="取り込み元の端末（複数つないでいるとき）")
    p.add_argument("--include", action="append", metavar="パターン", help="取り込むアプリ（例: 'com.example.*'、複数可）")
    p.add_argument("--exclude", action="append", metavar="パターン", help="取り込まないアプリ（複数可）")
    p.add_argument("--android", metavar="VER", help="使う Android のバージョン（既定: 実機と同じ）")


def _add_display_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scale", type=float, default=1.0,
                   help="解像度とDPIの倍率（0.2〜1.0）。0.5 にするとメモリを節約できます")
    p.add_argument("--fps", type=int, help="画面の更新頻度（既定: 設定の fps）")
    p.add_argument("--cpus", type=float, help="1台あたりのCPU上限（例: 1.5）")
    p.add_argument("--memory", help="1台あたりのメモリ上限（例: 2g）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="droidfork",
        description="実機1台を雛形に、仮想Android端末をN台起動します（コンテナ型Android＋共有層＋差分層）。",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--home", help="保存先（既定: ~/.local/share/droidfork、環境変数 DROIDFORK_HOME）")
    parser.add_argument("-v", "--verbose", action="store_true", help="実行する docker / adb コマンドを表示する")
    parser.add_argument("-q", "--quiet", action="store_true", help="進行状況を表示しない")
    parser.add_argument("--version", action="version", version=f"droidfork {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<コマンド>")

    def add(name: str, handler: Callable, help_text: str, aliases: Sequence[str] = ()) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text, description=help_text, aliases=list(aliases))
        p.set_defaults(handler=handler)
        return p

    add("doctor", cmd_doctor, "ホスト環境を確認する（Docker・binder・overlayfs・adb など）")
    add("devices", cmd_devices, "adb に接続された端末を一覧する")

    p = add("up", cmd_up, "取り込み → 雛形作成 → N台複製 → 起動 をまとめて行う")
    p.add_argument("-n", "--count", type=int, default=3, help="台数（既定: 3）")
    p.add_argument("-t", "--template", help="使うテンプレート（無ければこの名前で実機から取り込む）")
    _add_capture_options(p)
    _add_display_options(p)
    p.add_argument("--no-wait", action="store_true", help="起動完了を待たない")
    p.add_argument("--timeout", type=float, help="起動完了を待つ秒数")

    p = add("capture", cmd_capture, "USB接続した実機からアプリ構成と画面・地域設定を取り込む")
    p.add_argument("--name", help="テンプレート名（既定: 機種名から自動）")
    p.add_argument("--no-apks", action="store_true", help="APKを取り込まない（設定だけ）")
    _add_capture_options(p)

    template_parser = add("template", None, "テンプレート（雛形）の管理", aliases=["tpl"])
    tsub = template_parser.add_subparsers(dest="template_command", metavar="<操作>")
    template_parser.set_defaults(handler=lambda app, args: (template_parser.print_help(), 0)[1])

    tp = tsub.add_parser("list", aliases=["ls"], help="一覧")
    tp.set_defaults(handler=cmd_template_list)
    tp = tsub.add_parser("show", help="詳細（導入結果・注記を含む）")
    tp.add_argument("name")
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(handler=cmd_template_show)
    tp = tsub.add_parser("build", help="雛形を作成する（ベースAndroidにAPKと設定を適用して封印）")
    tp.add_argument("name")
    tp.add_argument("--image", help="使うイメージ（既定: redroid/redroid:<バージョン>-latest）")
    tp.add_argument("--force", action="store_true", help="作成済みでも作り直す")
    tp.add_argument("--keep-on-error", action="store_true", help="失敗したとき調査用にコンテナを残す")
    tp.set_defaults(handler=cmd_template_build)
    tp = tsub.add_parser("new", help="実機なしで雛形を定義する（手元のAPKと指定値から）")
    tp.add_argument("name")
    tp.add_argument("--android", required=True, help="Android のバージョン（例: 14）")
    tp.add_argument("--size", default="720x1280", help="画面サイズ（既定: 720x1280）")
    tp.add_argument("--dpi", type=int, default=320, help="DPI（既定: 320）")
    tp.add_argument("--locale", help="言語（例: ja-JP）")
    tp.add_argument("--timezone", help="タイムゾーン（例: Asia/Tokyo）")
    tp.add_argument("--apk", action="append", metavar="PATH", help="APK、または分割APKのフォルダ（複数可）")
    tp.set_defaults(handler=cmd_template_new)
    tp = tsub.add_parser("clone", help="既存のテンプレートを元に新しいテンプレートを作る（版の管理）")
    tp.add_argument("source")
    tp.add_argument("name")
    tp.set_defaults(handler=cmd_template_clone)
    tp = tsub.add_parser("add-apk", help="テンプレートにAPKを追加する（作り直しが必要）")
    tp.add_argument("name")
    tp.add_argument("apks", nargs="+", metavar="APK", help="APK、または分割APKのフォルダ")
    tp.set_defaults(handler=cmd_template_add_apk)
    tp = tsub.add_parser("rm-apk", help="テンプレートからアプリを外す（作り直しが必要）")
    tp.add_argument("name")
    tp.add_argument("package")
    tp.set_defaults(handler=cmd_template_rm_apk)
    tp = tsub.add_parser("rm", help="削除する")
    tp.add_argument("name")
    tp.add_argument("--force", action="store_true", help="使っているインスタンスとスナップショットも一緒に削除する")
    tp.add_argument("-y", "--yes", action="store_true", help="確認しない")
    tp.set_defaults(handler=cmd_template_rm)

    p = add("create", cmd_create, "テンプレートから N 台を複製する（ディスクはコピーしないので一瞬）")
    p.add_argument("template_name", metavar="TEMPLATE")
    p.add_argument("-n", "--count", type=int, default=1, help="台数（既定: 1）")
    _add_display_options(p)

    p = add("list", cmd_list, "インスタンスを一覧する", aliases=["ls"])
    p.add_argument("-t", "--template", help="このテンプレートのものだけ")

    for name, handler, text in (("start", cmd_start, "起動する"), ("restart", cmd_restart, "再起動する")):
        p = add(name, handler, text)
        _add_selection(p)
        p.add_argument("--no-wait", action="store_true", help="起動完了を待たない")
        p.add_argument("--timeout", type=float, help="起動完了を待つ秒数")

    p = add("stop", cmd_stop, "停止する（差分は残る）")
    _add_selection(p)

    p = add("reset", cmd_reset, "差分を消して雛形の状態に戻す")
    _add_selection(p)
    p.add_argument("--no-start", action="store_true", help="起動中だったものも停止したままにする")
    p.add_argument("-y", "--yes", action="store_true", help="確認しない")

    p = add("rm", cmd_rm, "削除する（差分も消える）")
    _add_selection(p)
    p.add_argument("-y", "--yes", action="store_true", help="確認しない")

    p = add("connect", cmd_connect, "起動中のインスタンスを adb に接続し直す")
    _add_selection(p, default_all=True)

    p = add("ids", cmd_ids, "各台の識別子（シリアル・Android ID・MAC）を表示し、重複を調べる")
    _add_selection(p, default_all=True)
    p.add_argument("--json", action="store_true")

    p = add("install", cmd_install, "APKを起動中のインスタンスへ一括導入する")
    p.add_argument("apks", nargs="+", metavar="APK", help="APK、または分割APKのフォルダ")
    p.add_argument("--to", dest="ids", action="append", default=[], metavar="ID", help="導入先（省略時は起動中の全台）")
    p.add_argument("-t", "--template", help="このテンプレートのインスタンスだけ")
    p.set_defaults(all=False)

    p = add("screen", cmd_screen, "scrcpy で画面を開く")
    _add_selection(p)
    p.add_argument("--scrcpy-args", help="scrcpy に渡す追加の引数（例: \"--max-size 800\"）")

    p = add("logs", cmd_logs, "コンテナのログを表示する")
    p.add_argument("id", metavar="ID")
    p.add_argument("--tail", type=int, default=100)
    p.add_argument("-f", "--follow", action="store_true")

    p = add("stats", cmd_stats, "ディスク増分・メモリ使用量を実測する（PoC用）")
    p.add_argument("--json", action="store_true", help="JSONで出力する（記録用）")

    p = add("limit", cmd_limit, "台ごとのCPU・メモリ上限を表示・変更する")
    _add_selection(p)
    p.add_argument("--cpus", type=float, help="CPUの上限（例: 1.5）")
    p.add_argument("--memory", help="メモリの上限（例: 2g）")
    p.add_argument("--no-cpus", action="store_true", help="CPUの上限を外す")
    p.add_argument("--no-memory", action="store_true", help="メモリの上限を外す")

    snap_parser = add("snapshot", None, "スナップショット（台の状態の保存と復元）", aliases=["snap"])
    ssub = snap_parser.add_subparsers(dest="snapshot_command", metavar="<操作>")
    snap_parser.set_defaults(handler=lambda app, args: (snap_parser.print_help(), 0)[1])
    sp = ssub.add_parser("create", help="台の今の状態（差分）を保存する")
    sp.add_argument("id", metavar="ID")
    sp.add_argument("--name", help="名前（既定: ID-日時）")
    sp.add_argument("--note", help="メモ")
    sp.set_defaults(handler=cmd_snapshot_create)
    sp = ssub.add_parser("list", aliases=["ls"], help="一覧")
    sp.add_argument("-t", "--template", help="このテンプレートのものだけ")
    sp.set_defaults(handler=cmd_snapshot_list)
    sp = ssub.add_parser("restore", help="保存した状態に戻す（既定は保存元の台。同じテンプレートの別の台にも戻せる）")
    sp.add_argument("snapshot")
    _add_selection(sp)
    sp.add_argument("-y", "--yes", action="store_true", help="確認しない")
    sp.set_defaults(handler=cmd_snapshot_restore)
    sp = ssub.add_parser("rm", help="削除する")
    sp.add_argument("names", nargs="+", metavar="NAME")
    sp.add_argument("-y", "--yes", action="store_true", help="確認しない")
    sp.set_defaults(handler=cmd_snapshot_rm)

    sched_parser = add("schedule", None, "スケジュール起動（決まった時刻に起動・停止など）")
    csub = sched_parser.add_subparsers(dest="schedule_command", metavar="<操作>")
    sched_parser.set_defaults(handler=lambda app, args: (sched_parser.print_help(), 0)[1])
    cp = csub.add_parser("add", help="予定を追加する")
    cp.add_argument("--at", required=True, help="時刻（例: 09:00）")
    cp.add_argument("--action", required=True, choices=list(ACTIONS), help="start / stop / restart / reset")
    cp.add_argument("--days", default="daily", help="daily / weekdays / weekends / mon-fri / mon,wed,fri（既定: daily）")
    _add_selection(cp)
    cp.set_defaults(handler=cmd_schedule_add)
    cp = csub.add_parser("list", aliases=["ls"], help="一覧")
    cp.set_defaults(handler=cmd_schedule_list)
    cp = csub.add_parser("rm", help="削除する")
    cp.add_argument("schedule_ids", nargs="+", metavar="ID")
    cp.set_defaults(handler=cmd_schedule_rm)
    for name, enabled in (("enable", True), ("disable", False)):
        cp = csub.add_parser(name, help="有効にする" if enabled else "無効にする")
        cp.add_argument("schedule_id", metavar="ID")
        cp.set_defaults(handler=cmd_schedule_enable, enabled=enabled)
    cp = csub.add_parser("run-due", help="時刻が来た予定を実行する（タイマーから呼ぶ）")
    cp.add_argument("--loop", action="store_true", help="30秒ごとに確認し続ける")
    cp.set_defaults(handler=cmd_schedule_run_due)
    cp = csub.add_parser("install", help="予定を自動で実行するタイマー（systemd）を登録する")
    cp.set_defaults(handler=cmd_schedule_install)
    cp = csub.add_parser("uninstall", help="タイマーを止める")
    cp.set_defaults(handler=cmd_schedule_uninstall)

    usb_parser = add("usb", None, "WSL2: 実機を Windows から WSL へつなぐ（usbipd-win）")
    usub = usb_parser.add_subparsers(dest="usb_command", metavar="<操作>")
    usb_parser.set_defaults(handler=lambda app, args: (usb_parser.print_help(), 0)[1])
    up_ = usub.add_parser("list", aliases=["ls"], help="Windows につながった USB 機器を一覧する")
    up_.set_defaults(handler=cmd_usb_list)
    up_ = usub.add_parser("attach", help="機器を WSL へつなぐ（初回は Windows の権限確認が出ます）")
    up_.add_argument("busid", metavar="BUSID")
    up_.set_defaults(handler=cmd_usb_attach)
    up_ = usub.add_parser("detach", help="機器を Windows へ戻す")
    up_.add_argument("busid", metavar="BUSID")
    up_.set_defaults(handler=cmd_usb_detach)

    p = add("ui", cmd_ui, "ブラウザで使う管理画面を起動する")
    p.add_argument("--host", default="127.0.0.1", help="待ち受けるアドレス（既定: 127.0.0.1）")
    p.add_argument("--port", type=int, help="ポート（既定: 設定の ui_port = 8765）")
    p.add_argument("--token", help="URL のトークンを固定する（既定: 起動ごとに生成。環境変数 DROIDFORK_UI_TOKEN でも可）")
    p.add_argument("--open", action="store_true", help="ブラウザで開く")

    add("config", cmd_config, "現在の設定を表示する")
    return parser


def main(argv: Sequence[str] | None = None, *, app: App | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "handler", None) is None:
        parser.print_help()
        return 0
    console = app.console if app is not None else Console(verbose=args.verbose, quiet=args.quiet)
    try:
        if app is None:
            app = App(cfg=load_config(args.home), console=console, runner=Runner(console))
        return int(args.handler(app, args) or 0)
    except DroidForkError as exc:
        console.err.write(f"エラー: {exc}\n")
        if exc.hint:
            console.err.write(f"ヒント: {exc.hint}\n")
        return 1
    except KeyboardInterrupt:
        console.err.write("中断しました。\n")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
