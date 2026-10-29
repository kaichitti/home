"""システム管理者のログイン・パスワード変更（テナント側とは別URL・別Cookie）"""
from ...core.controller import BaseController
from ...helpers import passwords
from ...models.audit_log import AuditLog
from ...util import is_empty, trim

# システム管理者パスワードの最小文字数（全テナントを管理できる最上位権限のため強めに設定）
ADMIN_PASSWORD_MIN_LENGTH = 12


class AdminAuthController(BaseController):
    def login(self):
        if self.auth.is_admin_logged_in():
            self.redirect('/admin/index.cgi?page=dashboard')
        if self.request.is_post():
            self._handle_login()
        self.render('admin/login', {'error': None}, 'admin')

    def logout(self):
        self.auth.admin_logout()
        self.redirect('/admin/index.cgi?page=login')

    def change_password(self):
        """パスワード変更。初期パスワードでログインした場合はこの画面へ強制的に案内する"""
        self.auth.require_system_admin()
        admin = self.auth.admin_user() or {}
        forced = self.auth.admin_must_change_password()

        def form(error, done=False):
            self.render('admin/password', {'error': error, 'forced': forced, 'done': done,
                                           'minLength': ADMIN_PASSWORD_MIN_LENGTH}, 'admin')

        if not self.request.is_post():
            form(None, self.request.get('done') == '1')
        self.verify_csrf()

        current = self.request.raw_post('current_password')
        new = self.request.raw_post('new_password')
        confirm = self.request.raw_post('confirm_password')
        if '\0' in new:
            form('パスワードに使用できない文字が含まれています。')
        row = self.db.query_one("SELECT `password_hash` FROM `system_admins` WHERE `id` = ?",
                                (int(admin.get('id') or 0),))
        if row is None or not passwords.verify(current, row['password_hash']):
            form('現在のパスワードが正しくありません。')
        if new != confirm:
            form('新しいパスワードと確認用パスワードが一致しません。')
        if len(new.encode('utf-8')) > 72:
            form('パスワードは72バイト（半角72文字）以内で入力してください。')
        if len(new) < ADMIN_PASSWORD_MIN_LENGTH or not passwords.is_alpha_numeric(new):
            form('パスワードは%d文字以上で、英字・数字をそれぞれ1文字以上含めてください。' % ADMIN_PASSWORD_MIN_LENGTH)
        if passwords.equals(passwords.DEFAULT_PASSWORD, new):
            form('初期パスワードは使用できません。別のパスワードを設定してください。')
        if passwords.equals(current, new):
            form('現在と同じパスワードは設定できません。')

        self.db.execute("UPDATE `system_admins` SET `password_hash` = ? WHERE `id` = ?",
                        (passwords.hash_password(new), int(admin['id'])))
        self.auth.set_admin_must_change_password(False)
        try:
            # システム管理者の操作のため tenant_id / user_id は NULL
            AuditLog(self.db).log(None, None, str(admin.get('username') or 'system_admin'), None, 'edit',
                                  int(admin['id']), None, {'action': 'system_admin_password_changed'},
                                  self.request.ip())
        except Exception:
            pass
        self.redirect('/admin/index.cgi?page=password&done=1')

    def _handle_login(self):
        self.verify_csrf()
        username = trim(self.request.post_str('username'))
        password = self.request.raw_post('password')
        if is_empty(username) or is_empty(password):
            self.render('admin/login', {'error': 'ユーザー名とパスワードを入力してください。'}, 'admin')
        if not self.auth.admin_login(username, password):
            self.render('admin/login', {'error': 'ユーザー名またはパスワードが正しくありません。'}, 'admin')
        self.redirect('/admin/index.cgi?page=dashboard')
