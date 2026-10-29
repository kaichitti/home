"""テナントユーザーのログイン・パスワード変更・メールアドレス変更"""
from ..core.controller import BaseController
from ..helpers import passwords
from ..helpers.validator import Validator, is_email
from ..models.audit_log import AuditLog
from ..models.user import User
from ..util import trim


class AuthController(BaseController):
    def login(self):
        if self.auth.is_logged_in():
            self.redirect('/index.cgi?page=dashboard')
        if self.request.is_post():
            self._handle_login()
        self.render('auth/login', {'error': None})

    def logout(self):
        self.auth.logout()
        self.redirect('/index.cgi?page=login')

    def change_password(self):
        """パスワード変更（GET: 画面 / POST: 変更）"""
        self.auth.require_login()

        def form(error, errors=None):
            self.render('auth/change_password', {'error': error, 'errors': errors or {}})

        if not self.request.is_post():
            form(None)
        self.verify_csrf()

        data = self.request.all()
        v = Validator(data, {'current_password': '現在のパスワード', 'new_password': '新しいパスワード',
                             'confirm_password': '確認用パスワード'})
        if not v.validate({'current_password': 'required|min:1', 'new_password': 'required|min:8',
                           'confirm_password': 'required|min:1'}):
            form('入力内容を確認してください。', v.first_errors())

        # パスワードは加工せずに受け取る
        new = self.request.raw_post('new_password')
        confirm = self.request.raw_post('confirm_password')
        current = self.request.raw_post('current_password')

        if '\0' in new:
            form('パスワードに使用できない文字が含まれています。')
        # 現在と同じパスワードへの「変更」は認めない（初回変更の強制を回避できないように）
        if new != '' and passwords.equals(current, new):
            form('現在と同じパスワードは設定できません。')
        if new != confirm:
            form('新しいパスワードと確認用パスワードが一致しません。')
        # bcrypt は72バイトを超える部分を無視するため、長すぎるパスワードは受け付けない
        if len(new.encode('utf-8')) > 72:
            form('パスワードは72バイト（半角72文字）以内で入力してください。')
        if len(new) < 8 or not passwords.is_alpha_numeric(new):
            form('パスワードは8文字以上で、英字・数字をそれぞれ1文字以上含めてください。')
        # 公開されている初期パスワードへの再設定は禁止
        if passwords.equals(passwords.DEFAULT_PASSWORD, new):
            form('初期パスワードは使用できません。別のパスワードを設定してください。')

        user_id = self.auth.user_id()
        tenant_id = self.auth.tenant_id()
        users = User(self.db)
        user = users.find_by_id(user_id, tenant_id)
        if user is None:
            self.redirect('/index.cgi?page=login')
        if not passwords.verify(current, user['password_hash']):
            form('現在のパスワードが正しくありません。')

        users.change_password(user_id, tenant_id, new)
        self.auth.set_must_change_password(False)
        AuditLog(self.db).log(tenant_id, user_id, user['display_name'], None, 'edit', user_id, None,
                              {'action': 'password_changed'}, self.request.ip())
        self.flash('success', 'パスワードを変更しました。次回から新しいパスワードでログインしてください。')
        self.redirect('/index.cgi?page=dashboard')

    def account(self):
        """アカウント設定（メールアドレス変更。ログインIDのため現在のパスワードの再確認が必要）"""
        self.auth.require_login()
        user_id = self.auth.user_id()
        tenant_id = self.auth.tenant_id()
        users = User(self.db)
        user = users.find_by_id(user_id, tenant_id)
        if user is None:
            self.redirect('/index.cgi?page=login')

        def form(error):
            self.render('auth/account', {'currentEmail': user['email'], 'error': error})

        if not self.request.is_post():
            form(None)
        self.verify_csrf()

        new_email = trim(self.request.post_str('new_email'))
        password = self.request.raw_post('current_password')
        if new_email == '' or not is_email(new_email):
            form('正しいメールアドレス形式で入力してください。')
        if len(new_email) > 255:
            form('メールアドレスは255文字以内で入力してください。')
        if new_email == user['email']:
            form('現在のメールアドレスと同じです。')
        if not passwords.verify(password, user['password_hash']):
            form('現在のパスワードが正しくありません。')
        # テナント内での重複チェック（自分自身を除く）
        if int(self.db.value("SELECT COUNT(*) FROM `users` WHERE `tenant_id` = ? AND `email` = ? AND `id` != ?",
                             (tenant_id, new_email, user_id)) or 0) > 0:
            form('このメールアドレスはすでに使用されています。')

        users.change_email(user_id, tenant_id, new_email)
        AuditLog(self.db).log(tenant_id, user_id, user['display_name'], None, 'edit', user_id,
                              {'email': user['email']}, {'email': new_email, 'action': 'email_changed'},
                              self.request.ip())
        self.flash('success', 'メールアドレスを変更しました。次回から新しいアドレスでログインしてください。')
        self.redirect('/index.cgi?page=account')

    def _handle_login(self):
        self.verify_csrf()
        data = self.request.all()
        v = Validator(data, {'tenant_code': 'テナントコード', 'email': 'メールアドレス', 'password': 'パスワード'})
        # ログインに失敗しても、入力したテナントコード・メールアドレスは残す
        old = {
            'tenant_code': data['tenant_code'] if isinstance(data.get('tenant_code'), str) else '',
            'email': data['email'] if isinstance(data.get('email'), str) else '',
        }
        if not v.validate({'tenant_code': 'required|min:1|max:50', 'email': 'required|email',
                           'password': 'required|min:1'}):
            self.render('auth/login', {'error': '入力内容を確認してください。', 'errors': v.first_errors(), 'old': old})

        tenant_code = trim(str(data['tenant_code']))
        email = trim(str(data['email']))
        password = self.request.raw_post('password')
        if not self.auth.login(tenant_code, email, password):
            self.render('auth/login', {
                'error': 'テナントコード、メールアドレス、またはパスワードが正しくありません。', 'old': old})
        if self.auth.must_change_password():
            self.redirect('/index.cgi?page=change_password')
        self.redirect('/index.cgi?page=dashboard')
