"""消去台帳（SQLite）。消去ステーションごとに 1 つ。

  media          受付した媒体（シリアル・写真・承諾書・保管場所）
  blocked        消去してはいけないシリアル（復旧案件の媒体・ステーション自身のディスク）
  runs           実行（ドライラン含む）の記録
  verifications  1 台ごとの検証結果
  validations    月次の妥当性確認（手順そのものの確認）
  certificates   発行した証明書（番号と PDF の SHA-256）
  checklists     スマホ初期化代行のチェックリスト
  events         追記専用の操作ログ
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  serial TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  maker TEXT, model TEXT, capacity INTEGER,
  device_maker TEXT, device_model TEXT, device_serial TEXT,
  requester TEXT NOT NULL,
  origin TEXT NOT NULL,
  consent_doc TEXT,
  photos TEXT,
  location TEXT,
  received_at TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocked (
  serial TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  media_id INTEGER NOT NULL REFERENCES media(id),
  category TEXT NOT NULL,
  method TEXT NOT NULL,
  commands TEXT NOT NULL,
  dry_run INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  completion TEXT,
  operator TEXT
);
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  media_id INTEGER NOT NULL REFERENCES media(id),
  run_id INTEGER REFERENCES runs(id),
  created_at TEXT NOT NULL,
  completion TEXT,
  readback_scope TEXT NOT NULL,
  readback_ok INTEGER NOT NULL,
  recovered INTEGER NOT NULL,
  passed INTEGER NOT NULL,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS validations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  performed_at TEXT NOT NULL,
  model TEXT NOT NULL,
  kind TEXT NOT NULL,
  method TEXT NOT NULL,
  planted_files INTEGER NOT NULL,
  recovered INTEGER NOT NULL,
  passed INTEGER NOT NULL,
  operator TEXT
);
CREATE TABLE IF NOT EXISTS certificates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  number TEXT NOT NULL UNIQUE,
  media_id INTEGER NOT NULL REFERENCES media(id),
  issued_at TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checklists (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  media_id INTEGER NOT NULL UNIQUE REFERENCES media(id),
  items TEXT NOT NULL,
  photos TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  media_id INTEGER,
  op TEXT NOT NULL,
  detail TEXT,
  rc INTEGER
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
"""

MEDIA_STATUSES = ("受付", "保管中", "消去済", "検証不合格", "物理破壊済", "返却", "販売", "廃棄")
ORIGINS = ("個人", "法人", "自社買取")
KINDS = ("HDD", "SATA SSD", "NVMe SSD", "USB メモリ", "SD カード", "スマホ", "その他")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def station_home() -> Path:
    return Path(os.environ.get("RESQ_ERASE_HOME", "resq-erase-data")).resolve()


class Ledger:
    def __init__(self, home: Path | None = None):
        self.home = (home or station_home())
        self.home.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.home / "erase.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def insert(self, table: str, **values: Any) -> int:
        cols = ", ".join(values)
        with self.conn:
            cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(values))})",
                                    tuple(values.values()))
        return int(cur.lastrowid)

    def one(self, sql: str, *args: Any):
        return self.conn.execute(sql, args).fetchone()

    def all(self, sql: str, *args: Any):
        return self.conn.execute(sql, args).fetchall()

    def execute(self, sql: str, *args: Any) -> None:
        with self.conn:
            self.conn.execute(sql, args)

    def event(self, op: str, detail: str = "", *, media_id: int | None = None, rc: int | None = 0) -> None:
        self.insert("events", ts=now(), media_id=media_id, op=op, detail=detail, rc=rc)

    # ------------------------------------------------------------ 媒体
    def register(self, *, serial: str, kind: str, requester: str, origin: str, consent_doc: str | None,
                 maker: str | None = None, model: str | None = None, capacity: int | None = None,
                 device_maker: str | None = None, device_model: str | None = None,
                 device_serial: str | None = None, photos: list[str] | None = None,
                 location: str | None = None) -> int:
        from .errors import EraseError

        serial = serial.strip()
        if not serial:
            raise EraseError("シリアル番号は必須です（受付時に媒体ラベルから登録）")
        if kind not in KINDS:
            raise EraseError(f"媒体の種別が不正です: {kind}（{' / '.join(KINDS)}）")
        if origin not in ORIGINS:
            raise EraseError(f"依頼元の区分が不正です: {origin}（{' / '.join(ORIGINS)}）")
        if origin != "自社買取" and not consent_doc:
            raise EraseError("消去承諾書の記録が必要です")
        mid = self.insert("media", serial=serial, kind=kind, maker=maker, model=model, capacity=capacity,
                          device_maker=device_maker, device_model=device_model, device_serial=device_serial,
                          requester=requester, origin=origin, consent_doc=consent_doc or "自社買取品",
                          photos=json.dumps(photos or [], ensure_ascii=False), location=location,
                          received_at=now(), status="保管中")
        self.event("media.register", f"{kind} {model or ''} sn={serial} loc={location or ''}", media_id=mid)
        return mid

    def media_by_serial(self, serial: str):
        return self.one("SELECT * FROM media WHERE serial=?", serial.strip())

    def block(self, serial: str, reason: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO blocked (serial, reason, synced_at) VALUES (?,?,?)",
                              (serial.strip(), reason, now()))

    def sync_blocked_from_resq(self, export_json: Path) -> int:
        """resq（復旧側）が書き出した「消去してはいけないシリアル」を取り込む。"""
        data = json.loads(export_json.read_text(encoding="utf-8"))
        n = 0
        for item in data.get("serials", []):
            if item.get("serial"):
                self.block(item["serial"], f"復旧案件 {item.get('case_id', '')}")
                n += 1
        self.event("blocked.sync", f"{export_json.name}: {n} 件")
        return n

    def blocked_reason(self, serial: str) -> str | None:
        r = self.one("SELECT reason FROM blocked WHERE serial=?", serial.strip())
        return r["reason"] if r else None

    def inventory_check(self, present_serials: list[str]) -> dict:
        """施錠保管の台数照合。台帳上『保管中』の媒体と、実際に棚にある媒体を突き合わせる。"""
        held = {r["serial"] for r in self.all("SELECT serial FROM media WHERE status='保管中'")}
        present = {s.strip() for s in present_serials}
        res = {"missing": sorted(held - present), "unregistered": sorted(present - held),
               "ok": sorted(held & present)}
        self.event("inventory.check", json.dumps({k: len(v) for k, v in res.items()}, ensure_ascii=False),
                   rc=0 if not res["missing"] else 1)
        return res
