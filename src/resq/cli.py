"""resq コマンドライン（Typer + Rich）。

  resq case new / list / show / status
  resq consent add      同意書・本人確認・所有確認の記録
  resq device add       預かり媒体の登録
  resq diagnose         診断（判定: 自社／条件付き／取次／不可）
  resq image            イメージ化（ddrescue, mapfile 付き・再開可）
  resq image-register   取得済みイメージの登録
  resq recover          多段復旧 S1→S2→S3→S4→S5→S6→S7→S8
  resq ingest           商用エンジン結果の取り込み（P3b）
  resq merge            S8 統合のみ再実行
  resq compare          段どうしの回収結果の比較（例: S3 と COM1）
  resq catalog          顧客向け一覧（HTML/PDF）
  resq select / deliver 納品対象の選択・納品（ハッシュ照合・納品書）
  resq workspace        案件ごとの暗号化作業領域（LUKS）のスクリプト生成
  resq wipe             作業領域の消去と消去証明書
  resq unlock           BitLocker / LUKS の解錠（回復キーは保存しない）
  resq mobile           スマホ吸い出し（iPhone / Android）
  resq gui              デスクトップアプリ（画面版）を起動
  resq events           操作ログの表示
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import catalog as catalog_mod
from . import diagnose as diagnose_mod
from . import image as image_mod
from . import intake
from .cases import TRANSITIONS, create_case, get_case, open_workspace
from .errors import ResqError
from .recover import STAGES, stage_label
from .recover import ingest as ingest_mod
from .recover import merge as merge_mod
from .recover import pipeline

app = typer.Typer(help="resq — データ復旧作業ツール（原本には書き込みません）", no_args_is_help=True)
case_app = typer.Typer(help="案件の管理", no_args_is_help=True)
consent_app = typer.Typer(help="同意書・本人確認", no_args_is_help=True)
device_app = typer.Typer(help="預かり媒体", no_args_is_help=True)
app.add_typer(case_app, name="case")
app.add_typer(consent_app, name="consent")
app.add_typer(device_app, name="device")
workspace_app = typer.Typer(help="案件ごとの暗号化作業領域（LUKS）", no_args_is_help=True)
mobile_app = typer.Typer(help="スマホ吸い出し", no_args_is_help=True)
app.add_typer(workspace_app, name="workspace")
app.add_typer(mobile_app, name="mobile")
console = Console()


def _show_version(value: bool) -> None:
    if value:
        from . import __version__

        console.print(f"resq {__version__}")
        raise typer.Exit()


@app.callback()
def _main(version: bool = typer.Option(False, "--version", callback=_show_version, is_eager=True,
                                       help="バージョンを表示して終了")):
    pass


def _case(case_id: str):
    ws, db = open_workspace()
    return get_case(ws, db, case_id)


def _guard(fn):
    """業務エラーはトレースバックなしで表示して終了コード 1。"""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except ResqError as e:
            console.print(f"[bold red]停止:[/] {e}")
            raise typer.Exit(1) from None
    return wrapper


# ---------------------------------------------------------------- case
@case_app.command("new")
@_guard
def case_new(customer: str = typer.Option(..., help="お客様名"),
             contact: Optional[str] = typer.Option(None, help="連絡先"),
             price_cap: Optional[int] = typer.Option(None, help="見積上限額（円）"),
             retention_until: Optional[str] = typer.Option(None, help="保管期限 YYYY-MM-DD"),
             note: Optional[str] = None):
    ws, db = open_workspace()
    c = create_case(ws, db, customer=customer, contact=contact, price_cap=price_cap,
                    retention_until=retention_until, note=note)
    console.print(f"案件を登録しました: [bold]{c.id}[/]  ({c.dir})")


@case_app.command("list")
def case_list():
    ws, db = open_workspace()
    t = Table("案件", "受付", "お客様", "状態", "上限額")
    for r in db.all("SELECT * FROM cases ORDER BY id DESC"):
        t.add_row(r["id"], r["received_at"][:16], r["customer"], r["status"],
                  f"{r['price_cap']:,}" if r["price_cap"] else "-")
    console.print(t)


@case_app.command("show")
@_guard
def case_show(case_id: str):
    c = _case(case_id)
    r = c.row
    console.print(f"[bold]{r['id']}[/] {r['customer']} 状態={r['status']} 上限={r['price_cap']}")
    for d in c.db.all("SELECT * FROM devices WHERE case_id=?", c.id):
        console.print(f"  媒体#{d['id']} {d['kind']} {d['maker'] or ''} {d['model'] or ''} SN={d['serial'] or '-'} 症状={d['symptom'] or '-'}")
    for i in c.db.all("SELECT * FROM images WHERE case_id=?", c.id):
        console.print(f"  イメージ#{i['id']} {i['path']} sha256={i['sha256'] or '(未完了)'} 読めず={i['unreadable_bytes']}")
    for s in c.db.all("SELECT stage, method, found, unique_found FROM stage_runs WHERE case_id=? ORDER BY id", c.id):
        console.print(f"  {s['stage']} {s['method']} 検出={s['found']} 単独={s['unique_found']}")
    console.print(f"  次に遷移できる状態: {', '.join(TRANSITIONS[r['status']]) or '-'}")


@case_app.command("status")
@_guard
def case_status(case_id: str, new_status: str):
    c = _case(case_id)
    c.set_status(new_status)
    console.print(f"{c.id}: {new_status}")


# ---------------------------------------------------------------- intake
@consent_app.command("add")
@_guard
def consent_add(case_id: str,
                form_version: str = typer.Option(..., help="同意書の版（例: 2026.11）"),
                id_method: str = typer.Option(..., help=f"本人確認方法: {' / '.join(intake.ID_METHODS)}"),
                ownership: str = typer.Option(intake.OWNERSHIP_SELF, help=f"所有確認: {' / '.join(intake.OWNERSHIP_CHOICES)}"),
                authorization_doc: Optional[str] = typer.Option(None, help="権限者の同意書面の番号等")):
    c = _case(case_id)
    intake.add_consent(c, form_version=form_version, id_method=id_method, ownership=ownership,
                       authorization_doc=authorization_doc)
    console.print("同意書を記録しました")


@device_app.command("add")
@_guard
def device_add(case_id: str, kind: str = typer.Option(..., help="HDD / SSD / NVMe / USB / SD / iPhone / Android など"),
               maker: Optional[str] = None, model: Optional[str] = None, serial: Optional[str] = None,
               capacity: Optional[int] = None, symptom: Optional[str] = None,
               request: Optional[str] = typer.Option(None, help="ご依頼内容（受けない依頼の検出に使う）")):
    c = _case(case_id)
    did = intake.add_device(c, kind=kind, maker=maker, model=model, serial=serial, capacity=capacity,
                            symptom=symptom, request=request)
    console.print(f"媒体#{did} を登録しました")


# ---------------------------------------------------------------- 作業
@app.command()
@_guard
def diagnose(source: str = typer.Argument(..., help="デバイスパスまたはイメージファイル"),
             case_id: Optional[str] = typer.Option(None, "--case"),
             device_id: Optional[int] = typer.Option(None, "--device"),
             symptom: list[str] = typer.Option([], help="症状（異音 / 認識しない / SSD削除 など。複数可）"),
             smart_json: Optional[Path] = typer.Option(None, help="smartctl -j -a の出力 JSON（テスト・持ち込み用）"),
             as_json: bool = typer.Option(False, "--json")):
    """媒体またはイメージを診断し、受付判定（自社／条件付き／取次／不可）と理由を出す。"""
    c = _case(case_id) if case_id else None
    d = diagnose_mod.diagnose(source, symptoms=symptom, smart_json=smart_json, ctx=c.ctx if c else None)
    if c:
        diagnose_mod.save(d, c, device_id)
    if as_json:
        print(json.dumps(d.to_dict(), ensure_ascii=False, indent=1))
        return
    color = {"自社": "green", "条件付き": "yellow", "取次": "magenta", "不可": "red"}[d.verdict]
    console.print(f"判定: [bold {color}]{d.verdict}[/]（{d.level}）")
    for r in d.reasons:
        console.print(f"  ・{r}")
    for w in d.warnings:
        console.print(f"  [yellow]注意[/] {w}")
    for fs in d.filesystems:
        console.print(f"  FS: {fs['type']} @ セクタ {fs['offset_sectors']}")
    for e in d.encryption:
        console.print(f"  暗号化: {e['type']} @ {e['offset']}")


@app.command()
@_guard
def image(case_id: str, source: str,
          device_id: Optional[int] = typer.Option(None, "--device"),
          accept_risk: bool = typer.Option(False, help="SMART 危険兆候を顧客に説明済みで続行する"),
          retry: int = typer.Option(3, help="不良領域の再試行回数"),
          sector_size: int = typer.Option(512)):
    """原本をイメージ化する（ddrescue・mapfile 付き。中断しても同じコマンドで再開）。"""
    c = _case(case_id)
    iid = image_mod.acquire(c, source, device_id=device_id, accept_risk=accept_risk, retry_passes=retry,
                            sector_size=sector_size, stream=sys.stderr)
    r = c.db.one("SELECT * FROM images WHERE id=?", iid)
    if r["sha256"]:
        console.print(f"イメージ#{iid} 完了 sha256={r['sha256']} 読めなかった領域={r['unreadable_bytes']:,} B")
    else:
        console.print(f"イメージ#{iid} は未完了です。同じコマンドで再開できます。")


@app.command("image-register")
@_guard
def image_register(case_id: str, path: Path, device_id: Optional[int] = typer.Option(None, "--device")):
    """他機で取得済みのイメージ（読み取り専用）を案件に登録する。"""
    c = _case(case_id)
    iid = image_mod.register_existing(c, path, device_id=device_id)
    console.print(f"イメージ#{iid} を登録しました")


@app.command()
@_guard
def recover(case_id: str, image_id: Optional[int] = typer.Option(None, "--image"),
            stages: str = typer.Option(",".join(pipeline.DEFAULT_STAGES), help="実行する段（カンマ区切り）"),
            no_testdisk: bool = typer.Option(False, help="S1 で TestDisk を使わない")):
    """多段復旧（S1→S7）を実行し、S8 で統合・ランク付けする。"""
    c = _case(case_id)
    st = tuple(s.strip().upper() for s in stages.split(",") if s.strip())
    with console.status("復旧中…") as status:
        rep = pipeline.run(c, image_id=image_id, stages=st, use_testdisk=not no_testdisk,
                           on_stage=lambda s: status.update(f"{s} {STAGES.get(s, '')} 実行中…"))
    _print_report(rep)


@app.command()
@_guard
def ingest(case_id: str, folder: Path, engine: str = typer.Option(..., help="DMDE / R-Studio"),
           image_id: Optional[int] = typer.Option(None, "--image"),
           license_note: Optional[str] = typer.Option(None, help="使用ライセンス（例: DMDE Professional #xxxx）")):
    """商用エンジン（DMDE / R-Studio）の書き出しフォルダを取り込んで統合する。"""
    c = _case(case_id)
    m = ingest_mod.ingest(c, folder, engine=engine, image_id=image_id, license_note=license_note)
    console.print(f"{len(m.candidates)} 件を取り込みました。統合します…")
    _print_report(merge_mod.merge(c))


@app.command()
@_guard
def merge(case_id: str):
    """S8（統合・ランク付け）だけをやり直す。"""
    _print_report(merge_mod.merge(_case(case_id)))


@app.command()
@_guard
def catalog(case_id: str, no_pdf: bool = typer.Option(False, help="PDF を作らない")):
    """顧客向けの復旧ファイル一覧（HTML / PDF）を作る。"""
    r = catalog_mod.build(_case(case_id), pdf=not no_pdf)
    console.print(f"一覧: {r['html']}")
    if r["pdf"]:
        console.print(f"PDF : {r['pdf']}")
    console.print("ランク別: " + "  ".join(f"{k}={v}" for k, v in r["ranks"].items()) + f"  ランク外={r['excluded']}")


@app.command()
@_guard
def events(case_id: str, limit: int = 50):
    """案件の操作ログ（実行した外部コマンド等）を表示する。"""
    c = _case(case_id)
    t = Table("日時", "操作", "rc", "コマンド")
    for e in c.db.all("SELECT * FROM events WHERE case_id=? ORDER BY id DESC LIMIT ?", c.id, limit):
        t.add_row(e["ts"][:19], e["op"], str(e["rc"]), (e["command"] or "")[:90])
    console.print(t)


@app.command()
@_guard
def compare(case_id: str, a: str, b: str):
    """2 つの段（例: S3 と COM1）の回収結果を比べて差分を記録する。"""
    from .recover import compare as compare_mod

    rep = compare_mod.compare(_case(case_id), a, b)
    console.print(json.dumps(rep["count"], ensure_ascii=False))
    console.print(f"フォルダ付き: {json.dumps(rep['with_folder'], ensure_ascii=False)}")
    console.print(f"記録: {rep['path']}")


@app.command()
@_guard
def select(case_id: str, ranks: str = typer.Option("A,B", help="選ぶランク（カンマ区切り。空なら ID のみ）"),
           ids: str = typer.Option("", help="個別に選ぶファイル ID（カンマ区切り）"),
           add: bool = typer.Option(False, help="今の選択に追加する")):
    """納品対象のファイルを選ぶ（ランク X は選べない）。"""
    from . import deliver as deliver_mod

    rk = tuple(r.strip().upper() for r in ranks.split(",") if r.strip()) or None
    id_list = [int(x) for x in ids.split(",") if x.strip()] or None
    n = deliver_mod.select(_case(case_id), ranks=rk, ids=id_list, add=add)
    console.print(f"納品対象: {n} 件")


@app.command()
@_guard
def deliver(case_id: str, target: Path = typer.Argument(..., help="納品用メディアのマウント先"),
            operator: str = typer.Option("", help="担当者名")):
    """選んだファイルを納品メディアへコピーし、ハッシュ照合して納品書を出す。"""
    from . import deliver as deliver_mod
    from .reports import human_bytes

    r = deliver_mod.deliver(_case(case_id), target, operator=operator)
    console.print(f"納品しました: {r['root']}  {r['count']} 件 {human_bytes(r['bytes'])}（全件ハッシュ一致）")
    console.print(f"納品書: {r['note']}")


@app.command()
@_guard
def wipe(case_id: str, plan: bool = typer.Option(False, "--plan", help="LUKS 破棄スクリプトを生成（実行しない）"),
         confirm: bool = typer.Option(False, "--confirm", help="破棄スクリプト実行後に確認して証明書を発行"),
         execute: bool = typer.Option(False, "--execute", help="暗号化コンテナなしの作業領域を削除して証明書を発行"),
         operator: str = typer.Option("", help="担当者名")):
    """作業領域を消去して消去証明書を出す（既定はドライラン）。"""
    from . import wipe as wipe_mod

    c = _case(case_id)
    if plan:
        p = wipe_mod.plan(c)
        console.print(f"破棄スクリプト: {p}\n作業機で root として実行してから `resq wipe {case_id} --confirm`")
        return
    if confirm:
        r = wipe_mod.confirm(c, operator=operator)
    else:
        r = wipe_mod.wipe_plain(c, execute=execute, operator=operator)
        if r.get("dry_run"):
            console.print(f"[ドライラン] 削除対象: {r['target']} {json.dumps(r['summary'], ensure_ascii=False)}")
            console.print("実行するには --execute（暗号化コンテナ使用時は --plan / --confirm）")
            return
    console.print(f"消去証明書 {r['number']}: {r['path']}\nSHA-256 {r['sha256']}")


@app.command("wipe-due")
def wipe_due():
    """保管期限を過ぎた消去待ちの案件。"""
    from . import wipe as wipe_mod

    _ws, db = open_workspace()
    t = Table("案件", "お客様", "状態", "保管期限")
    for r in wipe_mod.due(db):
        t.add_row(r["id"], r["customer"], r["status"], r["retention_until"])
    console.print(t)


@workspace_app.command("create")
@_guard
def workspace_create(case_id: str, size: str = typer.Option(..., help="コンテナの大きさ（例: 500G）")):
    """暗号化作業領域を作るスクリプトを生成する（実行は作業機で root が行う）。"""
    from . import workspace_crypt as wc

    c = _case(case_id)
    p = wc.write_script(c.ws, c.id, "create", wc.create_commands(c.ws, c.id, size))
    console.print(f"作成スクリプト: {p}")


@app.command()
@_guard
def unlock(case_id: str, image_id: int = typer.Option(..., "--image"),
           kind: str = typer.Option("bitlk", help="bitlk（BitLocker）/ luks"),
           partition: Optional[str] = typer.Option(None, help="パーティション内の場合 '開始セクタ:セクタ数'"),
           acquire: bool = typer.Option(True, help="解錠後に復号済みイメージを取得する"),
           close: bool = typer.Option(True, help="取得後に閉じる")):
    """回復キーを画面で入力して解錠する。キーは保存・表示・記録しない。"""
    from . import unlock as unlock_mod

    c = _case(case_id)
    if partition:
        start, length = (int(x) for x in partition.split(":"))
        image_id = unlock_mod.extract_partition(c, image_id, start, length)
        console.print(f"パーティションを切り出しました: イメージ#{image_id}")
    key = typer.prompt("回復キー（入力は表示されません）", hide_input=True)
    try:
        dev = unlock_mod.unlock(c, image_id, key, kind=kind)
    finally:
        del key
    console.print(f"解錠しました: {dev}（読み取り専用）")
    if acquire:
        try:
            iid = image_mod.acquire(c, dev, accept_risk=True, stream=sys.stderr)
            console.print(f"復号済みイメージ#{iid} を取得しました")
        finally:
            if close:
                unlock_mod.close(c, image_id)


@mobile_app.command("ios")
@_guard
def mobile_ios(case_id: str, udid: str, backup_dir: Optional[Path] = typer.Option(None, help="取得済みバックアップから取り出すだけの場合")):
    from .mobile import ios, next_stage_dir

    c = _case(case_id)
    if backup_dir is None:
        console.print("持ち主本人に次の操作をしてもらい、確認してください:")
        confirmed = {s: typer.confirm(f"  {s}") for s in ios.STEPS}
        backup_dir = ios.backup(c, udid, confirmed)
        stage = backup_dir.parent
    else:
        stage = next_stage_dir(c)
    man = ios.extract_camera_roll(c, backup_dir, stage)
    console.print(f"{len(man.candidates)} 件を取り出しました。統合します…")
    _print_report(merge_mod.merge(c))


@mobile_app.command("android")
@_guard
def mobile_android(case_id: str, serial: str):
    from .mobile import android

    c = _case(case_id)
    console.print("持ち主本人に次の操作をしてもらい、確認してください:")
    confirmed = {s: typer.confirm(f"  {s}") for s in android.STEPS}
    man = android.pull(c, serial, confirmed)
    console.print(f"{len(man.candidates)} 件を吸い出しました。統合します…")
    _print_report(merge_mod.merge(c))


@app.command("export-serials")
def export_serials(out: Path = typer.Argument(..., help="消去ステーションへ渡す JSON")):
    """進行中の復旧案件の媒体シリアルを書き出す（消去ステーションで消去禁止にするため）。"""
    from .db import now

    _ws, db = open_workspace()
    rows = db.all("""SELECT d.serial, d.case_id FROM devices d JOIN cases c ON c.id = d.case_id
                     WHERE d.serial IS NOT NULL AND d.serial != '' AND c.status NOT IN ('返却', '消去済')""")
    data = {"exported_at": now(), "serials": [{"serial": r["serial"], "case_id": r["case_id"]} for r in rows]}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    console.print(f"{len(rows)} 件を書き出しました: {out}")


@app.command()
def gui():
    """デスクトップアプリ（画面版）を起動する。ブラウザもネットワークも使わない。"""
    from .gui.app import main

    raise typer.Exit(main(["resq-gui"]))


def _print_report(rep: dict) -> None:
    t = Table("段", "手法", "検出", "単独で検出")
    for st, v in rep.get("stages", {}).items():
        t.add_row(st, stage_label(st), str(v["found"]), str(v["unique"]))
    console.print(t)
    console.print("ランク: " + "  ".join(f"{k}={v}" for k, v in rep["ranks"].items()))
    for v in rep.get("volumes", []):
        console.print(f"  ボリューム: {v['fstype']} @ セクタ {v['offset']}（{', '.join(v['found_by'])}）")


if __name__ == "__main__":
    app()
