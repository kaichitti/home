"""
古物台帳

- 削除は論理削除（deleted_at）のみ。すべての操作で tenant_id を条件に入れる。
- 過去年度のデータは変更・削除できない（古物営業法に合わせた運用）。
"""
from ..db import DBError, ER_NO_SUCH_TABLE
from ..util import is_empty, parse_datetime, today_str, to_int, trim, like_escape
from . import ledger_schema
from .base import BaseModel

SALES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS `sales` (
                        `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        `tenant_id`   INT UNSIGNED    NOT NULL,
                        `ledger_id`   BIGINT UNSIGNED NOT NULL,
                        `member_code` VARCHAR(50)     NULL DEFAULT NULL,
                        `quantity`    INT UNSIGNED    NOT NULL DEFAULT 1,
                        `sale_amount` DECIMAL(12,0)   NULL DEFAULT NULL,
                        `sold_at`     DATETIME        NOT NULL,
                        `note`        VARCHAR(512)    NULL DEFAULT NULL,
                        `created_by`  INT UNSIGNED    NULL DEFAULT NULL,
                        `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (`id`),
                        INDEX `idx_sales_tenant_sold` (`tenant_id`, `sold_at`),
                        INDEX `idx_sales_ledger_id`   (`ledger_id`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""


class LedgerError(RuntimeError):
    """利用者に表示するメッセージ付きのエラー"""


def fiscal_year_of(date_value):
    """会計年度（4月始まり）。例: 2024-03-31 → 2023, 2024-04-01 → 2024"""
    dt = parse_datetime(str(date_value or ''))
    if dt is None:
        return 1969  # PHP の strtotime が失敗した場合（1970-01-01 扱い）と同じ
    return dt.year if dt.month >= 4 else dt.year - 1


def _opt(data, key):
    v = data.get(key)
    return None if v is None or v == '' else v


def _like(v):
    return '%' + like_escape(str(v)) + '%'


def _main_values(data):
    """作成・更新で共通の列の値"""
    age = data.get('counterpart_age')
    return [
        data['transaction_date'],
        data['transaction_type'],
        data.get('transaction_type_note'),
        data['item_category'],
        data.get('item_category_note') if data['item_category'] == 'other' else None,
        data['item_name'],
        _opt(data, 'serial_number'),
        data.get('item_description'),
        to_int(data.get('quantity', 1) if data.get('quantity') is not None else 1),
        data.get('transaction_amount'),
        _opt(data, 'member_code'),
        'corporate' if data.get('counterpart_type') == 'corporate' else 'individual',
        data['counterpart_name'],
        data['counterpart_address'],
        _opt(data, 'counterpart_occupation'),
        to_int(age) if age is not None and age != '' else None,
        _opt(data, 'counterpart_phone'),
        _opt(data, 'counterpart_contact_name'),
        _opt(data, 'counterpart_account'),
        _opt(data, 'counterpart_note'),
        _opt(data, 'id_document_type'),
        _opt(data, 'id_document_number'),
    ]


class Ledger(BaseModel):
    table = 'ledgers'

    def __init__(self, db):
        super().__init__(db)
        # 後から追加した列（本人確認書類「その他」の内容・販売予定価格）を未適用の環境でも補う
        ledger_schema.ensure(db)

    def _optional_values(self, data):
        """後から追加した任意列の値（列が無い環境では保存しない）"""
        values = {}
        if ledger_schema.has_column(self.db, 'id_document_type_note'):
            note = trim(str(data.get('id_document_type_note') or ''))
            # 「その他」以外では補足を保存しない（種別を変えた後に古い補足が残らないように）
            values['id_document_type_note'] = note if data.get('id_document_type') == 'other' and note != '' else None
        if ledger_schema.has_column(self.db, 'sale_price'):
            price = trim(str(data.get('sale_price') if data.get('sale_price') is not None else ''))
            values['sale_price'] = to_int(price) if price != '' else None
        return values

    def _save_optional(self, ledger_id, tenant_id, data, only_live=False):
        optional = self._optional_values(data)
        if not optional:
            return
        sets = ', '.join('`%s` = ?' % c for c in optional)
        sql = "UPDATE `ledgers` SET " + sets + " WHERE `id` = ? AND `tenant_id` = ?"
        if only_live:
            sql += " AND `deleted_at` IS NULL"
        self.db.execute(sql, list(optional.values()) + [int(ledger_id), int(tenant_id)])

    # ------------------------------------------------------------------
    # 一覧・取得
    # ------------------------------------------------------------------
    def find_all(self, tenant_id, filters=None, page=1, per_page=50):
        """一覧（絞り込み + ページ送り）。{'records': [...], 'total': 件数} を返す"""
        try:
            return self._find_all(tenant_id, filters or {}, page, per_page)
        except DBError as e:
            # sales テーブルが無い（マイグレーション未実行）環境でも一覧が開けるように作成する
            if e.code == ER_NO_SUCH_TABLE:
                self.db.execute(SALES_TABLE_SQL)
                return self._find_all(tenant_id, filters or {}, page, per_page)
            raise

    def _find_all(self, tenant_id, f, page, per_page):
        where = ['l.tenant_id = ?', 'l.deleted_at IS NULL']
        params = [int(tenant_id)]

        def has(k):
            return not is_empty(f.get(k))

        if has('date_from'):
            where.append('l.transaction_date >= ?')
            params.append(f['date_from'])
        if has('date_to'):
            where.append('l.transaction_date <= ?')
            params.append(f['date_to'])
        if has('item_category'):
            where.append('l.item_category = ?')
            params.append(f['item_category'])
        if has('transaction_type'):
            where.append('l.transaction_type = ?')
            params.append(f['transaction_type'])
        # 部分一致検索（「%」「_」は文字として検索する）
        for key, col in (('item_name', 'l.item_name'), ('counterpart_name', 'l.counterpart_name'),
                         ('serial_number', 'l.serial_number')):
            if has(key) and isinstance(f[key], str):
                where.append(col + ' LIKE ?')
                params.append(_like(f[key]))
        if has('approval_status') and f['approval_status'] in ('pending', 'approved'):
            where.append('l.approval_status = ?')
            params.append(f['approval_status'])
        if has('registered_by_id'):
            where.append('l.registered_by = ?')
            params.append(to_int(f['registered_by_id']))
        if has('branch_id'):
            where.append('l.branch_id = ?')
            params.append(to_int(f['branch_id']))
        if has('fiscal_year'):
            where.append('l.fiscal_year = ?')
            params.append(to_int(f['fiscal_year']))
        if not has('date_from') and has('transaction_date_from'):
            where.append('l.transaction_date >= ?')
            params.append(f['transaction_date_from'])
        if not has('date_to') and has('transaction_date_to'):
            where.append('l.transaction_date <= ?')
            params.append(f['transaction_date_to'])

        clause = ' AND '.join(where)
        offset = (int(page) - 1) * int(per_page)
        total = int(self.db.value("SELECT COUNT(*) FROM `ledgers` l WHERE " + clause, params) or 0)
        records = self.db.query(
            """SELECT l.*,
                       b.name AS branch_name,
                       u.display_name AS registered_by_name,
                       COALESCE(sq.sold_qty, 0) AS sold_quantity
                FROM `ledgers` l
                LEFT JOIN `branches` b ON b.id = l.branch_id
                LEFT JOIN `users`    u ON u.id  = l.registered_by
                LEFT JOIN (
                    SELECT `ledger_id`, SUM(`quantity`) AS sold_qty
                    FROM `sales` GROUP BY `ledger_id`
                ) sq ON sq.`ledger_id` = l.id
                WHERE """ + clause + """
                ORDER BY l.transaction_date DESC, l.id DESC
                LIMIT ? OFFSET ?""", params + [int(per_page), offset])
        return {'records': records, 'total': total}

    def find_by_id(self, ledger_id, tenant_id):
        return self.db.query_one(
            """SELECT l.*,
                    b.name AS branch_name,
                    u.display_name AS registered_by_name,
                    uu.display_name AS updated_by_name,
                    MAX(CASE WHEN lf.file_type = 'id_document'      THEN 1 END) AS has_id_document,
                    MAX(CASE WHEN lf.file_type = 'purchase_receipt' THEN 1 END) AS has_receipt_form
             FROM `ledgers` l
             LEFT JOIN `branches`     b  ON b.id  = l.branch_id
             LEFT JOIN `users`        u  ON u.id  = l.registered_by
             LEFT JOIN `users`        uu ON uu.id = l.updated_by
             LEFT JOIN `ledger_files` lf ON lf.ledger_id = l.id
             WHERE l.id = ? AND l.tenant_id = ? AND l.deleted_at IS NULL
             GROUP BY l.id, b.name, u.display_name, uu.display_name""", (int(ledger_id), int(tenant_id)))

    # ------------------------------------------------------------------
    # 作成・更新・削除
    # ------------------------------------------------------------------
    def create(self, tenant_id, data):
        """作成する（会計年度は取引日から自動で計算する）"""
        fy = fiscal_year_of(data['transaction_date'])
        new_id = self.db.insert(
            """INSERT INTO `ledgers` (
                `tenant_id`, `branch_id`, `transaction_date`, `transaction_type`, `transaction_type_note`,
                `item_category`, `item_category_note`, `item_name`, `serial_number`, `item_description`, `quantity`, `transaction_amount`,
                `member_code`, `counterpart_type`,
                `counterpart_name`, `counterpart_address`, `counterpart_occupation`, `counterpart_age`, `counterpart_phone`,
                `counterpart_contact_name`, `counterpart_account`, `counterpart_note`,
                `id_document_type`, `id_document_number`,
                `registered_by`, `updated_by`, `fiscal_year`
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [int(tenant_id), data['branch_id']] + _main_values(data)
            + [data['registered_by'], data['registered_by'], fy])
        self._save_optional(new_id, tenant_id, data)
        return new_id

    def update(self, ledger_id, tenant_id, user_id, role, data):
        """
        更新する（LedgerError: 権限不足・過去年度・販売済数を下回る数量）
          管理者は全件、一般ユーザーは自分が登録したものだけ更新できる。
        """
        existing = self.find_by_id(ledger_id, tenant_id)
        if existing is None:
            raise LedgerError('台帳が見つかりません。')
        if int(existing['fiscal_year']) != fiscal_year_of(today_str()):
            raise LedgerError('過去年度のデータは編集できません。')
        if role != 'admin' and int(existing['registered_by'] or 0) != int(user_id):
            raise LedgerError('自分が登録したレコードのみ編集できます。')

        # 数量は販売済数を下回る値にできない。同時に POS 等で販売されても崩れないよう、
        # 台帳の行をロックしてから最新の販売数で確認し、そのまま更新する
        new_qty = to_int(data.get('quantity') if data.get('quantity') is not None else 1)
        own_tx = not self.db.in_transaction
        if own_tx:
            self.db.begin()
        try:
            locked = self.db.query_one(
                """SELECT `quantity` FROM `ledgers`
                 WHERE `id` = ? AND `tenant_id` = ? AND `deleted_at` IS NULL
                 FOR UPDATE""", (int(ledger_id), int(tenant_id)))
            if locked is None:
                raise LedgerError('台帳が見つかりません。')
            try:
                sold = int(self.db.value(
                    "SELECT COALESCE(SUM(`quantity`), 0) FROM `sales` WHERE `ledger_id` = ? AND `tenant_id` = ?",
                    (int(ledger_id), int(tenant_id))) or 0)
            except DBError:
                sold = 0  # sales テーブルが無い環境では販売ゼロ
            if new_qty < sold:
                raise LedgerError('数量を販売済数（%d点）より小さくすることはできません。先に販売記録を調整してください。' % sold)

            fy = fiscal_year_of(data['transaction_date'])
            branch_id = to_int(data['branch_id']) if not is_empty(data.get('branch_id')) else int(existing['branch_id'])
            self.db.execute(
                """UPDATE `ledgers` SET
                    `branch_id` = ?,
                    `transaction_date` = ?, `transaction_type` = ?, `transaction_type_note` = ?,
                    `item_category` = ?, `item_category_note` = ?, `item_name` = ?, `serial_number` = ?, `item_description` = ?,
                    `quantity` = ?, `transaction_amount` = ?,
                    `member_code` = ?, `counterpart_type` = ?,
                    `counterpart_name` = ?, `counterpart_address` = ?,
                    `counterpart_occupation` = ?, `counterpart_age` = ?, `counterpart_phone` = ?,
                    `counterpart_contact_name` = ?, `counterpart_account` = ?, `counterpart_note` = ?,
                    `id_document_type` = ?, `id_document_number` = ?,
                    `fiscal_year` = ?,
                    `updated_by` = ?, `updated_at` = NOW()
                 WHERE `id` = ? AND `tenant_id` = ? AND `deleted_at` IS NULL""",
                [branch_id] + _main_values(data) + [fy, int(user_id), int(ledger_id), int(tenant_id)])
            self._save_optional(ledger_id, tenant_id, data, only_live=True)
            if own_tx:
                self.db.commit()
            return True
        except BaseException:
            if own_tx and self.db.in_transaction:
                self.db.rollback()
            raise

    def soft_delete(self, ledger_id, tenant_id, user_id):
        if self.find_by_id(ledger_id, tenant_id) is None:
            raise LedgerError('台帳が見つかりません。')
        self.db.execute(
            """UPDATE `ledgers`
             SET `deleted_at` = NOW(), `updated_by` = ?, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ? AND `deleted_at` IS NULL""",
            (int(user_id), int(ledger_id), int(tenant_id)))
        return True

    # ------------------------------------------------------------------
    # 集計
    # ------------------------------------------------------------------
    def count_by_tenant(self, tenant_id, filters=None):
        f = filters or {}
        where = ['tenant_id = ?', 'deleted_at IS NULL']
        params = [int(tenant_id)]
        if not is_empty(f.get('branch_id')):
            where.append('branch_id = ?')
            params.append(to_int(f['branch_id']))
        if not is_empty(f.get('fiscal_year')):
            where.append('fiscal_year = ?')
            params.append(to_int(f['fiscal_year']))
        if not is_empty(f.get('transaction_date_from')):
            where.append('transaction_date >= ?')
            params.append(f['transaction_date_from'])
        if not is_empty(f.get('transaction_date_to')):
            where.append('transaction_date <= ?')
            params.append(f['transaction_date_to'])
        return int(self.db.value("SELECT COUNT(*) FROM `ledgers` WHERE " + ' AND '.join(where), params) or 0)

    def get_fiscal_year(self, date_value):
        return fiscal_year_of(date_value)

    def get_years(self, tenant_id):
        """台帳に存在する年度の一覧（新しい順）"""
        return self.db.column(
            """SELECT DISTINCT `fiscal_year`
             FROM `ledgers`
             WHERE `tenant_id` = ? AND `deleted_at` IS NULL
             ORDER BY `fiscal_year` DESC""", (int(tenant_id),))

    def count_this_month(self, tenant_id):
        return int(self.db.value(
            """SELECT COUNT(*) FROM `ledgers`
             WHERE `tenant_id` = ? AND `deleted_at` IS NULL
               AND `transaction_date` >= DATE_FORMAT(NOW(), '%Y-%m-01')
               AND `transaction_date` < DATE_FORMAT(DATE_ADD(NOW(), INTERVAL 1 MONTH), '%Y-%m-01')""",
            (int(tenant_id),)) or 0)

    def get_recent(self, tenant_id, limit=5):
        return self.db.query(
            """SELECT l.*,
                    b.name AS branch_name,
                    u.display_name AS registered_by_name
             FROM `ledgers` l
             LEFT JOIN `branches` b ON b.id = l.branch_id
             LEFT JOIN `users`    u ON u.id = l.registered_by
             WHERE l.tenant_id = ? AND l.deleted_at IS NULL
             ORDER BY l.created_at DESC, l.id DESC
             LIMIT ?""", (int(tenant_id), int(limit)))
