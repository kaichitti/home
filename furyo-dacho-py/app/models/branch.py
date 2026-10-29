"""拠点（すべての操作で tenant_id を条件に入れる）"""
from ..db import DBError, ER_ROW_IS_REFERENCED
from ..util import is_empty
from .base import BaseModel


class BranchError(RuntimeError):
    """利用者に表示するメッセージ付きのエラー"""


class Branch(BaseModel):
    table = 'branches'

    def find_all_by_tenant(self, tenant_id):
        return self.db.query("SELECT * FROM `branches` WHERE `tenant_id` = ? ORDER BY `name` ASC", (int(tenant_id),))

    def find_by_id(self, branch_id, tenant_id):
        return self.db.query_one("SELECT * FROM `branches` WHERE `id` = ? AND `tenant_id` = ?",
                                 (int(branch_id), int(tenant_id)))

    def login_code_exists(self, tenant_id, code, exclude_id=None):
        """
        拠点ログインコードが使用済みか（全テナント横断で判定する）。
        ログイン時は全テナント横断で検索し、テナントコードが優先されるため、
        どこかのテナントコードと同じ値も使用不可。
        """
        sql = "SELECT COUNT(*) FROM `branches` WHERE `login_code` = ?"
        params = [code]
        if exclude_id is not None:
            sql += " AND `id` != ?"
            params.append(int(exclude_id))
        if int(self.db.value(sql, params) or 0) > 0:
            return True
        return int(self.db.value("SELECT COUNT(*) FROM `tenants` WHERE `code` = ?", (code,)) or 0) > 0

    def create(self, tenant_id, name, address=None, login_code=None):
        return self.db.insert("INSERT INTO `branches` (`tenant_id`, `name`, `address`, `login_code`) VALUES (?, ?, ?, ?)",
                              (int(tenant_id), name, address, None if is_empty(login_code) else login_code))

    def update(self, branch_id, tenant_id, name, address=None, login_code=None):
        self.db.execute(
            """UPDATE `branches` SET `name` = ?, `address` = ?, `login_code` = ?, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?""",
            (name, address, None if is_empty(login_code) else login_code, int(branch_id), int(tenant_id)))
        return True

    def delete(self, branch_id, tenant_id):
        """削除する（所属ユーザー・台帳がある場合は BranchError）"""
        row = self.db.query_one(
            """SELECT SUM(`is_active` = 1) AS active_cnt, SUM(`is_active` <> 1) AS inactive_cnt
             FROM `users` WHERE `branch_id` = ? AND `tenant_id` = ?""", (int(branch_id), int(tenant_id))) or {}
        if int(row.get('active_cnt') or 0) > 0:
            raise BranchError('この拠点には所属ユーザーが存在するため削除できません。先にユーザー管理で所属拠点を変更してください。')
        if int(row.get('inactive_cnt') or 0) > 0:
            raise BranchError('この拠点には無効化したユーザーが所属しているため削除できません。ユーザー管理でそのユーザーの所属拠点を変更してください。')
        # 削除済みの台帳も法定帳簿の記録として残るため数える
        row2 = self.db.query_one(
            """SELECT SUM(`deleted_at` IS NULL) AS live_cnt, COUNT(*) AS all_cnt
             FROM `ledgers` WHERE `branch_id` = ? AND `tenant_id` = ?""", (int(branch_id), int(tenant_id))) or {}
        if int(row2.get('live_cnt') or 0) > 0:
            raise BranchError('この拠点には台帳レコードが存在するため削除できません。')
        if int(row2.get('all_cnt') or 0) > 0:
            raise BranchError('この拠点には削除済みの台帳レコード（記録として保存されています）が紐づいているため削除できません。名称を変更してご利用ください。')
        try:
            self.db.execute("DELETE FROM `branches` WHERE `id` = ? AND `tenant_id` = ?", (int(branch_id), int(tenant_id)))
        except DBError as e:
            if e.code == ER_ROW_IS_REFERENCED:
                raise BranchError('この拠点は他のデータから参照されているため削除できません。') from None
            raise
        return True
