"""古物区分の管理（テナント管理者のみ。法定13区分に加えて独自の区分を追加・削除できる）"""
from ..core.controller import BaseController
from ..models import item_category
from ..models.audit_log import AuditLog
from ..models.item_category import CategoryError, ItemCategory


class CategoryController(BaseController):
    def index(self):
        self.auth.require_admin_role()
        self.render('category/index', {
            'categories': ItemCategory(self.db).find_all_by_tenant(self.auth.tenant_id()),
            'statutory': item_category.STATUTORY,
        })

    def store(self):
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        name = self.post_string('name')
        try:
            new_id = ItemCategory(self.db).create(tenant_id, name)
            AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'create', new_id, None,
                                  {'item_category_name': name}, self.request.ip())
            self.flash('success', '古物区分「%s」を追加しました。' % name)
        except CategoryError as e:
            self.flash('error', str(e))
        self.redirect('/index.cgi?page=category')

    def delete(self):
        """削除（過去の台帳には区分名がそのまま保存されているため、既存データに影響しない）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        cat_id = self.post_int('id')
        model = ItemCategory(self.db)
        target = model.find_by_id(cat_id, tenant_id)
        if target is None:
            self.flash('error', '区分が見つかりません。')
            self.redirect('/index.cgi?page=category')
        model.delete(cat_id, tenant_id)
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'delete', cat_id,
                              {'item_category_name': target['name']}, None, self.request.ip())
        self.flash('success', '古物区分「%s」を削除しました。（登録済みの台帳の表記は変わりません）' % target['name'])
        self.redirect('/index.cgi?page=category')
