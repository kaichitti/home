"""拠点管理（テナント管理者のみ）"""
import re

from ..core.controller import BaseController
from ..models.audit_log import AuditLog
from ..models.branch import Branch, BranchError
from ..util import is_empty

_CODE_RE = re.compile(r'[A-Za-z0-9_-]+')


def _validate(name, address=''):
    errors = {}
    # 所在地は DB の列長（512文字）まで
    if len(address) > 512:
        errors['address'] = '所在地は512文字以内で入力してください。'
    if name == '':
        errors['name'] = '拠点名は必須です。'
    elif len(name) > 255:
        errors['name'] = '拠点名は255文字以内で入力してください。'
    return errors


def _code_error(model, tenant_id, code, exclude_id=None):
    if len(code) > 50:
        return '拠点ログインコードは50文字以内で入力してください。'
    if not _CODE_RE.fullmatch(code):
        return '拠点ログインコードは半角英数字・ハイフン・アンダースコアのみ使用できます。'
    if model.login_code_exists(tenant_id, code, exclude_id):
        return 'この拠点ログインコードは既に使用されています。'
    return None


class BranchController(BaseController):
    def index(self):
        self.auth.require_admin_role()
        self.render('branch/index', {'branches': Branch(self.db).find_all_by_tenant(self.auth.tenant_id())})

    def create(self):
        self.auth.require_admin_role()
        self.render('branch/form', {'branch': None, 'errors': {}, 'isEdit': False})

    def store(self):
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        name = self.post_string('name')
        address = self.post_string('address')
        code = self.post_string('login_code')
        errors = _validate(name, address)
        model = Branch(self.db)
        if code != '':
            err = _code_error(model, tenant_id, code)
            if err:
                errors['login_code'] = err
        if errors:
            self.render('branch/form', {'branch': None, 'errors': errors, 'isEdit': False,
                                        'input': {'name': name, 'address': address, 'login_code': code}})
        new_id = model.create(tenant_id, name, None if is_empty(address) else address,
                              None if is_empty(code) else code)
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'create', new_id, None,
                              {'name': name, 'address': address}, self.request.ip())
        self.flash('success', '拠点「%s」を登録しました。' % name)
        self.redirect('/index.cgi?page=branch')

    def edit(self):
        self.auth.require_admin_role()
        branch = Branch(self.db).find_by_id(self.get_int('id'), self.auth.tenant_id())
        if branch is None:
            self.not_found('拠点が見つかりません。')
        self.render('branch/form', {'branch': branch, 'errors': {}, 'isEdit': True})

    def update(self):
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        branch_id = self.post_int('id')
        name = self.post_string('name')
        address = self.post_string('address')
        code = self.post_string('login_code')
        model = Branch(self.db)
        before = model.find_by_id(branch_id, tenant_id)
        if before is None:
            self.not_found('拠点が見つかりません。')
        errors = _validate(name, address)
        # 重複チェックはコードを変更する場合のみ（旧バージョンの重複コードが残っていても名称等は保存できるように）
        changed = code.lower() != str(before.get('login_code') or '').lower()
        if code != '' and changed:
            err = _code_error(model, tenant_id, code, branch_id)
            if err:
                errors['login_code'] = err
        if errors:
            b = dict(before)
            b['login_code'] = code
            self.render('branch/form', {'branch': b, 'errors': errors, 'isEdit': True,
                                        'input': {'name': name, 'address': address, 'login_code': code}})
        model.update(branch_id, tenant_id, name, None if is_empty(address) else address,
                     None if is_empty(code) else code)
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', branch_id,
                              {'name': before['name'], 'address': before['address']},
                              {'name': name, 'address': address}, self.request.ip())
        self.flash('success', '拠点「%s」を更新しました。' % name)
        self.redirect('/index.cgi?page=branch')

    def delete(self):
        """削除（所属ユーザー・台帳がある場合はメッセージを表示して一覧へ戻る）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        branch_id = self.post_int('id')
        model = Branch(self.db)
        branch = model.find_by_id(branch_id, tenant_id)
        if branch is None:
            self.not_found('拠点が見つかりません。')
        if not is_empty(branch.get('is_main')):
            self.flash('error', '主拠点は削除できません。名称の変更のみ可能です。')
            self.redirect('/index.cgi?page=branch')
        try:
            model.delete(branch_id, tenant_id)
        except BranchError as e:
            self.flash('error', str(e))
            self.redirect('/index.cgi?page=branch')
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'delete', branch_id,
                              {'name': branch['name'], 'address': branch['address']}, None, self.request.ip())
        self.flash('success', '拠点「%s」を削除しました。' % branch['name'])
        self.redirect('/index.cgi?page=branch')
