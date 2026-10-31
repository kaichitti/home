"""
レジ精算（日計・現金過不足）の記録

精算のたびに1行追加する（やり直した場合も履歴として残し、最新を正とする）。
"""
import json

from ..util import php_json_encode
from .base import BaseModel

DENOMINATIONS = (10000, 5000, 2000, 1000, 500, 100, 50, 10, 5, 1)  # 金種（円）


def _decode(row):
    for key in ('denominations', 'summary'):
        try:
            v = json.loads(row.get(key) or '')
        except ValueError:
            v = None
        # PHP版で保存した JSON は、連番のキーだけの場合に配列（list）になっている
        if isinstance(v, list):
            v = {i: x for i, x in enumerate(v)}
        row[key] = v if isinstance(v, dict) else {}
    s = row['summary']
    for key in ('by_hour', 'by_method'):
        if isinstance(s.get(key), list):
            s[key] = {i: x for i, x in enumerate(s[key])}
    return row


class PosClosing(BaseModel):
    table = 'pos_closings'

    def create(self, d):
        return self.db.insert(
            """INSERT INTO `pos_closings`
                (`tenant_id`, `branch_id`, `register_no`, `biz_date`, `tx_count`, `sales_total`, `cash_sales`, `opening_float`,
                 `expected_cash`, `counted_cash`, `difference`, `denominations`, `summary`, `note`,
                 `closed_by`, `closed_by_name`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (d['tenant_id'], d['branch_id'], d.get('register_no'), d['biz_date'], d['tx_count'], d['sales_total'],
             d['cash_sales'], d['opening_float'], d['expected_cash'], d['counted_cash'], d['difference'],
             php_json_encode(d['denominations']), php_json_encode(d['summary']),
             None if d['note'] == '' else d['note'], d['closed_by'], d['closed_by_name']))

    def find_by_id(self, closing_id, tenant_id):
        row = self.db.query_one(
            """SELECT c.*, b.name AS branch_name FROM `pos_closings` c
             LEFT JOIN `branches` b ON b.id = c.branch_id
             WHERE c.`id` = ? AND c.`tenant_id` = ?""", (int(closing_id), int(tenant_id)))
        return _decode(row) if row else None

    def find_by_date(self, tenant_id, date):
        """指定日の精算履歴（新しい順）"""
        return [_decode(r) for r in self.db.query(
            """SELECT c.*, b.name AS branch_name FROM `pos_closings` c
             LEFT JOIN `branches` b ON b.id = c.branch_id
             WHERE c.`tenant_id` = ? AND c.`biz_date` = ?
             ORDER BY c.`created_at` DESC, c.`id` DESC""", (int(tenant_id), date))]
