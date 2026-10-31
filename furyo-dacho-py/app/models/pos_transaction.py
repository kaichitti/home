"""
POS 会計（取引）

会計1回 = pos_transactions 1行 + 明細（pos_transaction_items）+ 販売記録（sales）。
在庫は販売記録の数量合計で減る。取消時は販売記録を削除して在庫を戻し、
会計と明細はレシート再発行・監査のためにそのまま残す（status = voided）。
"""
from ..util import is_empty, like_escape, to_int
from .base import BaseModel


def _like(v):
    return '%' + like_escape(str(v)) + '%'


def _none_if_empty(v):
    return None if v is None or v == '' else v


class PosTransaction(BaseModel):
    table = 'pos_transactions'

    def find_by_id(self, tx_id, tenant_id):
        return self.db.query_one(
            """SELECT t.*, b.name AS branch_name, vu.display_name AS voided_by_name
             FROM `pos_transactions` t
             LEFT JOIN `branches` b ON b.id = t.branch_id
             LEFT JOIN `users` vu ON vu.id = t.voided_by
             WHERE t.`id` = ? AND t.`tenant_id` = ?""", (int(tx_id), int(tenant_id)))

    def find_by_token(self, tenant_id, token):
        return self.db.query_one("SELECT * FROM `pos_transactions` WHERE `tenant_id` = ? AND `client_token` = ?",
                                 (int(tenant_id), token))

    def items(self, tx_id, tenant_id):
        return self.db.query(
            """SELECT * FROM `pos_transaction_items`
             WHERE `transaction_id` = ? AND `tenant_id` = ?
             ORDER BY `line_no` ASC, `id` ASC""", (int(tx_id), int(tenant_id)))

    def next_receipt_no(self, tenant_id, biz_date):
        """レシート番号を採番する（テナント・日付ごとの連番。トランザクション内で呼ぶ。行ロックで重複しない）"""
        self.db.execute(
            """INSERT INTO `pos_counters` (`tenant_id`, `biz_date`, `last_no`)
             VALUES (?, ?, LAST_INSERT_ID(1))
             ON DUPLICATE KEY UPDATE `last_no` = LAST_INSERT_ID(`last_no` + 1)""", (int(tenant_id), biz_date))
        no = int(self.db.value("SELECT LAST_INSERT_ID()") or 0)
        if no < 1:
            raise RuntimeError('レシート番号の採番に失敗しました。')
        return biz_date.replace('-', '') + '-' + '%04d' % no

    def insert(self, d):
        return self.db.insert(
            """INSERT INTO `pos_transactions`
                (`tenant_id`, `branch_id`, `register_no`, `receipt_no`, `client_token`, `status`, `member_code`,
                 `member_id`, `member_name`, `item_count`,
                 `subtotal`, `discount_type`, `discount_value`, `discount_amount`, `tax_mode`, `tax_rate`,
                 `tax_amount`, `total`, `payment_method`, `tendered`, `change_amount`, `payment_ref`, `note`,
                 `store_info`, `cashier_name`, `receipt_status`, `created_by`, `created_at`)
             VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (d['tenant_id'], d['branch_id'], d.get('register_no'), d['receipt_no'], d['client_token'],
             _none_if_empty(d['member_code']), d.get('member_id'), _none_if_empty(d.get('member_name')),
             d['item_count'], d['subtotal'], d['discount_type'], d['discount_value'], d['discount_amount'],
             d['tax_mode'], d['tax_rate'], d['tax_amount'], d['total'],
             d['payment_method'], d['tendered'], d['change_amount'],
             _none_if_empty(d['payment_ref']), _none_if_empty(d['note']),
             d['store_info'], d['cashier_name'], d['receipt_status'], d['created_by'], d['created_at']))

    def insert_item(self, d):
        return self.db.insert(
            """INSERT INTO `pos_transaction_items`
                (`transaction_id`, `tenant_id`, `ledger_id`, `sale_id`, `line_no`, `item_name`, `serial_number`,
                 `quantity`, `unit_price`, `line_discount`, `amount`, `allocated_amount`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (d['transaction_id'], d['tenant_id'], d['ledger_id'], d['sale_id'], d['line_no'],
             d['item_name'], _none_if_empty(d.get('serial_number')),
             d['quantity'], d['unit_price'], d['line_discount'], d['amount'], d['allocated_amount']))

    def record_print(self, tx_id, tenant_id, doc, result):
        """
        レシート・領収書の印刷結果を記録する（doc: receipt|ryoshu, result: printed|failed）
        {'before': {...}, 'after': {...}} を返す（会計が無ければ None）
        """
        db = self.db
        db.begin()
        try:
            before = db.query_one(
                """SELECT `receipt_status`, `print_count`, `ryoshu_count` FROM `pos_transactions`
                 WHERE `id` = ? AND `tenant_id` = ? FOR UPDATE""", (int(tx_id), int(tenant_id)))
            if before is None:
                db.rollback()
                return None
            if doc == 'ryoshu':
                if result == 'printed':
                    db.execute("UPDATE `pos_transactions` SET `ryoshu_count` = `ryoshu_count` + 1 WHERE `id` = ? AND `tenant_id` = ?",
                               (int(tx_id), int(tenant_id)))
            elif result == 'printed':
                db.execute(
                    """UPDATE `pos_transactions`
                     SET `print_count` = `print_count` + 1, `receipt_status` = 'printed', `last_printed_at` = NOW()
                     WHERE `id` = ? AND `tenant_id` = ?""", (int(tx_id), int(tenant_id)))
            elif int(before['print_count']) == 0:
                # 一度も印刷できていない場合のみ「印刷失敗」にする（再発行の失敗で印刷済みを上書きしない）
                db.execute("UPDATE `pos_transactions` SET `receipt_status` = 'print_failed' WHERE `id` = ? AND `tenant_id` = ?",
                           (int(tx_id), int(tenant_id)))
            after = db.query_one(
                "SELECT `receipt_status`, `print_count`, `ryoshu_count` FROM `pos_transactions` WHERE `id` = ? AND `tenant_id` = ?",
                (int(tx_id), int(tenant_id)))
            db.commit()
            return {'before': before, 'after': after}
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise

    def void(self, tx_id, tenant_id, user_id, reason):
        """会計を取り消す（販売記録を削除して在庫を戻す）。取消前の会計を返す（取り消せない状態なら None）"""
        db = self.db
        db.begin()
        try:
            tx = db.query_one("SELECT * FROM `pos_transactions` WHERE `id` = ? AND `tenant_id` = ? FOR UPDATE",
                              (int(tx_id), int(tenant_id)))
            if tx is None or tx['status'] != 'completed':
                db.rollback()
                return None
            # 販売記録は主キーで削除する（索引範囲のギャップロックで他の会計を止めない）
            sale_ids = [int(x) for x in db.column(
                """SELECT `sale_id` FROM `pos_transaction_items`
                 WHERE `transaction_id` = ? AND `tenant_id` = ? AND `sale_id` IS NOT NULL""",
                (int(tx_id), int(tenant_id)))]
            if sale_ids:
                db.execute(
                    "DELETE FROM `sales` WHERE `tenant_id` = ? AND `transaction_id` = ? AND `id` IN (%s)"
                    % ','.join('?' * len(sale_ids)), [int(tenant_id), int(tx_id)] + sale_ids)
            db.execute(
                """UPDATE `pos_transactions`
                 SET `status` = 'voided', `voided_by` = ?, `voided_at` = NOW(), `void_reason` = ?
                 WHERE `id` = ? AND `tenant_id` = ?""", (int(user_id), reason, int(tx_id), int(tenant_id)))
            db.commit()
            return tx
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise

    def find_by_receipt_no(self, tenant_id, receipt_no):
        tx_id = self.db.value("SELECT `id` FROM `pos_transactions` WHERE `tenant_id` = ? AND `receipt_no` = ?",
                              (int(tenant_id), receipt_no))
        return None if tx_id is None else self.find_by_id(int(tx_id), tenant_id)

    def member_stats(self, tenant_id, member_ids):
        """会員ごとの購入実績（取消を除く）: {会員ID: {'count', 'total', 'last_at'}}"""
        ids = [i for i in (to_int(x) for x in member_ids) if i > 0]
        if not ids:
            return {}
        rows = self.db.query(
            """SELECT `member_id`, COUNT(*) AS cnt, COALESCE(SUM(`total`), 0) AS total, MAX(`created_at`) AS last_at
             FROM `pos_transactions`
             WHERE `tenant_id` = ? AND `status` = 'completed' AND `member_id` IN (%s)
             GROUP BY `member_id`""" % ','.join('?' * len(ids)), [int(tenant_id)] + ids)
        return {int(r['member_id']): {'count': int(r['cnt']), 'total': int(r['total']), 'last_at': r['last_at']}
                for r in rows}

    # ------------------------------------------------------------------
    # 検索
    # ------------------------------------------------------------------
    def _build_where(self, tenant_id, f):
        where = ['t.`tenant_id` = ?']
        params = [int(tenant_id)]

        def has(k):
            return not is_empty(f.get(k))

        if has('date_from'):
            where.append('t.`created_at` >= ?')
            params.append(str(f['date_from']) + ' 00:00:00')
        if has('date_to'):
            where.append('t.`created_at` < DATE_ADD(?, INTERVAL 1 DAY)')
            params.append(f['date_to'])
        if has('status') and f['status'] in ('completed', 'voided'):
            where.append('t.`status` = ?')
            params.append(f['status'])
        if has('payment_method'):
            where.append('t.`payment_method` = ?')
            params.append(f['payment_method'])
        if f.get('branch_id') is not None and f.get('branch_id') != '':
            where.append('t.`branch_id` = ?')
            params.append(to_int(f['branch_id']))
        if has('receipt_no'):
            where.append('t.`receipt_no` LIKE ?')
            params.append(_like(f['receipt_no']))
        if has('register_no'):
            where.append('t.`register_no` = ?')
            params.append(to_int(f['register_no']))
        if has('member_id'):
            where.append('t.`member_id` = ?')
            params.append(to_int(f['member_id']))
        if has('member'):
            # 会員番号の完全一致、または会員名の部分一致
            where.append('(t.`member_code` = ? OR t.`member_name` LIKE ?)')
            params += [str(f['member']), _like(f['member'])]
        if has('member_code'):
            where.append('t.`member_code` = ?')
            params.append(str(f['member_code']))
        if has('cashier'):
            where.append('t.`cashier_name` LIKE ?')
            params.append(_like(f['cashier']))
        if has('keyword'):
            where.append("""EXISTS (SELECT 1 FROM `pos_transaction_items` i
                                 WHERE i.`transaction_id` = t.`id` AND i.`tenant_id` = t.`tenant_id`
                                   AND (i.`item_name` LIKE ? OR i.`serial_number` LIKE ?))""")
            like = _like(f['keyword'])
            params += [like, like]
        return ' AND '.join(where), params

    def _item_where(self, tenant_id, filters):
        """明細検索の条件（取引の条件 ＋ 明細そのものの条件）"""
        f = dict(filters)
        keyword = str(f.pop('keyword', '') or '')
        ledger_id = to_int(f.get('ledger_id'))
        where, params = self._build_where(tenant_id, f)
        if keyword != '':
            where += ' AND (i.`item_name` LIKE ? OR i.`serial_number` LIKE ?)'
            like = _like(keyword)
            params += [like, like]
        if ledger_id > 0:
            where += ' AND i.`ledger_id` = ?'
            params.append(ledger_id)
        return where, params

    def search_items(self, tenant_id, filters, page=1, per_page=50):
        """会計明細の検索: {'rows', 'total', 'qty', 'amount', 'allocated'}"""
        where, params = self._item_where(tenant_id, filters)
        agg = self.db.query_one(
            """SELECT COUNT(*) AS cnt,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN i.`quantity` END), 0) AS qty,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN i.`amount` END), 0) AS amount,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN i.`allocated_amount` END), 0) AS allocated
             FROM `pos_transaction_items` i
             JOIN `pos_transactions` t ON t.`id` = i.`transaction_id` AND t.`tenant_id` = i.`tenant_id`
             WHERE """ + where, params) or {}
        offset = max(0, (int(page) - 1) * int(per_page))
        rows = self.db.query(
            """SELECT i.*, t.`id` AS tx_id, t.`receipt_no`, t.`created_at`, t.`status`, t.`register_no`,
                    t.`payment_method`, t.`member_code`, t.`member_id`, t.`member_name`, t.`cashier_name`,
                    t.`print_count`, b.name AS branch_name
             FROM `pos_transaction_items` i
             JOIN `pos_transactions` t ON t.`id` = i.`transaction_id` AND t.`tenant_id` = i.`tenant_id`
             LEFT JOIN `branches` b ON b.id = t.branch_id
             WHERE """ + where + """
             ORDER BY t.`created_at` DESC, t.`id` DESC, i.`line_no` ASC
             LIMIT %d OFFSET %d""" % (int(per_page), int(offset)), params)
        return {
            'rows': rows,
            'total': to_int(agg.get('cnt')),
            'qty': to_int(agg.get('qty')),
            'amount': to_int(agg.get('amount')),
            'allocated': to_int(agg.get('allocated')),
        }

    def search(self, tenant_id, filters, page=1, per_page=50):
        """取引履歴の検索: {'rows', 'total', 'sum_total', 'sum_count'}"""
        where, params = self._build_where(tenant_id, filters)
        agg = self.db.query_one(
            """SELECT COUNT(*) AS cnt,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN t.`total` END), 0) AS sum_total,
                    COALESCE(SUM(CASE WHEN t.`status` = 'completed' THEN 1 END), 0) AS sum_count
             FROM `pos_transactions` t WHERE """ + where, params) or {'cnt': 0, 'sum_total': 0, 'sum_count': 0}
        offset = max(0, (int(page) - 1) * int(per_page))
        rows = self.db.query(
            """SELECT t.*, b.name AS branch_name,
                    (SELECT GROUP_CONCAT(i.`item_name` ORDER BY i.`line_no` SEPARATOR '、')
                     FROM `pos_transaction_items` i WHERE i.`transaction_id` = t.`id` AND i.`tenant_id` = t.`tenant_id`) AS item_names
             FROM `pos_transactions` t
             LEFT JOIN `branches` b ON b.id = t.branch_id
             WHERE """ + where + """
             ORDER BY t.`created_at` DESC, t.`id` DESC
             LIMIT %d OFFSET %d""" % (int(per_page), int(offset)), params)
        return {
            'rows': rows,
            'total': to_int(agg['cnt']),
            'sum_total': to_int(agg['sum_total']),
            'sum_count': to_int(agg['sum_count']),
        }

    def export_rows(self, tenant_id, filters, limit=20000, line_filter=False):
        """CSV 出力用（明細単位）。line_filter=True は明細検索の条件で出力する"""
        where, params = self._item_where(tenant_id, filters) if line_filter else self._build_where(tenant_id, filters)
        return self.db.query(
            """SELECT t.`created_at`, t.`receipt_no`, t.`register_no`, t.`status`, t.`payment_method`, t.`member_code`, t.`member_name`,
                    t.`cashier_name`, b.name AS branch_name, t.`subtotal`, t.`discount_amount`, t.`tax_mode`,
                    t.`tax_rate`, t.`tax_amount`, t.`total`, t.`tendered`, t.`change_amount`, t.`voided_at`, t.`void_reason`,
                    i.`line_no`, i.`ledger_id`, i.`item_name`, i.`serial_number`, i.`quantity`, i.`unit_price`,
                    i.`line_discount`, i.`amount`, i.`allocated_amount`
             FROM `pos_transactions` t
             JOIN `pos_transaction_items` i ON i.`transaction_id` = t.`id` AND i.`tenant_id` = t.`tenant_id`
             LEFT JOIN `branches` b ON b.id = t.branch_id
             WHERE """ + where + """
             ORDER BY t.`created_at` ASC, t.`id` ASC, i.`line_no` ASC
             LIMIT %d""" % int(limit), params)

    def register_numbers(self, tenant_id):
        """記録のあるレジ番号の一覧（絞り込みの選択肢）"""
        return [int(x) for x in self.db.column(
            """SELECT DISTINCT `register_no` FROM `pos_transactions`
             WHERE `tenant_id` = ? AND `register_no` IS NOT NULL ORDER BY `register_no`""", (int(tenant_id),))]

    def daily_summary(self, tenant_id, date, branch_id=None, register_no=None):
        """日計（レジ精算用の集計）。branch_id / register_no が None なら全拠点 / 全レジ"""
        where = "`tenant_id` = ? AND `created_at` >= ? AND `created_at` < DATE_ADD(?, INTERVAL 1 DAY)"
        params = [int(tenant_id), date + ' 00:00:00', date]
        if branch_id is not None:
            where += " AND `branch_id` = ?"
            params.append(int(branch_id))
        if register_no is not None:
            where += " AND `register_no` = ?"
            params.append(int(register_no))

        s = {
            'tx_count': 0, 'item_count': 0, 'subtotal': 0, 'discount': 0, 'tax': 0, 'total': 0,
            'void_count': 0, 'void_total': 0, 'cash_sales': 0,
            'by_method': {m: {'count': 0, 'total': 0} for m in ('cash', 'credit', 'emoney', 'qr', 'other')},
        }
        for r in self.db.query(
                """SELECT `status`, `payment_method`, COUNT(*) AS cnt,
                    COALESCE(SUM(`item_count`), 0) AS items, COALESCE(SUM(`subtotal`), 0) AS subtotal,
                    COALESCE(SUM(`discount_amount`), 0) AS discount, COALESCE(SUM(`tax_amount`), 0) AS tax,
                    COALESCE(SUM(`total`), 0) AS total
             FROM `pos_transactions` WHERE """ + where + """
             GROUP BY `status`, `payment_method`""", params):
            if r['status'] == 'voided':
                s['void_count'] += to_int(r['cnt'])
                s['void_total'] += to_int(r['total'])
                continue
            s['tx_count'] += to_int(r['cnt'])
            s['item_count'] += to_int(r['items'])
            s['subtotal'] += to_int(r['subtotal'])
            s['discount'] += to_int(r['discount'])
            s['tax'] += to_int(r['tax'])
            s['total'] += to_int(r['total'])
            m = str(r['payment_method'])
            if m in s['by_method']:
                s['by_method'][m]['count'] += to_int(r['cnt'])
                s['by_method'][m]['total'] += to_int(r['total'])
        s['cash_sales'] = s['by_method']['cash']['total']

        # 時間帯別（完了分）
        s['by_hour'] = {}
        for r in self.db.query(
                """SELECT HOUR(`created_at`) AS h, COUNT(*) AS cnt, COALESCE(SUM(`total`), 0) AS total
             FROM `pos_transactions` WHERE """ + where + """ AND `status` = 'completed'
             GROUP BY h ORDER BY h""", params):
            s['by_hour'][int(r['h'])] = {'count': to_int(r['cnt']), 'total': to_int(r['total'])}

        # この日に取り消した「前日以前の会計」（返金はこの日のレジから行うため、現金分は理論残高から差し引く）
        rwhere = ("`tenant_id` = ? AND `status` = 'voided' AND `voided_at` >= ? "
                  "AND `voided_at` < DATE_ADD(?, INTERVAL 1 DAY) AND `created_at` < ?")
        rparams = [int(tenant_id), date + ' 00:00:00', date, date + ' 00:00:00']
        if branch_id is not None:
            rwhere += " AND `branch_id` = ?"
            rparams.append(int(branch_id))
        if register_no is not None:
            rwhere += " AND `register_no` = ?"
            rparams.append(int(register_no))
        rf = self.db.query_one(
            """SELECT COUNT(*) AS cnt, COALESCE(SUM(`total`), 0) AS total,
                    COALESCE(SUM(CASE WHEN `payment_method` = 'cash' THEN `total` ELSE 0 END), 0) AS cash
             FROM `pos_transactions` WHERE """ + rwhere, rparams) or {}
        s['refund_prev_count'] = to_int(rf.get('cnt'))
        s['refund_prev_total'] = to_int(rf.get('total'))
        s['refund_prev_cash'] = to_int(rf.get('cash'))

        # 台帳画面から直接登録された販売記録（POS 以外・参考表示）
        try:
            o = self.db.query_one(
                """SELECT COUNT(*) AS cnt, COALESCE(SUM(`quantity`), 0) AS qty, COALESCE(SUM(`sale_amount`), 0) AS total
                 FROM `sales`
                 WHERE `tenant_id` = ? AND `transaction_id` IS NULL
                   AND `sold_at` >= ? AND `sold_at` < DATE_ADD(?, INTERVAL 1 DAY)""",
                (int(tenant_id), date + ' 00:00:00', date)) or {}
            s['other_sales'] = {'count': to_int(o.get('cnt')), 'qty': to_int(o.get('qty')), 'total': to_int(o.get('total'))}
        except Exception:
            s['other_sales'] = {'count': 0, 'qty': 0, 'total': 0}
        return s
