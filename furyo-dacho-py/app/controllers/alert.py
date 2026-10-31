"""重複検知アラート"""
import math

from ..core.controller import BaseController
from ..models.alert import Alert
from ..models.audit_log import AuditLog


class AlertController(BaseController):
    def index(self):
        self.auth.require_admin_role()
        tenant_id = self.auth.tenant_id()
        status = self.request.get('status')
        status = status if isinstance(status, str) and status in ('unconfirmed', 'confirmed') else None
        per_page = 50
        page = max(1, self.get_int('p') if self.request.get('p') is not None else 1)
        model = Alert(self.db)
        total = model.count_all(tenant_id, status)
        total_pages = max(1, int(math.ceil(total / per_page)))
        page = min(page, total_pages)
        alerts = model.find_all(tenant_id, status, per_page, (page - 1) * per_page)
        self.render('alert/index', {
            'alerts': alerts, 'status': status, 'isAdmin': True,
            'pagination': {'current_page': page, 'total_pages': total_pages, 'total': total},
        })

    def confirm(self):
        """確認済みにする（POST のみ）"""
        self.auth.require_admin_role()
        if not self.request.is_post():
            self.redirect('/index.cgi?page=alert')
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.auth.user_id()
        alert_id = self.get_int('id')
        if alert_id <= 0:
            self.redirect('/index.cgi?page=alert')
        if Alert(self.db).confirm(alert_id, tenant_id, user_id):
            AuditLog(self.db).log(tenant_id, user_id, self.user_name(), None, 'alert_action', alert_id, None,
                                  {'status': 'confirmed'}, self.request.ip())
            self.flash('success', 'アラートを確認済みにしました。')
        else:
            self.flash('error', 'アラートの確認処理に失敗しました（既に確認済みか、見つかりません）。')
        self.redirect('/index.cgi?page=alert')
