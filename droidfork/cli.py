"""コマンドライン（droidfork <コマンド>）。"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Callable, Sequence

from . import __version__
from .app import App
from .capture import capture, new_template
from .config import load_config
from .hostcheck import NG, run_checks
from .instances import (
    INSTANCE_HEADERS, bulk_install, collect_ids, connect_instances, create_instances, instance_rows,
    open_screens, remove_instances, reset_instances, select_instances, start_instances, stop_instances,
)
from .redroid import adb_address, container_name
from .stats import collect_stats, render_stats
from .store import TEMPLATE_STATE_LABELS
from .template import build_template, failure_hint, remove_template
from .util import Console, DroidForkError, Runner, format_table

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
    created = create_instances(app, args.template_name, args.count, scale=args.scale, fps=args.fps)
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
    created = create_instances(app, tpl.name, args.count, scale=args.scale, fps=args.fps)
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
    tp = tsub.add_parser("rm", help="削除する")
    tp.add_argument("name")
    tp.add_argument("--force", action="store_true", help="使っているインスタンスも一緒に削除する")
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
