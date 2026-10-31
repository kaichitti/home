"""監査ログ（テナント管理者のみ）"""
import math

from ..core.controller import BaseController
from ..models.audit_log import AuditLog


class AuditController(BaseController):
    def index(self):
        """監査ログ一覧（1ページ50件）"""
        self.auth.require_admin_role()
        tenant_id = self.auth.tenant_id()
        per_page = 50
        page = max(1, self.get_int('p') if self.request.get('p') is not None else 1)

        def g(key):
            # 絞り込み条件は文字列のみ受け付ける（配列が送られた場合は条件なし）
            v = self.request.get(key)
            return v if isinstance(v, str) and v != '' else None

        filters = {'action_type': g('action_type'), 'user_id': g('user_id'),
                   'date_from': g('date_from'), 'date_to': g('date_to')}
        model = AuditLog(self.db)
        total = model.count_by_tenant(tenant_id, filters)
        logs = model.get_by_tenant(tenant_id, filters, per_page, page)
        self.render('audit/index', {
            'logs': logs, 'filters': filters, 'page': page, 'perPage': per_page,
            'pagination': {'current_page': page, 'total_pages': int(math.ceil(total / per_page)),
                           'total': total, 'per_page': per_page},
        })
