"""
認証・認可（PHP版 src/Core/Auth.php と同じ動き）

- テナントユーザー（role: admin / user）と、システム管理者（別URL・別Cookie）のログイン
- ログイン失敗ロック（5回で30分。ただし過去にログイン成功したIPからは照合する＝締め出し対策）
- IP単位・アカウント×IP単位のログイン試行制限（LoginThrottle）
- 15分操作が無ければタイムアウト
- 存在しないアカウントへの試行でも同じだけ時間をかける（応答時間からアカウントの有無を推測させない）
"""
import re
import time

from ..helpers import passwords
from ..helpers.login_throttle import LoginThrottle, account_key
from .response import ResponseDone, error_page, redirect

DEFAULT_PASSWORD = passwords.DEFAULT_PASSWORD
_ADMIN_NAME_RE = re.compile(r'[A-Za-z0-9._-]{1,64}')


class Auth:
    def __init__(self, ctx):
        self.ctx = ctx
        self.session = ctx.session
        self.timeout = ctx.cfg['session_timeout']
        self._revalidated = False

    @property
    def db(self):
        return self.ctx.db

    # ------------------------------------------------------------------
    # セッションの有効期限
    # ------------------------------------------------------------------
    def _session_valid(self):
        last = self.session.get('_last_activity')
        if last is None:
            return False
        try:
            last = int(last)
        except (TypeError, ValueError):
            last = 0
        if int(time.time()) - last > self.timeout:
            self.session.destroy()
            return False
        self.session.set('_last_activity', int(time.time()))
        return True

    def _regenerate(self):
        self.session.restart_if_destroyed()
        self.session.regenerate()
        self.session.set('_last_activity', int(time.time()))

    # ------------------------------------------------------------------
    # テナントユーザー
    # ------------------------------------------------------------------
    def _find_tenant_by_branch_code(self, code):
        try:
            # 旧バージョンではテナント間で同じコードを登録できたため、複数該当する場合は曖昧としてログイン不可
            rows = self.db.query("SELECT * FROM `branches` WHERE `login_code` = ? LIMIT 2", (code,))
            return rows[0] if len(rows) == 1 else None
        except Exception:
            return None  # login_code 列が無い（マイグレーション未実行）環境

    def login(self, tenant_code, email, password):
        from ..models.audit_log import AuditLog
        from ..models.tenant import Tenant
        from ..models.user import User

        db = self.db
        tenants = Tenant(db)
        users = User(db)
        throttle = LoginThrottle(db)
        ip = self.ctx.request.ip()

        # まずテナントコードで特定。見つからなければ拠点ログインコードで特定する
        tenant = tenants.find_by_code(tenant_code)
        branch_scope = None
        if tenant is None:
            branch = self._find_tenant_by_branch_code(tenant_code)
            if branch is not None:
                tenant = tenants.find_by_id(int(branch['tenant_id']))
                branch_scope = int(branch['id'])

        user = users.find_by_email(int(tenant['id']), email) \
            if tenant is not None and tenant['status'] == 'active' else None

        # 試行制限のアカウント識別子は、特定できたユーザーのIDで作る（表記ゆれで制限を回避させない）
        key = account_key('tenant', 'uid:%d' % int(user['id'])) if user is not None \
            else account_key('tenant-input', tenant_code, email)

        # 照合の前に試行を予約する（並行リクエストでも上限を超えて照合させない）
        reservation = throttle.reserve(key, ip)
        if reservation is None:
            passwords.dummy_verify(password)
            return False

        def fail():
            passwords.dummy_verify(password)
            return False

        if user is None:
            return fail()
        # 拠点コードでログインした場合、その拠点所属のユーザーのみ許可（管理者はどの拠点コードからでも可）
        if branch_scope is not None and user['role'] != 'admin' and int(user.get('branch_id') or 0) != branch_scope:
            return fail()
        if not int(user['is_active']):
            return fail()

        # アカウントロック（5回失敗で30分）。信頼済みIPからはロック中でも照合する（締め出し対策）
        user_id = int(user['id'])
        users.expire_lock(user_id)
        via_trusted_during_lock = False
        if not users.reserve_attempt(user_id):
            if not throttle.is_trusted_ip(key, ip):
                throttle.mark_refused(reservation)
                return fail()
            via_trusted_during_lock = True

        if not passwords.verify(password, user['password_hash']):
            return False  # 予約した行がそのまま失敗記録になる

        if not via_trusted_during_lock:
            users.reset_failed_attempts(user_id)
        users.update_last_login(user_id)
        throttle.record_success(key, ip)

        # ハッシュの方式・コストが今の既定と違えば保存し直す（照合中に変更された場合は上書きしない）
        if passwords.needs_rehash(user['password_hash']):
            try:
                users.update_password_hash(user_id, passwords.hash_password(password), user['password_hash'])
            except Exception:
                pass

        # 公開されている初期パスワードのままなら、変更するまで他の画面を使わせない
        must_change = int(user['must_change_password'] or 0) == 1 or passwords.equals(DEFAULT_PASSWORD, password)
        if must_change and int(user['must_change_password'] or 0) != 1:
            try:
                users.require_password_change(user_id)
            except Exception:
                pass

        # セッションIDを作り直す（セッション固定化攻撃の対策）
        self._regenerate()
        s = self.session
        s.set('tenant_id', int(tenant['id']))
        s.set('user_id', user_id)
        s.set('role', user['role'])
        s.set('display_name', user['display_name'])
        s.set('branch_id', int(user['branch_id']) if user.get('branch_id') is not None else None)
        s.set('must_change_password', 1 if must_change else 0)

        AuditLog(db).log(int(tenant['id']), user_id, user['display_name'], None, 'login',
                         None, None, None, ip)
        return True

    def logout(self):
        self.session.destroy()

    def is_logged_in(self):
        """ログイン済みか（タイムアウト判定と、1リクエストに1回のアカウント状態の再確認を含む）"""
        if not (self._session_valid() and self.session.get('user_id') is not None):
            return False
        if not self._revalidated:
            self._revalidated = True
            try:
                row = self.db.query_one(
                    """SELECT u.`is_active`, u.`role`, t.`status` AS tenant_status
                     FROM `users` u JOIN `tenants` t ON t.`id` = u.`tenant_id`
                     WHERE u.`id` = ? AND u.`tenant_id` = ?""",
                    (int(self.session.get('user_id')), int(self.session.get('tenant_id') or 0)))
                if row is None or int(row['is_active']) != 1 or row.get('tenant_status') != 'active':
                    # 削除・無効化されたアカウント、停止・削除されたテナント → セッションを破棄
                    self.session.destroy()
                    return False
                if row.get('role') is not None:
                    self.session.set('role', row['role'])
            except Exception:
                pass  # DB の一時障害時は可用性を優先する
        return True

    def require_login(self):
        if not self.is_logged_in():
            raise ResponseDone(redirect('/index.cgi?page=login'))

    def require_admin_role(self):
        self.require_login()
        if self.role() != 'admin':
            raise ResponseDone(error_page(403, 'アクセスできません',
                                          'この画面は管理者のみ利用できます。必要な場合は管理者に依頼してください。'))

    def tenant_id(self):
        try:
            return int(self.session.get('tenant_id') or 0)
        except (TypeError, ValueError):
            return 0

    def user_id(self):
        try:
            return int(self.session.get('user_id') or 0)
        except (TypeError, ValueError):
            return 0

    def role(self):
        r = self.session.get('role', '')
        return '' if r is None else str(r)

    def is_admin(self):
        return self.is_logged_in() and self.role() == 'admin'

    def must_change_password(self):
        return bool(self.session.get('must_change_password', False))

    def set_must_change_password(self, value):
        self.session.set('must_change_password', 1 if value else 0)

    def user(self):
        if not self.is_logged_in():
            return None
        return {
            'id': self.user_id(),
            'tenant_id': self.tenant_id(),
            'branch_id': self.session.get('branch_id'),
            'display_name': self.session.get('display_name'),
            'role': self.role(),
        }

    def verify_current_password(self, plain):
        """ログイン中のユーザーのパスワードを照合する（台帳削除時などの再入力確認）"""
        if not self.is_logged_in():
            return False
        row = self.db.query_one(
            "SELECT `password_hash` FROM `users` WHERE `id` = ? AND `tenant_id` = ? AND `is_active` = 1",
            (self.user_id(), self.tenant_id()))
        if row is None:
            return False
        return passwords.verify(plain, row['password_hash'])

    # ------------------------------------------------------------------
    # システム管理者
    # ------------------------------------------------------------------
    def admin_login(self, username, password):
        db = self.db
        throttle = LoginThrottle(db)
        ip = self.ctx.request.ip()
        username = username if isinstance(username, str) else ''

        # ユーザー名は半角英数字と . _ - のみ（DB の照合順序による表記ゆれの同一視を入口で弾く）
        admin = None
        if _ADMIN_NAME_RE.fullmatch(username):
            admin = db.query_one("SELECT * FROM `system_admins` WHERE `username` = ?", (username,))

        key = account_key('admin', 'id:%d' % int(admin['id'])) if admin is not None \
            else account_key('admin-input', username)

        reservation = throttle.reserve(key, ip)
        if reservation is None:
            passwords.dummy_verify(password)
            return False

        # アカウント単位のロック（30分間に5回失敗。今回の予約は数えない）。信頼済みIPは対象外
        if throttle.is_account_locked(key, reservation) and not throttle.is_trusted_ip(key, ip):
            throttle.mark_refused(reservation)
            passwords.dummy_verify(password)
            return False

        if admin is None:
            passwords.dummy_verify(password)
            return False

        if not passwords.verify(password, admin['password_hash']):
            return False

        throttle.record_success(key, ip)

        if passwords.needs_rehash(admin['password_hash']):
            try:
                db.execute("UPDATE `system_admins` SET `password_hash` = ? WHERE `id` = ? AND `password_hash` = ?",
                           (passwords.hash_password(password), admin['id'], admin['password_hash']))
            except Exception:
                pass

        db.execute("UPDATE `system_admins` SET `last_login_at` = NOW() WHERE `id` = ?", (admin['id'],))

        self._regenerate()
        self.session.set('admin_id', int(admin['id']))
        self.session.set('admin_name', admin['username'])
        # 公開されている初期パスワードのままなら、変更するまで他の管理画面を使えないようにする
        self.session.set('admin_must_change_password', 1 if passwords.equals(DEFAULT_PASSWORD, password) else 0)
        return True

    def admin_must_change_password(self):
        return bool(self.session.get('admin_must_change_password', False))

    def set_admin_must_change_password(self, value):
        self.session.set('admin_must_change_password', 1 if value else 0)

    def admin_logout(self):
        self.session.destroy()

    def is_admin_logged_in(self):
        return self._session_valid() and self.session.get('admin_id') is not None

    def require_system_admin(self):
        if not self.is_admin_logged_in():
            raise ResponseDone(redirect('/admin/index.cgi?page=login'))

    def admin_user(self):
        if not self.is_admin_logged_in():
            return None
        return {'id': self.session.get('admin_id'), 'username': self.session.get('admin_name')}
