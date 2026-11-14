"""SQLite による案件データベース（企画書 §3.6）。

回復キー・パスコードを保存する列は作らない。
events は追記専用（UPDATE / DELETE をトリガで禁止）。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id            TEXT PRIMARY KEY,
  received_at   TEXT NOT NULL,
  customer      TEXT NOT NULL,
  contact       TEXT,
  status        TEXT NOT NULL,
  price_cap     INTEGER,
  retention_until TEXT,
  note          TEXT
);
CREATE TABLE IF NOT EXISTS devices (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id   TEXT NOT NULL REFERENCES cases(id),
  kind      TEXT NOT NULL,
  maker     TEXT, model TEXT, serial TEXT,
  capacity  INTEGER,
  symptom   TEXT,
  owner     TEXT
);
CREATE TABLE IF NOT EXISTS consents (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id       TEXT NOT NULL REFERENCES cases(id),
  form_version  TEXT NOT NULL,
  signed_at     TEXT NOT NULL,
  id_method     TEXT NOT NULL,
  ownership     TEXT NOT NULL,
  authorization_doc TEXT
);
CREATE TABLE IF NOT EXISTS diagnoses (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id    TEXT REFERENCES cases(id),
  device_id  INTEGER REFERENCES devices(id),
  created_at TEXT NOT NULL,
  verdict    TEXT NOT NULL,
  report     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id    TEXT NOT NULL REFERENCES cases(id),
  device_id  INTEGER REFERENCES devices(id),
  source     TEXT NOT NULL,
  path       TEXT NOT NULL,
  mapfile    TEXT,
  size       INTEGER,
  sha256     TEXT,
  unreadable_bytes INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_runs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id    TEXT NOT NULL REFERENCES cases(id),
  image_id   INTEGER REFERENCES images(id),
  stage      TEXT NOT NULL,
  method     TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  found      INTEGER,
  unique_found INTEGER,
  out_dir    TEXT,
  note       TEXT
);
CREATE TABLE IF NOT EXISTS recovered_files (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id    TEXT NOT NULL REFERENCES cases(id),
  image_id   INTEGER REFERENCES images(id),
  orig_path  TEXT,
  name       TEXT NOT NULL,
  size       INTEGER NOT NULL,
  kind       TEXT,
  verify     TEXT NOT NULL,
  rank       TEXT NOT NULL,
  sha256     TEXT NOT NULL,
  method     TEXT NOT NULL,
  stage      TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  deleted    INTEGER,
  img_offset INTEGER,
  all_methods TEXT,
  alt_names  TEXT,
  selected   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id   TEXT,
  ts        TEXT NOT NULL,
  op        TEXT NOT NULL,
  command   TEXT,
  rc        INTEGER,
  detail    TEXT
);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
"""


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.conn:
            yield self.conn

    def insert(self, table: str, **values: Any) -> int:
        cols = ", ".join(values)
        qs = ", ".join("?" for _ in values)
        with self.tx() as c:
            cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", tuple(values.values()))
            return int(cur.lastrowid)

    def one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        return self.conn.execute(sql, args).fetchone()

    def all(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchall()

    def execute(self, sql: str, *args: Any) -> None:
        with self.tx() as c:
            c.execute(sql, args)

    # audit.EventSink
    def add_event(self, case_id: str | None, op: str, command: str, rc: int | None,
                  detail: dict | None = None) -> None:
        self.insert("events", case_id=case_id, ts=now(), op=op, command=command, rc=rc,
                    detail=json.dumps(detail, ensure_ascii=False) if detail else None)
