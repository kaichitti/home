"""
会員管理（相手方情報・本人確認情報の引用元）
閲覧・登録・編集は全ユーザー、削除は管理者のみ。
"""
import math

from ..core.controller import BaseController
from ..db import DBError, ER_DUP_ENTRY
from ..helpers import rate_limiter
from ..models import pos_schema
from ..models.audit_log import AuditLog
from ..models.member import Member
from ..models.pos_transaction import PosTransaction
from ..util import is_digits, is_empty, trim
from ..logger import log_error

DOC_TYPES = ('driver_license', 'my_number', 'passport', 'health_insurance',
             'residence_card', 'residence_status', 'special_permanent', 'other')


class MemberController(BaseController):
    def index(self):
        self.auth.require_login()
        tenant_id = self.auth.tenant_id()
        keyword = trim(self.request.get_str('keyword'))
        page = max(1, self.get_int('p') if self.request.get('p') is not None else 1)
        per_page = 50
        model = Member(self.db)
        members = model.search(tenant_id, keyword, per_page, (page - 1) * per_page)
        total = model.count_all(tenant_id, keyword)
        # POS での購入実績（回数・累計額・最終購入日）
        try:
            pos_schema.ensure(self.db)
            stats = PosTransaction(self.db).member_stats(tenant_id, [m['id'] for m in members])
        except Exception:
            stats = {}
        self.render('member/index', {
            'members': members, 'stats': stats, 'keyword': keyword, 'total': total, 'page': page,
            'totalPages': max(1, int(math.ceil(total / per_page))),
        })

    def show(self):
        """会員詳細（基本情報・POS での購入履歴・買取（台帳）履歴）"""
        self.auth.require_login()
        tenant_id = self.auth.tenant_id()
        member_id = self.get_int('id')
        member = Member(self.db).find_by_id(member_id, tenant_id)
        if member is None:
            self.not_found('会員が見つかりません（削除された可能性があります）。')
        pos_schema.ensure(self.db)
        txs = PosTransaction(self.db)
        stats = txs.member_stats(tenant_id, [member_id]).get(member_id) or {'count': 0, 'total': 0, 'last_at': None}
        recent = txs.search(tenant_id, {'member_id': member_id}, 1, 20)
        # 買取（台帳）: 会員番号で紐付いた台帳
        ledgers = self.db.query(
            """SELECT `id`, `transaction_date`, `transaction_type`, `item_name`, `quantity`, `transaction_amount`
             FROM `ledgers`
             WHERE `tenant_id` = ? AND `member_code` = ? AND `deleted_at` IS NULL
             ORDER BY `transaction_date` DESC, `id` DESC LIMIT 20""", (tenant_id, member['member_code']))
        buy = self.db.query_one(
            """SELECT COUNT(*) AS cnt, COALESCE(SUM(`transaction_amount`), 0) AS total FROM `ledgers`
             WHERE `tenant_id` = ? AND `member_code` = ? AND `deleted_at` IS NULL""",
            (tenant_id, member['member_code'])) or {'cnt': 0, 'total': 0}
        self.render('member/show', {
            'member': member, 'stats': stats, 'recent': recent['rows'], 'recentTotal': recent['total'],
            'ledgers': ledgers, 'buyCount': int(buy['cnt']), 'buyTotal': int(buy['total']), 'activePage': 'member',
        })

    def create(self):
        self.auth.require_login()
        self.render('member/form', {'member': None, 'errors': {}})

    def store(self):
        self.auth.require_login()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        data = self._collect_input()
        model = Member(self.db)
        # 会員番号が空欄なら自動で採番する（M-0001 形式）
        auto_code = False
        if data['member_code'] == '':
            data['member_code'] = model.generate_code(tenant_id)
            auto_code = True
        errors = self._validate(tenant_id, data)
        if errors:
            if auto_code:
                data['member_code'] = ''
            self.render('member/form', {'member': None, 'errors': errors, 'input': data})
        try:
            new_id = model.create(tenant_id, data)
        except DBError as e:
            # 同時に同じ番号が登録された場合など（一意制約違反）は入力内容を残して再表示する
            log_error('MemberController.store failed: %s' % e)
            shown = dict(data, member_code='') if auto_code else data
            self.render('member/form', {'member': None, 'input': shown, 'errors': {'member_code':
                        'この会員番号はすでに登録されています。' if e.code == ER_DUP_ENTRY
                        else '会員を登録できませんでした。入力内容を確認してください。'}})
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'create', new_id, None,
                              {'member_code': data['member_code'], 'name': data['name'], 'kind': 'member'},
                              self.request.ip())
        self.flash('success', '会員「%s」（%s）を登録しました。%s'
                   % (data['member_code'], data['name'], '（会員番号は自動採番）' if auto_code else ''))
        self.redirect('/index.cgi?page=member.show&id=%d' % new_id)

    def edit(self):
        self.auth.require_login()
        member = Member(self.db).find_by_id(self.get_int('id'), self.auth.tenant_id())
        if member is None:
            self.not_found('会員が見つかりません。')
        self.render('member/form', {'member': member, 'errors': {}})

    def update(self):
        self.auth.require_login()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        member_id = self.post_int('id')
        model = Member(self.db)
        member = model.find_by_id(member_id, tenant_id)
        if member is None:
            self.not_found('会員が見つかりません。')
        data = self._collect_input()
        errors = self._validate(tenant_id, data, member_id)
        if errors:
            self.render('member/form', {'member': member, 'errors': errors, 'input': data})
        try:
            model.update(member_id, tenant_id, data)
        except DBError as e:
            log_error('MemberController.update failed: %s' % e)
            self.render('member/form', {'member': member, 'input': data, 'errors': {'member_code':
                        'この会員番号はすでに登録されています。' if e.code == ER_DUP_ENTRY
                        else '会員情報を保存できませんでした。入力内容を確認してください。'}})
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', member_id,
                              {'member_code': member['member_code'], 'name': member['name'], 'kind': 'member'},
                              {'member_code': data['member_code'], 'name': data['name'], 'kind': 'member'},
                              self.request.ip())
        self.flash('success', '会員「%s」の情報を更新しました。' % data['member_code'])
        self.redirect('/index.cgi?page=member.show&id=%d' % member_id)

    def delete(self):
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        member_id = self.post_int('id')
        model = Member(self.db)
        member = model.find_by_id(member_id, tenant_id)
        if member is None:
            self.flash('error', '会員が見つかりません。')
            self.redirect('/index.cgi?page=member')
        model.delete(member_id, tenant_id)
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'delete', member_id,
                              {'member_code': member['member_code'], 'name': member['name'], 'kind': 'member'},
                              None, self.request.ip())
        self.flash('success', '会員「%s」を削除しました。（過去の台帳記録は変わりません）' % member['member_code'])
        self.redirect('/index.cgi?page=member')

    def lookup(self):
        """会員番号から会員情報を JSON で返す（台帳フォームの引用ボタン用）"""
        self.auth.require_login()
        tenant_id = self.auth.tenant_id()
        code = trim(self.request.get_str('code'))
        # 会員番号の総当たりによる会員情報の列挙を防ぐ（1分間に30回まで）
        if not rate_limiter.hit(self.session, 'member.lookup', 30, 60):
            self.json({'found': False, 'message': '短時間に照会が集中しています。しばらく待ってから再度お試しください。'}, 429)
        if code == '':
            self.json({'found': False, 'message': '会員番号を入力してください。'})
        m = Member(self.db).find_by_code(tenant_id, code)
        if m is None:
            self.json({'found': False, 'message': '会員番号「%s」は登録されていません。' % code})
        self.json({'found': True, 'member': {
            'member_code': m['member_code'],
            'counterpart_type': m['counterpart_type'],
            'name': m['name'],
            'address': m['address'] or '',
            'occupation': m['occupation'] or '',
            'age': str(m['age']) if m['age'] is not None else '',
            'phone': m['phone'] or '',
            'contact_name': m['contact_name'] or '',
            'account': m['account'] or '',
            'id_document_type': m['id_document_type'] or '',
            # 本人確認書類番号は個人情報のため返さない（登録の有無だけ返す）
            'has_id_document_number': not is_empty(m['id_document_number']),
        }})

    def _collect_input(self):
        ctype = self.request.post('counterpart_type', 'individual')
        doc_type = self.post_string('id_document_type')
        return {
            'member_code': self.post_string('member_code'),
            'counterpart_type': ctype if ctype in ('individual', 'corporate') else 'individual',
            'name': self.post_string('name'),
            'address': self.post_string('address'),
            'occupation': self.post_string('occupation'),
            'age': self.post_string('age'),
            'phone': self.post_string('phone'),
            'contact_name': self.post_string('contact_name'),
            'account': self.post_string('account'),
            'id_document_type': doc_type,
            # マイナンバーカードの個人番号は法令上記録できないため捨てる（種別が未選択の場合も捨てる）
            'id_document_number': '' if doc_type in ('my_number', '') else self.post_string('id_document_number'),
            'note': self.post_string('note'),
        }

    def _validate(self, tenant_id, d, exclude_id=None):
        errors = {}
        if d['member_code'] == '':
            errors['member_code'] = '会員番号を入力してください。'
        elif len(d['member_code']) > 50:
            errors['member_code'] = '会員番号は50文字以内で入力してください。'
        elif Member(self.db).exists_code(tenant_id, d['member_code'], exclude_id):
            errors['member_code'] = 'この会員番号はすでに登録されています。'
        if d['name'] == '':
            errors['name'] = '名称（会社名）を入力してください。' if d['counterpart_type'] == 'corporate' else '氏名を入力してください。'
        if d['counterpart_type'] == 'corporate' and d['contact_name'] == '':
            errors['contact_name'] = '法人の場合は担当者名を入力してください。'
        # 文字数の上限（DB の列長）
        for field, mx, label in (('name', 255, '氏名・名称'), ('address', 512, '住所'), ('occupation', 255, '職業'),
                                 ('phone', 20, '電話番号'), ('contact_name', 255, '担当者名'),
                                 ('account', 255, '取引アカウント'), ('id_document_number', 64, '書類番号')):
            if is_empty(errors.get(field)) and len(d[field]) > mx:
                errors[field] = '%sは%d文字以内で入力してください。' % (label, mx)
        if len(d['note'].encode('utf-8')) > 65535:
            errors['note'] = '備考が長すぎます（全角で約2万文字まで）。'
        if d['age'] != '' and (not is_digits(d['age']) or int(d['age']) > 150):
            errors['age'] = '年齢は0〜150の数値で入力してください。'
        if d['id_document_type'] != '' and d['id_document_type'] not in DOC_TYPES:
            errors['id_document_type'] = '本人確認書類種別の値が不正です。'
        return errors
