"""
テナント管理（システム管理者専用）
テナントの作成・変更・停止・再開・削除と、テナント利用者のパスワード再設定・ロック解除。
テナント作成時は主拠点と初期管理者（オーナー）を自動で作る。
"""
from ...core.controller import BaseController
from ...helpers import passwords
from ...helpers.login_throttle import LoginThrottle, account_key
from ...helpers.validator import Validator
from ...logger import log_error
from ...models.audit_log import AuditLog
from ...models.tenant import Tenant
from ...models.user import User
from ...util import trim

USER_PASSWORD_MIN_LENGTH = 8  # テナント利用者のパスワードの最小文字数

FIELD_LABELS = {
    'code': 'テナントコード', 'name': 'テナント名', 'type': '種別', 'status': '状態',
    'admin_email': 'メールアドレス', 'admin_name': '表示名',
}

CODE_RULE = r'required|min:1|max:50|regex:(?i)[a-z0-9_\-]+'


class TenantController(BaseController):
    def dashboard(self):
        self.auth.require_system_admin()
        tenants = Tenant(self.db).find_all_with_stats()
        self.render('admin/dashboard', {'tenants': tenants, 'totalCount': len(tenants)}, 'admin')

    def index(self):
        """テナント一覧（?deleted=1 で削除済みも表示）"""
        self.auth.require_system_admin()
        show_deleted = self.request.get('deleted') == '1'
        self.render('admin/tenant/index', {'tenants': Tenant(self.db).find_all_with_stats(show_deleted),
                                           'showDeleted': show_deleted}, 'admin')

    def create(self):
        self.auth.require_system_admin()
        self.render('admin/tenant/form', {'tenant': None, 'error': None, 'errors': {}}, 'admin')

    def store(self):
        """作成（コード重複を確認し、テナント・主拠点・初期管理者（オーナー）を作る）"""
        self.auth.require_system_admin()
        self.verify_csrf()
        data = self.request.all()

        def form(error, errors):
            old = dict(data)
            old.pop('admin_password', None)
            old.pop('admin_password_confirm', None)
            self.render('admin/tenant/form', {'tenant': None, 'error': error, 'errors': errors, 'old': old}, 'admin')

        v = Validator(data, FIELD_LABELS)
        valid = v.validate({
            'code': CODE_RULE,
            'name': 'required|min:1|max:255',
            'type': 'required|in:own,client',
            'admin_email': 'required|email|max:255',
            'admin_name': 'required|min:1|max:255',
        })
        errors = v.first_errors()
        # 初期パスワード（加工せずに受け取る）
        password = self.request.raw_post('admin_password')
        confirm = self.request.form.get('admin_password_confirm')
        confirm = confirm if isinstance(confirm, str) else None
        pw_error = passwords.policy_error(password, USER_PASSWORD_MIN_LENGTH)
        if pw_error is not None:
            errors['admin_password'] = pw_error
        elif confirm is not None and not passwords.equals(password, confirm):
            errors['admin_password_confirm'] = 'パスワードと確認用パスワードが一致しません。'
        if not valid or errors:
            form('入力内容を確認してください。', errors)

        tenants = Tenant(self.db)
        code = trim(str(data['code']))
        # テナントコードは他のテナントのコード・拠点ログインコードと重ならないこと
        # （ログイン時はテナントコードが優先されるため、重なると拠点の利用者が別テナントへ案内される）
        if tenants.is_code_taken(code) or self._branch_login_code_exists(code):
            form('このテナントコードはすでに使用されています。',
                 {'code': 'このテナントコードはすでに使用されています（拠点ログインコードを含む）。'})

        name = trim(str(data['name']))
        try:
            self.db.begin()
            tenant_id = tenants.create({'code': code, 'name': name, 'type': data['type'], 'status': 'active'})
            # 主拠点を自動で作る（拠点が無いと台帳を登録できないため）
            branch_id = self.db.insert("INSERT INTO `branches` (`tenant_id`, `name`, `is_main`) VALUES (?, '本社', 1)",
                                       (tenant_id,))
            owner_id = User(self.db).create({
                'tenant_id': tenant_id, 'branch_id': branch_id, 'display_name': trim(str(data['admin_name'])),
                'email': trim(str(data['admin_email'])), 'password': password, 'role': 'admin',
                'is_active': 1, 'must_change_password': 1,
            })
            # 初期管理者をオーナーにする（削除・無効化・降格できない）
            self.db.execute("UPDATE `users` SET `is_owner` = 1 WHERE `id` = ? AND `tenant_id` = ?", (owner_id, tenant_id))
            self.db.commit()
        except Exception as e:
            if self.db.in_transaction:
                self.db.rollback()
            log_error('tenant create failed: %s' % e)
            form('テナントの作成中にエラーが発生しました。入力内容を確認して、もう一度お試しください。', {})

        self._audit('create', tenant_id, None, {'kind': 'tenant', 'code': code, 'name': name,
                                                'owner_email': trim(str(data['admin_email']))})
        self.flash('success', 'テナント「%s」を作成しました。テナントコード「%s」・管理者のメールアドレス・設定した初期パスワードを'
                              '先方に伝えてください（初回ログイン時にパスワードの変更が求められます）。' % (name, code))
        self.redirect('/admin/index.cgi?page=tenant.show&id=%d' % tenant_id)

    def show(self):
        """テナント詳細（利用者一覧・パスワード再設定・ロック解除）"""
        self.auth.require_system_admin()
        tenant_id = self.get_int('id')
        tenant = Tenant(self.db).find_by_id(tenant_id)
        if tenant is None:
            self.not_found('テナントが見つかりません。')
        stats = {}
        for key, sql in (
                ('ledger_count', "SELECT COUNT(*) FROM `ledgers` WHERE `tenant_id` = ? AND `deleted_at` IS NULL"),
                ('branch_count', "SELECT COUNT(*) FROM `branches` WHERE `tenant_id` = ?"),
                ('member_count', "SELECT COUNT(*) FROM `members` WHERE `tenant_id` = ?")):
            try:
                stats[key] = int(self.db.value(sql, (tenant_id,)) or 0)
            except Exception:
                stats[key] = 0
        self.render('admin/tenant/show', {'tenant': tenant, 'users': User(self.db).get_by_tenant(tenant_id),
                                          'stats': stats}, 'admin')

    def edit(self):
        self.auth.require_system_admin()
        tenant_id = self.get_int('id')
        tenant = Tenant(self.db).find_by_id(tenant_id)
        if tenant is None:
            self.not_found('テナントが見つかりません。')
        if tenant['status'] == 'deleted':
            self.flash('error', '削除済みのテナントは編集できません。')
            self.redirect('/admin/index.cgi?page=tenant.show&id=%d' % tenant_id)
        self.render('admin/tenant/form', {'tenant': tenant, 'error': None, 'errors': {}}, 'admin')

    def update(self):
        self.auth.require_system_admin()
        self.verify_csrf()
        tenant_id = self.post_int('id')
        data = self.request.all()
        tenants = Tenant(self.db)
        tenant = tenants.find_by_id(tenant_id)
        if tenant is None:
            self.not_found('テナントが見つかりません。')
        # 削除済みテナントは利用者が全員無効化されているため、編集で中途半端に「有効」へ戻さない
        if tenant['status'] == 'deleted':
            self.flash('error', '削除済みのテナントは編集できません。')
            self.redirect('/admin/index.cgi?page=tenant.show&id=%d' % tenant_id)
        v = Validator(data, FIELD_LABELS)
        if not v.validate({'code': CODE_RULE, 'name': 'required|min:1|max:255', 'type': 'required|in:own,client',
                           'status': 'required|in:active,suspended'}):
            self.render('admin/tenant/form', {'tenant': tenant, 'error': '入力内容を確認してください。',
                                              'errors': v.first_errors(), 'old': data}, 'admin')
        # コード重複（自分自身を除く）。拠点ログインコードとの衝突確認はコードを変更する場合のみ
        new_code = trim(str(data['code']))
        changed = new_code.lower() != str(tenant['code']).lower()
        if tenants.is_code_taken(new_code, tenant_id) or (changed and self._branch_login_code_exists(new_code)):
            self.render('admin/tenant/form', {
                'tenant': tenant, 'error': 'このテナントコードはすでに使用されています。',
                'errors': {'code': 'このテナントコードはすでに使用されています（拠点ログインコードを含む）。'}, 'old': data,
            }, 'admin')
        after = {'code': new_code, 'name': trim(str(data['name'])), 'type': data['type'], 'status': data['status']}
        tenants.update(tenant_id, after)
        a = {'kind': 'tenant'}
        a.update(after)
        self._audit('edit', tenant_id, {'kind': 'tenant', 'code': tenant['code'], 'name': tenant['name'],
                                        'type': tenant['type'], 'status': tenant['status']}, a)
        msg = 'テナント「%s」を更新しました。' % after['name']
        if changed:
            msg += 'テナントコードを変更したため、利用者には新しいコード「%s」でログインするよう伝えてください。' % new_code
        self.flash('success', msg)
        self.redirect('/admin/index.cgi?page=tenant.show&id=%d' % tenant_id)

    def suspend(self):
        """停止（利用者はログインできなくなる。データは保持）"""
        self.auth.require_system_admin()
        self.verify_csrf()
        tenant_id = self.post_int('id')
        tenants = Tenant(self.db)
        tenant = tenants.find_by_id(tenant_id)
        if tenant is None:
            self.not_found('テナントが見つかりません。')
        if tenant['status'] != 'active':
            self.flash('error', 'このテナントは有効ではないため停止できません。')
            self.redirect(self._back_url(tenant_id))
        tenants.suspend(tenant_id)
        self._audit('edit', tenant_id, {'kind': 'tenant', 'status': 'active'},
                    {'kind': 'tenant', 'status': 'suspended', 'action': 'tenant_suspended'})
        self.flash('success', 'テナント「%s」を停止しました（利用者はログインできなくなります。データは保持されます）。' % tenant['name'])
        self.redirect(self._back_url(tenant_id))

    def resume(self):
        """停止中のテナントを再開する"""
        self.auth.require_system_admin()
        self.verify_csrf()
        tenant_id = self.post_int('id')
        tenants = Tenant(self.db)
        tenant = tenants.find_by_id(tenant_id)
        if tenant is None:
            self.not_found('テナントが見つかりません。')
        if not tenants.resume(tenant_id):
            self.flash('error', '停止中のテナントのみ再開できます。')
            self.redirect(self._back_url(tenant_id))
        self._audit('edit', tenant_id, {'kind': 'tenant', 'status': 'suspended'},
                    {'kind': 'tenant', 'status': 'active', 'action': 'tenant_resumed'})
        self.flash('success', 'テナント「%s」を再開しました。' % tenant['name'])
        self.redirect(self._back_url(tenant_id))

    def delete(self):
        """削除（論理削除・全利用者を無効化。確認欄にテナントコードを入力した場合のみ）"""
        self.auth.require_system_admin()
        self.verify_csrf()
        tenant_id = self.post_int('id')
        tenants = Tenant(self.db)
        tenant = tenants.find_by_id(tenant_id)
        if tenant is None:
            self.not_found('テナントが見つかりません。')
        confirm = self.request.post('confirm_code', '')
        if not isinstance(confirm, str) or confirm != str(tenant['code']):
            self.flash('error', '削除するには、確認欄にテナントコード「%s」を正確に入力してください。' % tenant['code'])
            self.redirect('/admin/index.cgi?page=tenant.show&id=%d' % tenant_id)
        try:
            self.db.begin()
            User(self.db).deactivate_all_by_tenant(tenant_id)
            tenants.delete(tenant_id)
            self.db.commit()
        except Exception as e:
            if self.db.in_transaction:
                self.db.rollback()
            log_error('tenant delete failed: %s' % e)
            self.flash('error', 'テナントの削除に失敗しました。もう一度お試しください。')
            self.redirect('/admin/index.cgi?page=tenant.show&id=%d' % tenant_id)
        self._audit('delete', tenant_id, {'kind': 'tenant', 'code': tenant['code'], 'name': tenant['name'],
                                          'status': tenant['status']}, None)
        self.flash('success', 'テナント「%s」を削除しました（全利用者を無効化しました。台帳データはDBに保持されています）。' % tenant['name'])
        self.redirect('/admin/index.cgi?page=tenant')

    def user_password(self):
        """テナント利用者のパスワード再設定（ロック解除を含む。オーナーが忘れた場合など）"""
        self.auth.require_system_admin()
        self.verify_csrf()
        tenant_id = self.post_int('tenant_id')
        user_id = self.post_int('user_id')
        back = '/admin/index.cgi?page=tenant.show&id=%d' % tenant_id
        users = User(self.db)
        target = users.find_by_id(user_id, tenant_id)
        if target is None:
            self.not_found('ユーザーが見つかりません。')
        password = self.request.raw_post('new_password')
        confirm = self.request.raw_post('new_password_confirm')
        pw_error = passwords.policy_error(password, USER_PASSWORD_MIN_LENGTH)
        if pw_error is None and not passwords.equals(password, confirm):
            pw_error = '新しいパスワードと確認用パスワードが一致しません。'
        if pw_error is not None:
            self.flash('error', '「%s」のパスワードを再設定できませんでした: %s' % (target['display_name'], pw_error))
            self.redirect(back)
        users.reset_password(user_id, tenant_id, password)
        LoginThrottle(self.db).clear_failures(account_key('tenant', 'uid:%d' % user_id))
        self._audit('edit', user_id, {'kind': 'user', 'display_name': target['display_name']},
                    {'action': 'password_reset_by_system_admin', 'unlocked': True}, tenant_id)
        self.flash('success', '「%s」のパスワードを再設定しました（ロックも解除しました）。設定したパスワードを本人に伝えてください。'
                              '次回ログイン時に本人のパスワードへの変更が求められます。' % target['display_name'])
        self.redirect(back)

    def user_unlock(self):
        self.auth.require_system_admin()
        self.verify_csrf()
        tenant_id = self.post_int('tenant_id')
        user_id = self.post_int('user_id')
        users = User(self.db)
        target = users.find_by_id(user_id, tenant_id)
        if target is None:
            self.not_found('ユーザーが見つかりません。')
        users.unlock(user_id, tenant_id)
        LoginThrottle(self.db).clear_failures(account_key('tenant', 'uid:%d' % user_id))
        self._audit('edit', user_id, {'kind': 'user', 'display_name': target['display_name']},
                    {'action': 'account_unlocked_by_system_admin'}, tenant_id)
        self.flash('success', '「%s」のログインロックを解除しました。' % target['display_name'])
        self.redirect('/admin/index.cgi?page=tenant.show&id=%d' % tenant_id)

    # ------------------------------------------------------------------
    def _back_url(self, tenant_id):
        """操作後の戻り先（詳細画面から操作した場合は詳細へ、それ以外は一覧へ）"""
        if self.request.post('back') == 'show':
            return '/admin/index.cgi?page=tenant.show&id=%d' % tenant_id
        return '/admin/index.cgi?page=tenant'

    def _audit(self, action, target_id, before, after, tenant_id=None):
        """システム管理者の操作を監査ログに記録する"""
        try:
            admin = self.auth.admin_user() or {}
            AuditLog(self.db).log(tenant_id, None, '[システム管理者] ' + str(admin.get('username') or 'system_admin'),
                                  None, action, target_id, before, after, self.request.ip())
        except Exception as e:
            log_error('admin audit log failed: %s' % e)

    def _branch_login_code_exists(self, code):
        try:
            return int(self.db.value("SELECT COUNT(*) FROM `branches` WHERE `login_code` = ?", (code,)) or 0) > 0
        except Exception:
            return False
