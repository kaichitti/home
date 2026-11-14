"""案件の生成・取得と、案件ごとの作業ディレクトリ・監査コンテキスト。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .audit import AuditContext
from .config import CASE_SUBDIRS, Workspace
from .db import Database, now
from .errors import ResqError

# 状態遷移（P6 の管理画面でも同じ定義を使う）
STATES = ("受付", "診断済", "イメージ取得済", "復旧済", "一覧提示", "納品済", "キャンセル", "取次", "返却", "消去済")
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "受付": ("診断済", "キャンセル"),
    "診断済": ("イメージ取得済", "取次", "返却", "キャンセル"),
    "イメージ取得済": ("復旧済", "キャンセル"),
    "復旧済": ("一覧提示", "復旧済"),
    "一覧提示": ("納品済", "キャンセル", "復旧済"),
    "納品済": ("消去済",),
    "キャンセル": ("消去済",),
    "取次": ("返却",),
    "返却": ("消去済",),
    "消去済": (),
}


@dataclass
class Case:
    ws: Workspace
    db: Database
    id: str

    @property
    def dir(self) -> Path:
        return self.ws.case_dir(self.id)

    def sub(self, name: str) -> Path:
        p = self.dir / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def ctx(self) -> AuditContext:
        return AuditContext(log_path=self.ws.log_path, sink=self.db, case_id=self.id,
                            extra_logs=[self.dir / "logs" / "events.jsonl"])

    @property
    def row(self):
        return self.db.one("SELECT * FROM cases WHERE id=?", self.id)

    def set_status(self, new: str, *, force_same: bool = False) -> None:
        cur = self.row["status"]
        if new == cur and force_same:
            return
        if new not in TRANSITIONS.get(cur, ()):
            raise ResqError(f"状態遷移できません: {cur} → {new}")
        self.db.execute("UPDATE cases SET status=? WHERE id=?", new, self.id)
        self.db.add_event(self.id, "case.status", f"{cur} -> {new}", 0)

    def advance(self, new: str) -> None:
        """処理の完了時に呼ぶ。すでにその状態以降なら何もしない。"""
        cur = self.row["status"]
        if cur == new:
            return
        if new in TRANSITIONS.get(cur, ()):
            self.set_status(new)


def new_case_id(db: Database) -> str:
    prefix = "R" + datetime.now().strftime("%y%m") + "-"
    row = db.one("SELECT id FROM cases WHERE id LIKE ? ORDER BY id DESC LIMIT 1", prefix + "%")
    seq = int(row["id"].split("-")[1]) + 1 if row else 1
    return f"{prefix}{seq:04d}"


def open_workspace(ws: Workspace | None = None) -> tuple[Workspace, Database]:
    ws = (ws or Workspace.from_env()).ensure()
    return ws, Database(ws.db_path)


def create_case(ws: Workspace, db: Database, *, customer: str, contact: str | None = None,
                price_cap: int | None = None, retention_until: str | None = None,
                note: str | None = None) -> Case:
    cid = new_case_id(db)
    db.insert("cases", id=cid, received_at=now(), customer=customer, contact=contact,
              status="受付", price_cap=price_cap, retention_until=retention_until, note=note)
    case = Case(ws, db, cid)
    for d in CASE_SUBDIRS:
        case.sub(d)
    db.add_event(cid, "case.create", "", 0)
    return case


def get_case(ws: Workspace, db: Database, case_id: str) -> Case:
    if not db.one("SELECT id FROM cases WHERE id=?", case_id):
        raise ResqError(f"案件が見つかりません: {case_id}")
    return Case(ws, db, case_id)
