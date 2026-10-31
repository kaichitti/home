"""ダッシュボード"""
from ..core.controller import BaseController
from ..models import pos_schema
from ..models.alert import Alert
from ..models.ledger import Ledger
from ..models.pos_transaction import PosTransaction
from ..util import today_str


class DashboardController(BaseController):
    def index(self):
        """今月の台帳登録件数・未確認アラート・最近の登録5件・本日のPOS売上・承認待ち"""
        self.auth.require_login()
        tenant_id = self.auth.tenant_id()
        ledgers = Ledger(self.db)
        this_month = ledgers.count_this_month(tenant_id)
        alert_count = Alert(self.db).count_unconfirmed(tenant_id)
        recent = ledgers.get_recent(tenant_id, 5)
        fy = ledgers.get_fiscal_year(today_str())

        pos_today = None
        try:
            pos_schema.ensure(self.db)
            pos_today = PosTransaction(self.db).daily_summary(tenant_id, today_str(), None)
        except Exception:
            pos_today = None

        approval_count = 0
        if self.auth.is_admin():
            try:
                approval_count = int(self.db.value(
                    """SELECT COUNT(*) FROM `ledgers`
                     WHERE `tenant_id` = ? AND `approval_status` = 'pending' AND `deleted_at` IS NULL""",
                    (tenant_id,)) or 0)
            except Exception:
                approval_count = 0

        self.render('dashboard/index', {
            'pos_today': pos_today,
            'approval_count': approval_count,
            'monthly_count': this_month,
            'this_month_count': this_month,
            'alert_count': alert_count,
            'recent_records': recent,
            'total_records': ledgers.count_by_tenant(tenant_id),
            'this_year': ledgers.count_by_tenant(tenant_id, {'fiscal_year': fy}),
            'current_year': fy,
        })
