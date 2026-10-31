"""
販売記録（在庫管理）

台帳（仕入記録）1件に対して複数回の販売を記録できる。
残在庫 = ledgers.quantity - SUM(sales.quantity)
"""
import re

from ..db import DBError, ER_BAD_FIELD, ER_DUP_FIELDNAME, ER_DUP_KEYNAME, ER_NO_SUCH_TABLE
from ..util import is_empty, like_escape, to_int
from . import ledger_schema
from .base import BaseModel

CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS `sales` (
                `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `tenant_id`   INT UNSIGNED    NOT NULL,
                `ledger_id`   BIGINT UNSIGNED NOT NULL,
                `transaction_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT 'POS会計（pos_transactions.id）。台帳画面からの販売はNULL',
                `member_code` VARCHAR(50)     NULL DEFAULT NULL COMMENT '販売先の会員番号（任意）',
                `quantity`    INT UNSIGNED    NOT NULL DEFAULT 1,
                `sale_amount` DECIMAL(12,0)   NULL DEFAULT NULL,
                `sold_at`     DATETIME        NOT NULL,
                `note`        VARCHAR(512)    NULL DEFAULT NULL,
                `created_by`  INT UNSIGNED    NULL DEFAULT NULL,
                `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                INDEX `idx_sales_tenant_sold` (`tenant_id`, `sold_at`),
                INDEX `idx_sales_ledger_id`   (`ledger_id`),
                INDEX `idx_sales_transaction_id` (`transaction_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
              COMMENT='販売記録（在庫管理）'"""

MEMBER_CODE_COLUMN_DDL = """ALTER TABLE `sales` ADD COLUMN `member_code` VARCHAR(50) NULL DEFAULT NULL
                 COMMENT '販売先の会員番号（任意）' AFTER `ledger_id`"""

_ID_CANDIDATE_RE = re.compile(r'(?:#|L|l)?0*([1-9][0-9]{0,17})')


def period_expr(column, granularity):
    """期間の単位ごとの GROUP BY 式（ラベルにもなる）"""
    if granularity == 'year':
        return "DATE_FORMAT(%s, '%%Y')" % column
    if granularity == 'month':
        return "DATE_FORMAT(%s, '%%Y-%%m')" % column
    if granularity == 'week':
        # 週の開始日（月曜）をラベルにする
        return "DATE_FORMAT(DATE_SUB(DATE(%s), INTERVAL WEEKDAY(%s) DAY), '%%Y-%%m-%%d')" % (column, column)
    return "DATE_FORMAT(%s, '%%Y-%%m-%%d')" % column


def _opt(data, key):
    v = data.get(key)
    return None if v is None or v == '' else v


class Sale(BaseModel):
    table = 'sales'

    def _add_transaction_id_column(self):
        from .pos_schema import SALES_TRANSACTION_COLUMN_DDL
        try:
            self.db.execute(SALES_TRANSACTION_COLUMN_DDL)
        except DBError as e:
            if e.code not in (ER_DUP_FIELDNAME, ER_DUP_KEYNAME):
                raise

    def _add_member_code_column(self):
        try:
            self.db.execute(MEMBER_CODE_COLUMN_DDL)
        except DBError as e:
            if e.code != ER_DUP_FIELDNAME:
                raise

    def _with_table(self, fn):
        try:
            return fn()
        except DBError as e:
            if e.code == ER_NO_SUCH_TABLE:
                self.db.execute(CREATE_TABLE_SQL)
                return fn()
            # sales テーブルはあるが列が足りない（マイグレーション未実行）環境では列を補ってやり直す。
            # DDL は暗黙のコミットを伴うため、トランザクション中は補わない
            if e.code == ER_BAD_FIELD and not self.db.in_transaction:
                if 'member_code' in e.message:
                    self._add_member_code_column()
                    return fn()
                if 'transaction_id' in e.message:
                    self._add_transaction_id_column()
                    return fn()
            raise

    def ensure_schema(self):
        """sales テーブルと member_code / transaction_id 列があることを保証する（トランザクション開始前に呼ぶ）"""
        if getattr(self.db, 'sales_schema_ok', False) or self.db.in_transaction:
            return
        try:
            cols = {str(c.get('Field') or '') for c in self.db.query("SHOW COLUMNS FROM `sales`")}
            if 'member_code' not in cols:
                self._add_member_code_column()
            if 'transaction_id' not in cols:
                self._add_transaction_id_column()
            self.db.sales_schema_ok = True
        except DBError as e:
            if e.code == ER_NO_SUCH_TABLE:
                self.db.execute(CREATE_TABLE_SQL)
                self.db.sales_schema_ok = True
            # それ以外は本処理側で通常どおりエラー処理する

    def create(self, tenant_id, data):
        return self._with_table(lambda: self.db.insert(
            """INSERT INTO `sales`
                    (`tenant_id`, `ledger_id`, `transaction_id`, `member_code`, `quantity`, `sale_amount`, `sold_at`, `note`, `created_by`)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(tenant_id), to_int(data['ledger_id']),
             to_int(data['transaction_id']) if not is_empty(data.get('transaction_id')) else None,
             _opt(data, 'member_code'), max(1, to_int(data['quantity'])), _opt(data, 'sale_amount'),
             data['sold_at'], _opt(data, 'note'), data.get('created_by'))))

    def find_by_id(self, sale_id, tenant_id):
        return self._with_table(lambda: self.db.query_one(
            "SELECT * FROM `sales` WHERE `id` = ? AND `tenant_id` = ?", (int(sale_id), int(tenant_id))))

    def find_by_ledger(self, ledger_id, tenant_id):
        """台帳の販売記録一覧（記録者名・POSレシート番号つき）"""
        def run():
            try:
                return self.db.query(
                    """SELECT s.*, u.display_name AS created_by_name, t.receipt_no AS pos_receipt_no
                     FROM `sales` s
                     LEFT JOIN `users` u ON u.id = s.created_by
                     LEFT JOIN `pos_transactions` t ON t.id = s.transaction_id AND t.tenant_id = s.tenant_id
                     WHERE s.`ledger_id` = ? AND s.`tenant_id` = ?
                     ORDER BY s.`sold_at` DESC, s.`id` DESC""", (int(ledger_id), int(tenant_id)))
            except DBError as e:
                # POS テーブル・列が無い環境（マイグレーション前）は従来の一覧
                if e.code not in (ER_NO_SUCH_TABLE, ER_BAD_FIELD):
                    raise
            return self.db.query(
                """SELECT s.*, u.display_name AS created_by_name
                 FROM `sales` s
                 LEFT JOIN `users` u ON u.id = s.created_by
                 WHERE s.`ledger_id` = ? AND s.`tenant_id` = ?
                 ORDER BY s.`sold_at` DESC, s.`id` DESC""", (int(ledger_id), int(tenant_id)))
        return self._with_table(run)

    def lock_ledgers(self, ledger_ids, tenant_id):
        """
        トランザクション内で台帳行をまとめてロックし、{台帳ID: {'quantity', 'sold'}} を返す
        （存在しない・削除済みの台帳は含まない）。

        在庫を変える処理（POS会計・販売の追加/修正・台帳の数量変更）は、必ず先にこれでロックを取る。
        - 台帳行は1つの SQL で ID の昇順にロックする（端末間でロック順がそろい、デッドロックしない）
        - 販売数の合計はロック取得「後」に通常の SELECT で読む（先行処理のコミット済みの販売も見える）
        - そのため、トランザクション開始後はこれより前に通常の SELECT を実行しないこと
        """
        ids = sorted({i for i in (to_int(x) for x in ledger_ids) if i > 0})
        if not ids:
            return {}
        rows = self.db.query(
            """SELECT `id`, `quantity` FROM `ledgers` FORCE INDEX (PRIMARY)
             WHERE `tenant_id` = ? AND `deleted_at` IS NULL AND `id` IN (%s)
             ORDER BY `id` ASC
             FOR UPDATE""" % ','.join('?' * len(ids)), [int(tenant_id)] + ids)
        state = {int(r['id']): {'quantity': int(r['quantity']), 'sold': 0} for r in rows}
        if not state:
            return {}
        locked = list(state.keys())
        for r in self.db.query(
                """SELECT `ledger_id`, COALESCE(SUM(`quantity`), 0) AS sold FROM `sales`
             WHERE `tenant_id` = ? AND `ledger_id` IN (%s)
             GROUP BY `ledger_id`""" % ','.join('?' * len(locked)), [int(tenant_id)] + locked):
            state[int(r['ledger_id'])]['sold'] = int(r['sold'])
        return state

    def sold_quantity(self, ledger_id, tenant_id):
        return self._with_table(lambda: int(self.db.value(
            """SELECT COALESCE(SUM(`quantity`), 0) FROM `sales`
                 WHERE `ledger_id` = ? AND `tenant_id` = ?""", (int(ledger_id), int(tenant_id))) or 0))

    def update(self, sale_id, tenant_id, data):
        self._with_table(lambda: self.db.execute(
            """UPDATE `sales` SET
                    `member_code` = ?, `quantity` = ?, `sale_amount` = ?, `sold_at` = ?, `note` = ?
                 WHERE `id` = ? AND `tenant_id` = ?""",
            (_opt(data, 'member_code'), max(1, to_int(data['quantity'])), _opt(data, 'sale_amount'),
             data['sold_at'], _opt(data, 'note'), int(sale_id), int(tenant_id))))
        return True

    def delete(self, sale_id, tenant_id):
        self._with_table(lambda: self.db.execute(
            "DELETE FROM `sales` WHERE `id` = ? AND `tenant_id` = ?", (int(sale_id), int(tenant_id))))
        return True

    def aggregate(self, tenant_id, date_from, date_to, granularity):
        """売上の推移"""
        expr = period_expr('s.`sold_at`', granularity)
        return self._with_table(lambda: self.db.query(
            """SELECT """ + expr + """ AS period,
                        COALESCE(SUM(s.`sale_amount`), 0) AS total,
                        COUNT(*) AS cnt,
                        COALESCE(SUM(s.`quantity`), 0) AS qty
                 FROM `sales` s
                 WHERE s.`tenant_id` = ? AND s.`sold_at` >= ? AND s.`sold_at` < DATE_ADD(?, INTERVAL 1 DAY)
                 GROUP BY period
                 ORDER BY period ASC""", (int(tenant_id), date_from + ' 00:00:00', date_to)))

    def aggregate_purchases(self, tenant_id, date_from, date_to, granularity):
        """仕入（台帳）の推移"""
        expr = period_expr('l.`transaction_date`', granularity)
        return self.db.query(
            """SELECT """ + expr + """ AS period,
                    COALESCE(SUM(l.`transaction_amount`), 0) AS total,
                    COUNT(*) AS cnt,
                    COALESCE(SUM(l.`quantity`), 0) AS qty
             FROM `ledgers` l
             WHERE l.`tenant_id` = ? AND l.`deleted_at` IS NULL
               AND l.`transaction_date` >= ? AND l.`transaction_date` <= ?
             GROUP BY period
             ORDER BY period ASC""", (int(tenant_id), date_from, date_to))

    def search_in_stock(self, tenant_id, keyword='', limit=30, exact=False):
        """
        POS用: 在庫のある台帳を検索する（残数つき）
        - 品名・シリアル番号の部分一致。数字（「#123」「L123」も可）は台帳番号としても照合する
        - exact=True（バーコード読取・Enter確定）はシリアル番号の完全一致と台帳番号の一致のみ
        - LIKE のワイルドカード（% _）は文字として扱う
        """
        def run():
            sale_price_col = 'l.`sale_price`' if ledger_schema.has_column(self.db, 'sale_price') else 'NULL'
            sql = """SELECT l.`id`, l.`item_name`, l.`serial_number`, l.`quantity`,
                           l.`transaction_amount`, l.`transaction_date`, l.`approval_status`,
                           """ + sale_price_col + """ AS sale_price,
                           COALESCE(s.sold_qty, 0) AS sold_quantity,
                           (l.`quantity` - COALESCE(s.sold_qty, 0)) AS remaining
                    FROM `ledgers` l
                    LEFT JOIN (
                        SELECT `ledger_id`, SUM(`quantity`) AS sold_qty
                        FROM `sales` WHERE `tenant_id` = ? GROUP BY `ledger_id`
                    ) s ON s.`ledger_id` = l.`id`
                    WHERE l.`tenant_id` = ? AND l.`deleted_at` IS NULL
                      AND (l.`quantity` - COALESCE(s.sold_qty, 0)) > 0"""
            params = [int(tenant_id), int(tenant_id)]
            id_candidate = 0
            m = _ID_CANDIDATE_RE.fullmatch(keyword)
            if m:
                id_candidate = int(m.group(1))
            if keyword != '':
                if exact:
                    sql += " AND (l.`serial_number` = ?" + (" OR l.`id` = ?" if id_candidate > 0 else '') + ")"
                    params.append(keyword)
                else:
                    like = '%' + like_escape(keyword) + '%'
                    sql += (" AND (l.`item_name` LIKE ? OR l.`serial_number` LIKE ?"
                            + (" OR l.`id` = ?" if id_candidate > 0 else '') + ")")
                    params += [like, like]
                if id_candidate > 0:
                    params.append(id_candidate)
            sql += " ORDER BY l.`id` DESC LIMIT %d" % max(1, min(100, int(limit)))
            return self.db.query(sql, params)
        return self._with_table(run)
