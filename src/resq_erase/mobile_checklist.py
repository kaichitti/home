"""E5 スマホ初期化代行のチェックリスト（企画書 §8.3 スマホ行）。

全項目のチェックと写真（初期化後の初期設定画面など）が揃わないと証明書を発行できない。
"""
from __future__ import annotations

import json

from .errors import EraseError
from .ledger import Ledger, now

ITEMS = (
    "持ち主にバックアップの有無を確認した",
    "Apple ID / Google アカウントからサインアウトした（アクティベーションロック・FRP の解除）",
    "画面ロックが持ち主の操作で解除できることを確認した",
    "端末標準の初期化（すべてのコンテンツと設定を消去）を実行した",
    "初期化後の初期設定画面が表示されることを確認した",
    "SIM カードを取り外した",
    "SD カードを取り外した（または同時に消去した）",
)


def get(ledger: Ledger, media_id: int) -> dict:
    r = ledger.one("SELECT * FROM checklists WHERE media_id=?", media_id)
    if r is None:
        return {"items": {k: False for k in ITEMS}, "photos": []}
    items = json.loads(r["items"])
    return {"items": {k: bool(items.get(k)) for k in ITEMS}, "photos": json.loads(r["photos"])}


def save(ledger: Ledger, media_id: int, checked: dict[str, bool], photos: list[str] | None = None) -> dict:
    m = ledger.one("SELECT kind FROM media WHERE id=?", media_id)
    if m is None or m["kind"] != "スマホ":
        raise EraseError("スマホとして登録された媒体ではありません")
    cur = get(ledger, media_id)
    items = {k: bool(checked.get(k, cur["items"][k])) for k in ITEMS}
    allp = cur["photos"] + list(photos or [])
    with ledger.conn:
        ledger.conn.execute(
            "INSERT INTO checklists (media_id, items, photos, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(media_id) DO UPDATE SET items=excluded.items, photos=excluded.photos, "
            "updated_at=excluded.updated_at",
            (media_id, json.dumps(items, ensure_ascii=False), json.dumps(allp, ensure_ascii=False), now()))
    ledger.event("mobile.checklist", f"{sum(items.values())}/{len(ITEMS)} photos={len(allp)}", media_id=media_id)
    if all(items.values()) and allp:
        ledger.execute("UPDATE media SET status='消去済' WHERE id=?", media_id)
    return {"items": items, "photos": allp}


def is_complete(ledger: Ledger, media_id: int) -> bool:
    c = get(ledger, media_id)
    return all(c["items"].values()) and bool(c["photos"])
