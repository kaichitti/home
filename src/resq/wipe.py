"""作業領域の消去（案件終了時、P5）。

暗号化コンテナ（LUKS2）を使っている案件:
  1. `plan()` で破棄スクリプト（鍵スロット消去→鍵ファイル削除→コンテナ削除）を生成
  2. 人間が作業機で root として実行
  3. `confirm()` でコンテナ・鍵ファイルが無いことを確かめてから、消去証明書を発行
暗号化コンテナを使っていない案件（開発・検証用）:
  `wipe_plain(execute=True)` で作業ディレクトリを削除して証明書を発行。
  ※ 通常の削除は SSD 上に痕跡が残りうるため、本番では LUKS 方式を使う。

DB からは復旧ファイル一覧（ファイル名を含む）を削除し、案件の状態を「消去済」にする。
操作ログ（events）は追記専用のため残る（ファイル名は含まない）。
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import date, datetime
from pathlib import Path

from . import reports, workspace_crypt
from .cases import Case
from .db import now
from .errors import ResqError

WIPE_FROM = ("納品済", "キャンセル", "返却")


def _summary(case: Case) -> dict:
    files = bytes_ = 0
    if case.dir.exists():
        for p in case.dir.rglob("*"):
            if p.is_file() and not p.is_symlink():
                files += 1
                bytes_ += p.stat().st_size
    images = case.db.one("SELECT COUNT(*) AS n FROM images WHERE case_id=?", case.id)["n"]
    rec = case.db.one("SELECT COUNT(*) AS n FROM recovered_files WHERE case_id=?", case.id)["n"]
    return {"files": files, "bytes": bytes_, "images": images, "recovered": rec}


def _check_state(case: Case) -> None:
    st = case.row["status"]
    if st not in WIPE_FROM:
        raise ResqError(f"状態が『{st}』のため消去できません（{' / '.join(WIPE_FROM)} のときのみ）")


def plan(case: Case) -> Path:
    """LUKS コンテナ破棄スクリプトを生成する（実行はしない）。"""
    _check_state(case)
    cmds = workspace_crypt.destroy_commands(case.ws, case.id)
    p = workspace_crypt.write_script(case.ws, case.id, "destroy", cmds)
    case.db.add_event(case.id, "wipe.plan", str(p), 0)
    return p


def _issue(case: Case, *, method: str, summary: dict, operator: str, pdf: bool) -> dict:
    out_dir = case.ws.root / "certificates"
    out_dir.mkdir(parents=True, exist_ok=True)
    number = f"W-{case.id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    html, pdf_path = reports.render(
        "workarea_certificate.html", out_dir / f"{number}.html", pdf=pdf, case=case.row, number=number,
        issued=datetime.now().strftime("%Y-%m-%d %H:%M"), method=method, summary=summary, operator=operator)
    doc = pdf_path or html
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()
    case.db.insert("certificates", case_id=case.id, kind="作業領域消去", number=number, issued_at=now(),
                   path=str(doc), sha256=digest)
    with case.db.tx() as c:
        c.execute("DELETE FROM recovered_files WHERE case_id=?", (case.id,))
    case.db.add_event(case.id, "wipe.done", f"{method} cert={number} sha256={digest}", 0)
    case.set_status("消去済")
    return {"number": number, "path": doc, "sha256": digest, "summary": summary}


def confirm(case: Case, *, operator: str = "", pdf: bool = True) -> dict:
    """破棄スクリプトの実行後に呼ぶ。コンテナと鍵ファイルが消えていることを確かめて証明書を出す。"""
    _check_state(case)
    p = workspace_crypt.paths(case.ws, case.id)
    left = [str(x) for x in (p.container, p.keyfile) if x.exists()]
    if left:
        raise ResqError(f"まだ残っています（破棄スクリプトを実行してください）: {left}")
    return _issue(case, method="LUKS2 キースロット消去（cryptsetup erase）＋鍵ファイル・コンテナ削除",
                  summary=_summary(case), operator=operator, pdf=pdf)


def wipe_plain(case: Case, *, execute: bool = False, operator: str = "", pdf: bool = True) -> dict:
    """暗号化コンテナなしの作業領域を削除する。execute=False ならドライラン（対象の集計のみ）。"""
    _check_state(case)
    if workspace_crypt.is_encrypted_workspace(case.ws, case.id):
        raise ResqError("この案件は暗号化コンテナを使っています。`resq wipe --plan` と `--confirm` を使ってください")
    summary = _summary(case)
    if not execute:
        return {"dry_run": True, "summary": summary, "target": str(case.dir)}
    shutil.rmtree(case.dir, ignore_errors=False)
    return _issue(case, method="作業ディレクトリの削除（暗号化コンテナ未使用）", summary=summary,
                  operator=operator, pdf=pdf)


def due(case_db, today: date | None = None) -> list[dict]:
    """保管期限を過ぎた、消去待ちの案件。"""
    today = today or date.today()
    out = []
    for r in case_db.all("SELECT * FROM cases WHERE retention_until IS NOT NULL AND status IN (?,?,?)",
                         *WIPE_FROM):
        try:
            if date.fromisoformat(r["retention_until"][:10]) <= today:
                out.append(dict(r))
        except ValueError:
            continue
    return out
