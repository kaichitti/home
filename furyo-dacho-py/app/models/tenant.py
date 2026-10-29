"""テナント（事業者）"""
from .base import BaseModel


class Tenant(BaseModel):
    table = 'tenants'

    def find_all(self):
        return self.db.query("SELECT * FROM `tenants` WHERE `status` != 'deleted' ORDER BY `id` ASC")

    def get_active(self):
        return self.db.query("SELECT * FROM `tenants` WHERE `status` = 'active' ORDER BY `id` ASC")

    def find_by_id(self, tenant_id):
        return self.db.query_one("SELECT * FROM `tenants` WHERE `id` = ?", (int(tenant_id),))

    def find_by_code(self, code):
        """テナントコードで特定する（ログイン時）"""
        return self.db.query_one("SELECT * FROM `tenants` WHERE `code` = ?", (code,))

    def is_code_taken(self, code, exclude_id=None):
        if exclude_id is not None:
            n = self.db.value("SELECT COUNT(*) FROM `tenants` WHERE `code` = ? AND `id` != ?", (code, int(exclude_id)))
        else:
            n = self.db.value("SELECT COUNT(*) FROM `tenants` WHERE `code` = ?", (code,))
        return int(n or 0) > 0

    def create(self, data):
        return self.db.insert("INSERT INTO `tenants` (`code`, `name`, `type`, `status`) VALUES (?, ?, ?, ?)",
                              (data['code'], data['name'], data['type'], data.get('status') or 'active'))

    def update(self, tenant_id, data):
        self.db.execute(
            """UPDATE `tenants` SET `code` = ?, `name` = ?, `type` = ?, `status` = ?, `updated_at` = NOW()
               WHERE `id` = ?""",
            (data['code'], data['name'], data['type'], data['status'], int(tenant_id)))
        return True

    def suspend(self, tenant_id):
        self.db.execute("UPDATE `tenants` SET `status` = 'suspended', `updated_at` = NOW() WHERE `id` = ?",
                        (int(tenant_id),))
        return True

    def delete(self, tenant_id):
        """論理削除（status = deleted）。呼び出し元で全ユーザーを無効化すること"""
        self.db.execute("UPDATE `tenants` SET `status` = 'deleted', `updated_at` = NOW() WHERE `id` = ?",
                        (int(tenant_id),))
        return True

    def find_all_with_stats(self, include_deleted=False):
        """利用状況（ユーザー数・台帳件数・最終ログイン）付きの一覧"""
        where = '' if include_deleted else "WHERE t.`status` != 'deleted'"
        return self.db.query(
            """SELECT t.*,
                    COALESCE(u.user_count, 0)   AS user_count,
                    COALESCE(u.active_count, 0) AS active_user_count,
                    u.last_login_at,
                    COALESCE(l.ledger_count, 0) AS ledger_count
             FROM `tenants` t
             LEFT JOIN (
                 SELECT `tenant_id`, COUNT(*) AS user_count, SUM(`is_active` = 1) AS active_count,
                        MAX(`last_login_at`) AS last_login_at
                 FROM `users` GROUP BY `tenant_id`
             ) u ON u.`tenant_id` = t.`id`
             LEFT JOIN (
                 SELECT `tenant_id`, COUNT(*) AS ledger_count
                 FROM `ledgers` WHERE `deleted_at` IS NULL GROUP BY `tenant_id`
             ) l ON l.`tenant_id` = t.`id`
             """ + where + """
             ORDER BY t.`id` ASC""")

    def resume(self, tenant_id):
        """停止中のテナントを再開する（削除済みは対象外）"""
        return self.db.execute(
            "UPDATE `tenants` SET `status` = 'active', `updated_at` = NOW() WHERE `id` = ? AND `status` = 'suspended'",
            (int(tenant_id),)) > 0
