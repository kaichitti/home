"""集計レポート（管理者のみ）: 仕入（台帳）と売上（販売記録）の推移を日/週/月/年で表示する"""
import datetime

from ..core.controller import BaseController
from ..models.sale import Sale
from ..util import add_months, parse_date, to_int, today_str, trim

GRANULARITIES = {'day': '日', 'week': '週', 'month': '月', 'year': '年'}


def _normalize_date(value):
    """YYYY-MM-DD 形式の実在する日付ならそのまま、それ以外は空文字"""
    value = trim(value)
    return value if parse_date(value) is not None else ''


class ReportController(BaseController):
    def index(self):
        self.auth.require_admin_role()
        tenant_id = self.auth.tenant_id()
        gran = self.request.get('granularity', 'day')
        if not isinstance(gran, str) or gran not in GRANULARITIES:
            gran = 'day'
        to = self.request.get('to', '')
        frm = self.request.get('from', '')
        to = _normalize_date(to) if isinstance(to, str) else ''
        frm = _normalize_date(frm) if isinstance(frm, str) else ''
        if to == '':
            to = today_str()
        if frm == '':
            # 期間の指定が無ければ、単位に応じた既定の期間
            d = parse_date(to)
            if gran == 'day':
                start = d - datetime.timedelta(days=30)
            elif gran == 'week':
                start = d - datetime.timedelta(weeks=12)
            elif gran == 'month':
                start = add_months(d, -12)
            else:
                start = add_months(d, -60)
            frm = start.strftime('%Y-%m-%d')
        if frm > to:
            frm, to = to, frm

        model = Sale(self.db)
        sales = model.aggregate(tenant_id, frm, to, gran)
        purchases = model.aggregate_purchases(tenant_id, frm, to, gran)
        # 期間ラベルで1つの表にまとめる
        periods = {}
        for r in purchases:
            periods.setdefault(str(r['period']), {})['purchase'] = r
        for r in sales:
            periods.setdefault(str(r['period']), {})['sale'] = r
        periods = dict(sorted(periods.items()))
        total_purchase = sum(to_int((row.get('purchase') or {}).get('total')) for row in periods.values())
        total_sale = sum(to_int((row.get('sale') or {}).get('total')) for row in periods.values())
        self.render('report/index', {
            'periods': periods, 'granularity': gran, 'granularities': GRANULARITIES,
            'from': frm, 'to': to, 'totalPurchase': total_purchase, 'totalSale': total_sale,
        })
