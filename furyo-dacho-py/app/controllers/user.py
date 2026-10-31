"""ユーザー管理（テナント管理者のみ）"""
from ..core.controller import BaseController
from ..helpers import passwords
from ..helpers.login_throttle import LoginThrottle, account_key
from ..helpers.validator import is_email
from ..models.audit_log import AuditLog
from ..models.branch import Branch
from ..models.user import User
from ..util import is_digits, is_empty, to_int, trim

PASSWORD_MIN_LENGTH = 8  # ログイン後の変更画面と同じ


def _branch_value(v):
    return to_int(v) if v is not None and v != '' else None


class UserController(BaseController):
    def index(self):
        self.auth.require_admin_role()
        self.render('user/index', {'users': User(self.db).get_by_tenant(self.auth.tenant_id())})

    def _form(self, user, errors, is_edit, data=None):
        values = {'user': user, 'branches': Branch(self.db).find_all_by_tenant(self.auth.tenant_id()),
                  'errors': errors, 'isEdit': is_edit}
        if data is not None:
            values['input'] = data
        self.render('user/form', values)

    def create(self):
        self.auth.require_admin_role()
        self._form(None, {}, False)

    def store(self):
        """登録（初期パスワードは管理者が入力した値。初回ログイン時に本人のパスワードへの変更を求める）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        data = self.request.all()
        errors = self._validate(data, None, tenant_id)
        password = self.request.raw_post('password')
        confirm = self.request.raw_post('password_confirm')
        pw_error = passwords.policy_error(password, PASSWORD_MIN_LENGTH)
        if pw_error is not None:
            errors['password'] = pw_error
        elif not passwords.equals(password, confirm):
            errors['password_confirm'] = 'パスワードと確認用パスワードが一致しません。'
        if errors:
            data.pop('password', None)
            data.pop('password_confirm', None)
            self._form(None, errors, False, data)

        role = data.get('role') if data.get('role') is not None else 'user'
        new_id = User(self.db).create({
            'tenant_id': tenant_id,
            'branch_id': _branch_value(data.get('branch_id')),
            'display_name': data['display_name'],
            'email': data['email'],
            'password': password,
            'role': role,
            'is_active': 1,
            'must_change_password': 1,
        })
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'create', new_id, None, {
            'display_name': data['display_name'], 'email': data['email'], 'role': role,
            'branch_id': None if is_empty(data.get('branch_id')) else data.get('branch_id'),
        }, self.request.ip())
        self.flash('success', 'ユーザー「%s」を登録しました。設定したパスワードを本人に伝えてください'
                              '（初回ログイン時に本人のパスワードへの変更が求められます）。' % data['display_name'])
        self.redirect('/index.cgi?page=user')

    def edit(self):
        self.auth.require_admin_role()
        user = User(self.db).find_by_id(self.get_int('id'), self.auth.tenant_id())
        if user is None:
            self.not_found('ユーザーが見つかりません。')
        self._form(user, {}, True)

    def update(self):
        """更新（表示名・メール・拠点・権限。パスワードはここでは変更しない）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.post_int('id')
        data = self.request.all()
        users = User(self.db)
        before = users.find_by_id(user_id, tenant_id)
        if before is None:
            self.not_found('ユーザーが見つかりません。')
        errors = self._validate(data, user_id, tenant_id)

        new_role = data.get('role') if data.get('role') is not None else 'user'
        # 編集画面には有効/無効の項目が無いため、送られていなければ現在の値を維持する
        before_active = 1 if int(before['is_active']) == 1 else 0
        has_active = 'is_active' in data
        new_active = (1 if to_int(data['is_active']) == 1 else 0) if has_active else before_active
        is_owner = not is_empty(before.get('is_owner'))
        is_self = user_id == self.auth.user_id()
        # オーナー・自分自身の「無効化」と「管理者からの降格」は禁止
        if (is_owner or is_self) and ((before_active == 1 and new_active == 0)
                                      or (before['role'] == 'admin' and new_role != 'admin')):
            errors['role'] = ('オーナーアカウントは無効化・権限の変更ができません。' if is_owner
                              else '自分自身を無効化・降格することはできません。')
        # オーナーのメールアドレス（ログインID）はオーナー本人しか変更できない
        email_in = data.get('email')
        if is_owner and not is_self and \
                trim(email_in if isinstance(email_in, str) else '').lower() != str(before['email']).lower():
            errors['email'] = 'オーナーのメールアドレスは、オーナー本人が「アカウント設定」から変更してください。'
        if errors:
            self._form(before, errors, True, data)

        users.update(user_id, tenant_id, {
            'display_name': data['display_name'],
            'email': data['email'],
            'role': new_role,
            # 送られていなければ None（DB 側で現在の値を維持する）
            'is_active': new_active if has_active else None,
            'branch_id': _branch_value(data.get('branch_id')),
        })
        audit_before = {'display_name': before['display_name'], 'email': before['email'],
                        'role': before['role'], 'branch_id': before['branch_id']}
        audit_after = {'display_name': data['display_name'], 'email': data['email'], 'role': new_role,
                       'branch_id': None if is_empty(data.get('branch_id')) else data.get('branch_id')}
        if has_active:
            audit_before['is_active'] = before_active
            audit_after['is_active'] = new_active
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', user_id,
                              audit_before, audit_after, self.request.ip())
        self.flash('success', 'ユーザー「%s」の情報を更新しました。' % data['display_name'])
        self.redirect('/index.cgi?page=user')

    def deactivate(self):
        """無効化（自分自身・オーナーは不可）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.post_int('id')
        if user_id == self.auth.user_id():
            self.flash('error', '自分自身を無効化することはできません。')
            self.redirect('/index.cgi?page=user')
        users = User(self.db)
        target = users.find_by_id(user_id, tenant_id)
        if target is None:
            self.not_found('ユーザーが見つかりません。')
        if not is_empty(target.get('is_owner')):
            self.flash('error', 'オーナーアカウントは無効化できません。')
            self.redirect('/index.cgi?page=user')
        users.deactivate(user_id, tenant_id)
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', user_id,
                              {'is_active': 1, 'display_name': target['display_name']}, {'is_active': 0},
                              self.request.ip())
        self.flash('success', '「%s」を無効化しました（ログインできなくなります）。' % target['display_name'])
        self.redirect('/index.cgi?page=user')

    def activate(self):
        """再有効化（誤って無効化した利用者・復職者を元に戻す）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.post_int('id')
        users = User(self.db)
        target = users.find_by_id(user_id, tenant_id)
        if target is None:
            self.not_found('ユーザーが見つかりません。')
        if int(target['is_active']) == 1:
            self.flash('success', 'このユーザーは既に有効です。')
            self.redirect('/index.cgi?page=user')
        users.activate(user_id, tenant_id)
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', user_id,
                              {'is_active': 0, 'display_name': target['display_name']}, {'is_active': 1},
                              self.request.ip())
        self.flash('success', '「%s」を有効にしました。' % target['display_name'])
        self.redirect('/index.cgi?page=user')

    def delete(self):
        """削除（オーナー・自分自身・台帳の登録記録があるユーザーは不可）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.post_int('id')
        if user_id == self.auth.user_id():
            self.flash('error', '自分自身を削除することはできません。')
            self.redirect('/index.cgi?page=user')
        target = User(self.db).find_by_id(user_id, tenant_id)
        if target is None:
            self.not_found('ユーザーが見つかりません。')
        if not is_empty(target.get('is_owner')):
            self.flash('error', 'オーナーアカウントは削除できません。')
            self.redirect('/index.cgi?page=user')
        # 台帳の登録・更新記録がある場合は削除不可（法定帳簿の登録者情報を保全する）
        if int(self.db.value(
                "SELECT COUNT(*) FROM `ledgers` WHERE `tenant_id` = ? AND (`registered_by` = ? OR `updated_by` = ?)",
                (tenant_id, user_id, user_id)) or 0) > 0:
            self.flash('error', 'このユーザーには台帳の登録記録があるため削除できません。'
                                '帳簿の登録者情報を保全するため、代わりに「無効化」を使用してください。')
            self.redirect('/index.cgi?page=user')
        # 承認記録の参照を外してから削除する
        self.db.execute("UPDATE `ledgers` SET `approved_by` = NULL WHERE `tenant_id` = ? AND `approved_by` = ?",
                        (tenant_id, user_id))
        self.db.execute("UPDATE `alerts` SET `confirmed_by` = NULL WHERE `tenant_id` = ? AND `confirmed_by` = ?",
                        (tenant_id, user_id))
        self.db.execute("DELETE FROM `users` WHERE `id` = ? AND `tenant_id` = ?", (user_id, tenant_id))
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'delete', user_id,
                              {'display_name': target['display_name'], 'email': target['email'], 'kind': 'user'},
                              None, self.request.ip())
        self.flash('success', 'ユーザー「%s」を削除しました。' % target['display_name'])
        self.redirect('/index.cgi?page=user')

    def reset_password(self):
        """
        パスワードの再設定（仮パスワードを設定し、次回ログイン時に変更を求める。ロックも解除する）
        オーナーのパスワードは他の管理者からは再設定できない。自分自身は「パスワード変更」画面で変更する。
        """
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.post_int('id')
        back = '/index.cgi?page=user.edit&id=%d' % user_id
        users = User(self.db)
        target = users.find_by_id(user_id, tenant_id)
        if target is None:
            self.not_found('ユーザーが見つかりません。')
        if user_id == self.auth.user_id():
            self.flash('error', '自分のパスワードは「パスワード変更」画面で変更してください。')
            self.redirect(back)
        if not is_empty(target.get('is_owner')):
            self.flash('error', 'オーナーのパスワードは他の管理者からは再設定できません。'
                                'オーナー本人が変更するか、システム管理者に再設定を依頼してください。')
            self.redirect(back)
        password = self.request.raw_post('new_password')
        confirm = self.request.raw_post('new_password_confirm')
        pw_error = passwords.policy_error(password, PASSWORD_MIN_LENGTH)
        if pw_error is None and not passwords.equals(password, confirm):
            pw_error = '新しいパスワードと確認用パスワードが一致しません。'
        if pw_error is not None:
            self.flash('error', 'パスワードを再設定できませんでした: ' + pw_error)
            self.redirect(back)
        users.reset_password(user_id, tenant_id, password)
        LoginThrottle(self.db).clear_failures(account_key('tenant', 'uid:%d' % user_id))
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', user_id,
                              {'display_name': target['display_name']},
                              {'action': 'password_reset_by_admin', 'unlocked': True}, self.request.ip())
        self.flash('success', '「%s」のパスワードを再設定しました（ロックも解除しました）。設定したパスワードを本人に伝えてください。'
                              '次回ログイン時に本人のパスワードへの変更が求められます。' % target['display_name'])
        self.redirect('/index.cgi?page=user')

    def unlock(self):
        """ログインロックの解除（30分待たずにログインできるようにする）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.post_int('id')
        users = User(self.db)
        target = users.find_by_id(user_id, tenant_id)
        if target is None:
            self.not_found('ユーザーが見つかりません。')
        users.unlock(user_id, tenant_id)
        LoginThrottle(self.db).clear_failures(account_key('tenant', 'uid:%d' % user_id))
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', user_id,
                              {'display_name': target['display_name'], 'locked_until': target['locked_until']},
                              {'action': 'account_unlocked'}, self.request.ip())
        self.flash('success', '「%s」のログインロックを解除しました。' % target['display_name'])
        self.redirect('/index.cgi?page=user')

    def _validate(self, data, exclude_id, tenant_id):
        errors = {}
        for k in ('display_name', 'email', 'role', 'branch_id'):
            if k in data and not isinstance(data[k], str):
                data[k] = ''
                errors[k] = '入力値の形式が不正です。'
        name = data.get('display_name')
        if is_empty(name):
            errors['display_name'] = '表示名は必須です。'
        elif len(name) > 255:
            errors['display_name'] = '表示名は255文字以内で入力してください。'
        email = data.get('email')
        if is_empty(email):
            errors['email'] = 'メールアドレスは必須です。'
        elif len(email) > 255:
            errors['email'] = 'メールアドレスは255文字以内で入力してください。'
        elif not is_email(email):
            errors['email'] = '正しいメールアドレス形式で入力してください。'
        else:
            sql = "SELECT `id` FROM `users` WHERE `tenant_id` = ? AND `email` = ?"
            args = [tenant_id, email]
            if exclude_id is not None:
                sql += " AND `id` != ?"
                args.append(exclude_id)
            if self.db.query_one(sql, args) is not None:
                errors['email'] = 'このメールアドレスはすでに使用されています。'
        if data.get('role') not in ('admin', 'user'):
            errors['role'] = '権限の値が無効です。'
        # 所属拠点は自テナントの拠点のみ
        branch_id = data.get('branch_id')
        if branch_id is not None and branch_id != '':
            if not is_digits(str(branch_id)) or Branch(self.db).find_by_id(int(branch_id), tenant_id) is None:
                errors['branch_id'] = '所属拠点の値が無効です。'
        return errors
