"""resq-erase コマンドライン（消去ステーション専用）。

  resq-erase register        媒体の受付（シリアル・承諾書・保管場所）
  resq-erase sync-blocked    復旧側（resq export-serials）の「消去してはいけないシリアル」を取り込む
  resq-erase inventory       施錠保管の台数照合
  resq-erase probe           E1 媒体識別と方式選択
  resq-erase erase           E2 ドライラン（既定）／ --execute で実行（シリアル下 4 桁の入力が必要）
  resq-erase verify          E3 読み戻し＋復旧試行
  resq-erase destroy         物理破壊の記録（写真必須）
  resq-erase certificate     E4 証明書の発行
  resq-erase export-verify   照合ページ用の書き出し（番号とハッシュのみ）
  resq-erase validation      月次の妥当性確認の記録・実績表
  resq-erase gui             デスクトップアプリ（スマホ初期化代行のチェックリストなど）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import certificate as cert_mod
from .collect import collect as _collect
from .collect import device_size
from .collect import lsblk_live as _lsblk_live
from . import exec as ex
from . import probe as probe_mod
from . import run as run_mod
from . import verify as verify_mod
from .errors import EraseError
from .ledger import Ledger

app = typer.Typer(help="resq-erase — 完全消去ツール（消去ステーション専用）", no_args_is_help=True)
validation_app = typer.Typer(help="月次の妥当性確認", no_args_is_help=True)
app.add_typer(validation_app, name="validation")
console = Console()


def _show_version(value: bool) -> None:
    if value:
        from . import __version__

        console.print(f"resq-erase {__version__}")
        raise typer.Exit()


@app.callback()
def _main(version: bool = typer.Option(False, "--version", callback=_show_version, is_eager=True,
                                       help="バージョンを表示して終了")):
    pass


def _guard(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except EraseError as e:
            console.print(f"[bold red]停止:[/] {e}")
            raise typer.Exit(1) from None
    return wrapper


@app.command()
@_guard
def register(serial: str = typer.Option(...), kind: str = typer.Option(...), requester: str = typer.Option(...),
             origin: str = typer.Option("個人"), consent_doc: Optional[str] = typer.Option(None),
             model: Optional[str] = None, maker: Optional[str] = None, location: Optional[str] = None,
             photo: list[Path] = typer.Option([], help="受付時の媒体ラベル写真")):
    """媒体を受付して消去台帳に登録する。"""
    lg = Ledger()
    mid = lg.register(serial=serial, kind=kind, requester=requester, origin=origin, consent_doc=consent_doc,
                      model=model, maker=maker, location=location, photos=[str(p.resolve()) for p in photo])
    console.print(f"媒体#{mid} を登録しました（施錠保管: {location or '未指定'}）")


@app.command("sync-blocked")
@_guard
def sync_blocked(export_json: Path):
    """復旧側の書き出し（resq export-serials）を取り込み、該当シリアルを消去禁止にする。"""
    n = Ledger().sync_blocked_from_resq(export_json)
    console.print(f"消去禁止シリアル: {n} 件を取り込みました")


@app.command()
def inventory(serials: list[str]):
    """施錠保管の台数照合。棚にある媒体のシリアルを並べて渡す。"""
    res = Ledger().inventory_check(serials)
    console.print(json.dumps(res, ensure_ascii=False, indent=1))
    if res["missing"]:
        raise typer.Exit(1)


@app.command()
@_guard
def probe(serial: str, mock_dir: Optional[Path] = typer.Option(None, help="識別出力のモック（訓練・テスト用）")):
    """媒体を識別し、消去方式を選ぶ（読み取りのみ）。"""
    lg = Ledger()
    m = lg.media_by_serial(serial)
    lsblk, outs = _collect(lg, serial, mock_dir)
    p = probe_mod.probe_from_outputs(serial, lsblk=lsblk, declared_kind=m["kind"] if m else None, **outs)
    meth = probe_mod.select_method(p)
    console.print(f"媒体: {p.media}（接続 {p.transport} / 回転 {p.rotational}）")
    console.print(f"方式: [bold]{meth.category or '—'}[/] {meth.name}")
    for b in meth.blockers:
        console.print(f"  [red]要対応[/] {b}")
    for n in meth.notes:
        console.print(f"  注意 {n}")


@app.command()
@_guard
def erase(serial: str, execute: bool = typer.Option(False, "--execute", help="本実行（既定はドライラン）"),
          mock_dir: Optional[Path] = typer.Option(None), operator: str = typer.Option(""),
          station_serial: list[str] = typer.Option([], help="ステーション自身のディスクのシリアル")):
    """消去する。既定はドライラン（実行予定コマンドの表示と記録のみ）。"""
    lg = Ledger()
    m = lg.media_by_serial(serial)
    lsblk, outs = _collect(lg, serial, mock_dir)
    p = probe_mod.probe_from_outputs(serial, lsblk=lsblk, declared_kind=m["kind"] if m else None, **outs)
    plan = run_mod.plan(lg, serial, p, probe_mod.select_method, lsblk=lsblk, station_serials=set(station_serial),
                        operator=operator)
    console.print(f"対象: {plan.device}（シリアル {serial}）／ {plan.method.category} {plan.method.name}")
    for c in plan.commands:
        console.print(f"  $ {' '.join(c)}")
    for b in plan.method.blockers:
        console.print(f"  [red]要対応[/] {b}")
    if not execute:
        console.print("[ドライラン] 実行していません。実行するには --execute")
        return
    last4 = typer.prompt(f"媒体ラベルのシリアル下 4 桁を入力（{plan.device}）")
    rid = run_mod.execute(lg, plan, confirm_last4=last4,
                          get_lsblk=(lambda: _lsblk_live(lg)) if not mock_dir else (lambda: lsblk),
                          station_serials=set(station_serial), operator=operator)
    console.print(f"実行記録#{rid}。続けて `resq-erase verify {serial} --target {plan.device}`")


@app.command()
@_guard
def verify(serial: str, target: str = typer.Option(..., help="消去したデバイス（またはそのイメージ）"),
           scope: str = typer.Option("sample", help="sample / full"),
           expected: str = typer.Option("auto", help="auto / zero / none（読み戻しで期待する内容）"),
           completion: Optional[str] = typer.Option(None, help="完了ステータス（未指定なら実行記録から）")):
    """読み戻し検査と復旧試行で、消去が効いているかを確かめる。"""
    lg = Ledger()
    m = lg.media_by_serial(serial)
    if m is None:
        raise EraseError("台帳に未登録です")
    run = lg.one("SELECT * FROM runs WHERE media_id=? AND dry_run=0 ORDER BY id DESC LIMIT 1", m["id"])
    exp = {"zero": b"\0", "none": None}.get(expected)
    if expected == "auto":
        exp = b"\0" if run and ("上書き" in run["method"] or "Overwrite" in run["method"]) else None
    is_dev = target.startswith("/dev/")
    size = device_size(lg, target)
    res = verify_mod.verify(lg, m["id"], target, size, expected=exp, scope=scope,
                            completion=completion or (run["completion"] if run else None),
                            run_id=run["id"] if run else None, allow_device=is_dev)
    console.print(f"結果: {'[green]合格' if res['passed'] else '[red]不合格'}[/]  読み戻し {res['readback']['ok']} ／ "
                  f"復旧試行で回収 {res['recovery']['recovered']} 件")


@app.command()
@_guard
def destroy(serial: str, photo: list[Path] = typer.Option(..., help="破壊後の写真"), operator: str = ""):
    """物理破壊を記録する（写真必須）。"""
    lg = Ledger()
    m = lg.media_by_serial(serial)
    if m is None:
        raise EraseError("台帳に未登録です")
    cert_mod.destroy(lg, m["id"], photos=[str(p.resolve()) for p in photo], operator=operator)
    console.print("物理破壊を記録しました")


@app.command()
@_guard
def certificate(serial: str, operator: str = "", verify_url: Optional[str] = typer.Option(None)):
    """消去証明書を発行する（検証合格・物理破壊・初期化代行チェック完了のいずれかが必要）。"""
    lg = Ledger()
    m = lg.media_by_serial(serial)
    if m is None:
        raise EraseError("台帳に未登録です")
    r = cert_mod.issue(lg, m["id"], operator=operator, verify_base_url=verify_url)
    console.print(f"証明書 {r['number']}: {r['path']}\nSHA-256 {r['sha256']}")


@app.command("export-verify")
def export_verify(out_dir: Path):
    """照合ページ用に、証明書番号・発行日・SHA-256 だけを書き出す。"""
    j, h = cert_mod.export_verification_list(Ledger(), out_dir)
    console.print(f"{j}\n{h}")


@validation_app.command("record")
def validation_record(model: str = typer.Option(...), kind: str = typer.Option(...), method: str = typer.Option(...),
                      planted: int = typer.Option(...), recovered: int = typer.Option(...), operator: str = ""):
    """月次の妥当性確認の結果を記録する。"""
    verify_mod.record_validation(Ledger(), model=model, kind=kind, method=method, planted_files=planted,
                                 recovered=recovered, operator=operator)
    console.print("記録しました" + ("" if recovered == 0 else "（[red]不合格[/]：方式を見直してください）"))


@validation_app.command("report")
def validation_report():
    """型番×方式ごとの実績表。"""
    t = Table("型番", "種別", "方式", "回数", "合格", "最終", "判定")
    for r in verify_mod.validation_table(Ledger()):
        t.add_row(r["model"], r["kind"], r["method"], str(r["runs"]), str(r["passes"]), r["last"][:10],
                  "合格" if r["all_passed"] else "要見直し")
    console.print(t)


@app.command()
def gui():
    """消去ステーションのデスクトップアプリ（画面版）を起動する。"""
    from .gui import main

    raise typer.Exit(main(["resq-erase-gui"]))


if __name__ == "__main__":
    app()
