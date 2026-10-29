"""監査ログ（追記専用。変更・削除の処理は用意しない）"""
from ..util import php_json_encode
from .base import BaseModel


class AuditLog(BaseModel):
    table = 'audit_logs'

    def log(self, tenant_id, user_id, display_name, branch_name, action_type, target_id,
            before_value, after_value, ip_address):
        """
        監査ログを1件記録する
          action_type: login / create / edit / delete / export / alert_action など
          before_value / after_value: 変更前後の値（dict。JSON で保存）
        """
        return self.db.insert(
            """INSERT INTO `audit_logs`
             (`tenant_id`, `user_id`, `user_display_name`, `branch_name`,
              `action_type`, `target_id`, `before_value`, `after_value`, `ip_address`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (None if tenant_id is None else int(tenant_id),
             None if user_id is None else int(user_id),
             str(display_name),
             branch_name,
             action_type,
             None if target_id is None else int(target_id),
             php_json_encode(before_value) if before_value is not None else None,
             php_json_encode(after_value) if after_value is not None else None,
             ip_address))

    def find_by_tenant(self, tenant_id, limit=100, offset=0):
        return self.db.query(
            """SELECT * FROM `audit_logs` WHERE `tenant_id` = ?
             ORDER BY `created_at` DESC LIMIT ? OFFSET ?""", (int(tenant_id), int(limit), int(offset)))

    def find_all(self, limit=100, offset=0):
        """全テナントの監査ログ（システム管理者用）"""
        return self.db.query(
            """SELECT `al`.*, `t`.`name` AS `tenant_name`
             FROM `audit_logs` AS `al`
             LEFT JOIN `tenants` AS `t` ON `al`.`tenant_id` = `t`.`id`
             ORDER BY `al`.`created_at` DESC
             LIMIT ? OFFSET ?""", (int(limit), int(offset)))

    def get_by_tenant(self, tenant_id, filters=None, per_page=100, page=1):
        """テナントの監査ログ（絞り込みつき）"""
        where, params = build_filter_where(tenant_id, filters or {})
        offset = (int(page) - 1) * int(per_page)
        return self.db.query(
            "SELECT * FROM `audit_logs` WHERE " + where + " ORDER BY `created_at` DESC LIMIT ? OFFSET ?",
            params + [int(per_page), offset])

    def count_by_tenant(self, tenant_id, filters=None):
        where, params = build_filter_where(tenant_id, filters or {})
        return int(self.db.value("SELECT COUNT(*) FROM `audit_logs` WHERE " + where, params) or 0)


def build_filter_where(tenant_id, f):
    from ..util import is_empty, to_int
    where = ['tenant_id = ?']
    params = [int(tenant_id)]
    if not is_empty(f.get('action_type')):
        where.append('action_type = ?')
        params.append(f['action_type'])
    if not is_empty(f.get('user_id')):
        where.append('user_id = ?')
        params.append(to_int(f['user_id']))
    if not is_empty(f.get('date_from')):
        where.append('created_at >= ?')
        params.append(str(f['date_from']) + ' 00:00:00')
    if not is_empty(f.get('date_to')):
        where.append('created_at <= ?')
        params.append(str(f['date_to']) + ' 23:59:59')
    return ' AND '.join(where), params
