"""
テナントのユーザー（ログイン・管理）

すべての操作で tenant_id を条件に入れ、他のテナントのユーザーに触れないようにする。
"""
from ..helpers import passwords
from .base import BaseModel


class User(BaseModel):
    table = 'users'

    def get_by_tenant(self, tenant_id):
        """テナント内のユーザー一覧（所属拠点名つき）"""
        return self.db.query(
            """SELECT u.`id`, u.`branch_id`, u.`display_name`, u.`email`, u.`role`, u.`is_owner`, u.`is_active`,
                    u.`must_change_password`, u.`failed_login_attempts`, u.`locked_until`,
                    (u.`locked_until` IS NOT NULL AND u.`locked_until` > NOW()) AS `is_locked`,
                    u.`last_login_at`, u.`created_at`, b.`name` AS `branch_name`
             FROM `users` u
             LEFT JOIN `branches` b ON b.`id` = u.`branch_id` AND b.`tenant_id` = u.`tenant_id`
             WHERE u.`tenant_id` = ? ORDER BY u.`is_active` DESC, u.`display_name` ASC""", (int(tenant_id),))

    def find_by_email(self, tenant_id, email):
        """ログイン用（無効・ロック中のユーザーも返し、呼び出し側で判定する）"""
        return self.db.query_one("SELECT * FROM `users` WHERE `tenant_id` = ? AND `email` = ?",
                                 (int(tenant_id), email))

    def find_by_id(self, user_id, tenant_id):
        return self.db.query_one("SELECT * FROM `users` WHERE `id` = ? AND `tenant_id` = ?",
                                 (int(user_id), int(tenant_id)))

    def create(self, data):
        return self.db.insert(
            """INSERT INTO `users`
             (`tenant_id`, `branch_id`, `display_name`, `email`, `password_hash`, `role`, `is_active`, `must_change_password`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (data['tenant_id'], data.get('branch_id'), data['display_name'], data['email'],
             passwords.hash_password(data['password']), data.get('role') or 'user',
             1 if data.get('is_active') is None else data['is_active'],
             1 if data.get('must_change_password') is None else data['must_change_password']))

    def update(self, user_id, tenant_id, data):
        # is_active が None（未指定）なら現在の値を変えない（別の管理者の無効化を古い値で書き戻さない）
        self.db.execute(
            """UPDATE `users`
             SET `display_name` = ?, `email` = ?, `role` = ?, `is_active` = COALESCE(?, `is_active`),
                 `branch_id` = ?, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?""",
            (data['display_name'], data['email'], data['role'], data.get('is_active'), data.get('branch_id'),
             int(user_id), int(tenant_id)))
        return True

    def deactivate(self, user_id, tenant_id):
        self.db.execute("UPDATE `users` SET `is_active` = 0, `updated_at` = NOW() WHERE `id` = ? AND `tenant_id` = ?",
                        (int(user_id), int(tenant_id)))
        return True

    def activate(self, user_id, tenant_id):
        """再有効化（ロック状態も初期化する）"""
        self.db.execute(
            """UPDATE `users` SET `is_active` = 1, `failed_login_attempts` = 0, `locked_until` = NULL,
                    `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?""", (int(user_id), int(tenant_id)))
        return True

    def deactivate_all_by_tenant(self, tenant_id):
        self.db.execute("UPDATE `users` SET `is_active` = 0, `updated_at` = NOW() WHERE `tenant_id` = ?",
                        (int(tenant_id),))
        return True

    def change_email(self, user_id, tenant_id, new_email):
        self.db.execute("UPDATE `users` SET `email` = ?, `updated_at` = NOW() WHERE `id` = ? AND `tenant_id` = ?",
                        (new_email, int(user_id), int(tenant_id)))
        return True

    def change_password(self, user_id, tenant_id, new_password):
        """パスワード変更（変更強制フラグ・ロックも解除）"""
        self.db.execute(
            """UPDATE `users`
             SET `password_hash` = ?, `must_change_password` = 0, `failed_login_attempts` = 0,
                 `locked_until` = NULL, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?""",
            (passwords.hash_password(new_password), int(user_id), int(tenant_id)))
        return True

    def reset_password(self, user_id, tenant_id, temp_password):
        """管理者による再設定（仮パスワード。次回ログイン時に変更を求める。ロックも解除）"""
        self.db.execute(
            """UPDATE `users`
             SET `password_hash` = ?, `must_change_password` = 1, `failed_login_attempts` = 0,
                 `locked_until` = NULL, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?""",
            (passwords.hash_password(temp_password), int(user_id), int(tenant_id)))
        return True

    def unlock(self, user_id, tenant_id):
        self.db.execute(
            """UPDATE `users` SET `failed_login_attempts` = 0, `locked_until` = NULL, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?""", (int(user_id), int(tenant_id)))
        return True

    def reset_failed_attempts(self, user_id):
        self.db.execute("UPDATE `users` SET `failed_login_attempts` = 0, `locked_until` = NULL WHERE `id` = ?",
                        (int(user_id),))

    def expire_lock(self, user_id):
        """期限切れのロックを解除する（期限の判定は DB の時刻で行う）"""
        self.db.execute(
            """UPDATE `users` SET `failed_login_attempts` = 0, `locked_until` = NULL
             WHERE `id` = ? AND `locked_until` IS NOT NULL AND `locked_until` <= NOW()""", (int(user_id),))

    def reserve_attempt(self, user_id):
        """
        パスワード照合の「前」に試行1回分を予約する（1文の UPDATE で判定と加算を同時に行う）。
        ロック中でなければ失敗回数を1増やし（5回目でロック）True。ロック中なら False。
        """
        return self.db.execute(
            """UPDATE `users`
             SET `locked_until` = CASE
                     WHEN `failed_login_attempts` + 1 >= 5 THEN DATE_ADD(NOW(), INTERVAL 30 MINUTE)
                     ELSE NULL
                 END,
                 `failed_login_attempts` = LEAST(`failed_login_attempts` + 1, 255)
             WHERE `id` = ? AND `locked_until` IS NULL""", (int(user_id),)) > 0

    def update_password_hash(self, user_id, new_hash, old_hash=None):
        """ハッシュを差し替える（ログイン時の再ハッシュ。旧ハッシュが一致する場合のみ）"""
        if old_hash is None:
            self.db.execute("UPDATE `users` SET `password_hash` = ? WHERE `id` = ?", (new_hash, int(user_id)))
            return
        self.db.execute("UPDATE `users` SET `password_hash` = ? WHERE `id` = ? AND `password_hash` = ?",
                        (new_hash, int(user_id), old_hash))

    def require_password_change(self, user_id):
        self.db.execute("UPDATE `users` SET `must_change_password` = 1 WHERE `id` = ?", (int(user_id),))

    def is_locked(self, user_id):
        return int(self.db.value(
            "SELECT (`locked_until` IS NOT NULL AND `locked_until` > NOW()) FROM `users` WHERE `id` = ?",
            (int(user_id),)) or 0) == 1

    def update_last_login(self, user_id):
        self.db.execute("UPDATE `users` SET `last_login_at` = NOW() WHERE `id` = ?", (int(user_id),))
