"""重複検知アラート"""
from .base import BaseModel


class Alert(BaseModel):
    table = 'alerts'

    def find_all(self, tenant_id, status=None, limit=None, offset=0):
        """アラート一覧（画面表示用の列つき）"""
        where = ['a.tenant_id = ?']
        params = [int(tenant_id)]
        if status is not None:
            where.append('a.status = ?')
            params.append(status)
        sql = """SELECT
                    a.*,
                    l1.id              AS record_a_id,
                    l1.item_name       AS record_a_item_name,
                    l1.transaction_amount AS record_a_price,
                    l1.created_at      AS record_a_created_at,
                    u1.display_name    AS record_a_created_by,
                    l2.id              AS record_b_id,
                    l2.item_name       AS record_b_item_name,
                    l2.transaction_amount AS record_b_price,
                    l2.created_at      AS record_b_created_at,
                    u2.display_name    AS record_b_created_by,
                    uc.display_name    AS confirmed_by_name
                FROM `alerts` a
                LEFT JOIN `ledgers` l1 ON l1.id = a.ledger_id_1
                LEFT JOIN `ledgers` l2 ON l2.id = a.ledger_id_2
                LEFT JOIN `users`   u1 ON u1.id = l1.registered_by
                LEFT JOIN `users`   u2 ON u2.id = l2.registered_by
                LEFT JOIN `users`   uc ON uc.id = a.confirmed_by
                WHERE """ + ' AND '.join(where) + """
                ORDER BY a.created_at DESC"""
        if limit is not None:
            sql += ' LIMIT %d OFFSET %d' % (int(limit), int(offset))
        return self.db.query(sql, params)

    def count_all(self, tenant_id, status=None):
        where = ['tenant_id = ?']
        params = [int(tenant_id)]
        if status is not None:
            where.append('status = ?')
            params.append(status)
        return int(self.db.value('SELECT COUNT(*) FROM `alerts` WHERE ' + ' AND '.join(where), params) or 0)

    def count_unconfirmed(self, tenant_id):
        """未確認アラートの件数（ダッシュボード・サイドバーのバッジ）"""
        return int(self.db.value("SELECT COUNT(*) FROM `alerts` WHERE `tenant_id` = ? AND `status` = 'unconfirmed'",
                                 (int(tenant_id),)) or 0)

    def create_if_not_exists(self, tenant_id, ledger_id_1, ledger_id_2):
        """同じ組合せが既にあれば作らず 0 を返す（小さい方の ID を ledger_id_1 にそろえる）"""
        a, b = int(ledger_id_1), int(ledger_id_2)
        if a > b:
            a, b = b, a
        exists = self.db.value(
            """SELECT `id` FROM `alerts`
             WHERE `tenant_id` = ? AND `ledger_id_1` = ? AND `ledger_id_2` = ? LIMIT 1""",
            (int(tenant_id), a, b))
        if exists is not None:
            return 0
        return self.db.insert("INSERT INTO `alerts` (`tenant_id`, `ledger_id_1`, `ledger_id_2`) VALUES (?, ?, ?)",
                              (int(tenant_id), a, b))

    def confirm(self, alert_id, tenant_id, confirmed_by):
        """確認済みにする（実際に更新できた場合のみ True）"""
        return self.db.execute(
            """UPDATE `alerts`
             SET `status` = 'confirmed', `confirmed_by` = ?, `confirmed_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ? AND `status` = 'unconfirmed'""",
            (int(confirmed_by), int(alert_id), int(tenant_id))) > 0

    def detect_duplicates(self, tenant_id, new_ledger_id):
        """
        新しく登録した台帳と重複する記録を探し、アラートを作る。重複の条件（すべて一致）:
          1. 品目名が同じ  2. 取引金額が同じ
          3. 本人確認書類ファイルの保存日時が秒単位で同じ
        """
        new = self.db.query_one(
            """SELECT l.item_name, l.transaction_amount,
                    DATE_FORMAT(MIN(lf.created_at), '%Y-%m-%d %H:%i:%s') AS file_created_sec
             FROM `ledgers` l
             LEFT JOIN `ledger_files` lf
               ON lf.ledger_id = l.id
              AND lf.file_type = 'id_document'
             WHERE l.id = ? AND l.tenant_id = ? AND l.deleted_at IS NULL
             GROUP BY l.id, l.item_name, l.transaction_amount""", (int(new_ledger_id), int(tenant_id)))
        if new is None or new['file_created_sec'] is None:
            return
        rows = self.db.query(
            """SELECT l.id
             FROM `ledgers` l
             INNER JOIN `ledger_files` lf
               ON lf.ledger_id = l.id
              AND lf.file_type = 'id_document'
             WHERE l.tenant_id = ?
               AND l.id != ?
               AND l.deleted_at IS NULL
               AND l.item_name = ?
               AND l.transaction_amount = ?
               AND DATE_FORMAT(lf.created_at, '%Y-%m-%d %H:%i:%s') = ?
             GROUP BY l.id""",
            (int(tenant_id), int(new_ledger_id), new['item_name'], new['transaction_amount'],
             new['file_created_sec']))
        for row in rows:
            self.create_if_not_exists(tenant_id, new_ledger_id, int(row['id']))
