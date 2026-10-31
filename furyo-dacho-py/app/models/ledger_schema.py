"""
台帳（ledgers）に後から追加した列の定義と自動追加

- id_document_type_note : 本人確認書類「その他」の内容
- sale_price            : 販売予定価格（POSレジの単価の初期値）

マイグレーション未実行の環境でも、台帳を扱う画面を開いた時点で不足分を追加する。
"""
import sys

from ..db import DBError, ER_DUP_FIELDNAME

COLUMN_UPGRADES = [
    ('id_document_type_note',
     """ALTER TABLE `ledgers`
                 ADD COLUMN `id_document_type_note` VARCHAR(255) NULL DEFAULT NULL
                 COMMENT '本人確認書類の種別が「その他」の場合の内容' AFTER `id_document_type`"""),
    ('sale_price',
     """ALTER TABLE `ledgers`
                 ADD COLUMN `sale_price` DECIMAL(12,0) NULL DEFAULT NULL
                 COMMENT '販売予定価格（売価・任意。POSレジの単価の初期値）' AFTER `transaction_amount`"""),
]


def _columns(db):
    return {str(r.get('Field') or '') for r in db.query("SHOW COLUMNS FROM `ledgers`")}


def missing_columns(db):
    have = _columns(db)
    return [c for c, _ in COLUMN_UPGRADES if c not in have]


def apply(db):
    """不足している列を追加する（トランザクションの外で呼ぶこと）。追加した列の数を返す"""
    missing = missing_columns(db)
    n = 0
    for column, ddl in COLUMN_UPGRADES:
        if column not in missing:
            continue
        try:
            db.execute(ddl)
            n += 1
            db.ledger_columns = None
        except DBError as e:
            if e.code != ER_DUP_FIELDNAME:  # 並行して追加された場合は無視
                raise
    return n


def ensure(db):
    """リクエスト内で1回だけ確認して不足分を追加する（失敗しても例外は投げない）"""
    if getattr(db, 'ledger_schema_checked', False) or db.in_transaction:
        return
    db.ledger_schema_checked = True
    try:
        apply(db)
    except Exception as e:
        sys.stderr.write('[furyo-dacho] ledger schema check failed: %s\n' % e)


def has_column(db, column):
    cols = getattr(db, 'ledger_columns', None)
    if cols is None:
        try:
            cols = _columns(db)
        except Exception:
            cols = set()
        db.ledger_columns = cols
    return column in cols
