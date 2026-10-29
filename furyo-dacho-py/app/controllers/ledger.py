"""古物台帳（一覧・登録・詳細・編集・削除・承認・販売記録）"""
import math

from ..core.controller import BaseController
from ..core.response import ResponseDone
from ..db import DBError, ER_LOCK_DEADLOCK, ER_LOCK_WAIT_TIMEOUT
from ..helpers.file_upload import FileUpload, UploadError, detect_mime
from ..core.request import UPLOAD_ERR_NO_FILE, UPLOAD_ERR_OK
from ..logger import log_error
from ..models import item_category
from ..models.alert import Alert
from ..models.audit_log import AuditLog
from ..models.branch import Branch
from ..models.item_category import ItemCategory
from ..models.ledger import Ledger, LedgerError
from ..models.ledger_file import LedgerFile
from ..models.member import Member
from ..models.sale import Sale
from ..models.user import User
from ..util import (is_digits, is_empty, is_numeric, mb_convert_kana_n, now_str, parse_date, php_round,
                    strtotime, to_int, today_str, trim)

# 必須項目
REQUIRED_FIELDS = ('transaction_date', 'transaction_type', 'item_category', 'item_name', 'quantity',
                   'transaction_amount', 'counterpart_name', 'counterpart_address')

DOC_TYPES = ('driver_license', 'my_number', 'passport', 'health_insurance',
             'residence_card', 'residence_status', 'special_permanent', 'other')

TRANSACTION_TYPES = {'buy': '買取', 'exchange': '交換', 'consignment': '委託販売受け', 'other': 'その他'}

FIELD_LABELS = {
    'transaction_date': '取引年月日', 'transaction_type': '取引種別', 'item_category': '古物区分',
    'item_name': '品名', 'quantity': '数量', 'transaction_amount': '取引金額', 'counterpart_name': '相手方氏名',
    'counterpart_address': '相手方住所', 'counterpart_occupation': '相手方職業', 'counterpart_age': '相手方年齢',
    'id_document_type': '本人確認書類種別', 'id_document_number': '本人確認書類番号',
    'transaction_type_note': '取引種別の補足', 'item_category_note': '古物区分の補足',
    'counterpart_phone': '相手方電話番号', 'counterpart_contact_name': '担当者名',
    'id_document_type_note': '確認書類の内容', 'sale_price': '販売予定価格',
}

MAX_LENGTHS = (
    ('transaction_type_note', 255), ('item_category_note', 255), ('item_name', 255), ('counterpart_name', 255),
    ('counterpart_address', 512), ('counterpart_occupation', 255), ('counterpart_phone', 20),
    ('counterpart_contact_name', 255), ('id_document_number', 64), ('id_document_type_note', 255),
)

PHOTO_MAX_SIZE = 26214400  # 商品画像1点あたりの上限（25MB）
PHOTO_MAX_COUNT = 20       # 商品画像の最大点数
PHOTO_MIMES = ('image/jpeg', 'image/png', 'image/gif', 'image/webp')


def _label(field):
    return FIELD_LABELS.get(field, field)


def _blank(v):
    """値が無い・空白だけ（PHP の empty($v) || trim($v) === ''）"""
    return is_empty(v) or trim(str(v)) == ''


def sanitize_for_log(data):
    """監査ログ用に機密情報を除いたデータ（本人確認書類番号は記録しない）"""
    safe = dict(data)
    if safe.get('id_document_number') is not None:
        safe['id_document_number'] = '***'
    for k in ('_csrf_token', 'password', 'confirm_password'):
        safe.pop(k, None)
    return safe


class LedgerController(BaseController):
    # ------------------------------------------------------------------
    # 一覧
    # ------------------------------------------------------------------
    def index(self):
        self.auth.require_login()
        tenant_id = self.auth.tenant_id()

        def g(key):
            # 検索条件は文字列のみ受け付ける（配列が送られた場合は条件なし）
            v = self.request.get(key)
            return v if isinstance(v, str) else None

        filters = {
            'date_from': g('date_from'), 'date_to': g('date_to'), 'item_category': g('item_category'),
            'transaction_type': g('transaction_type'), 'item_name': g('item_name'),
            'counterpart_name': g('counterpart_name'), 'serial_number': g('serial_number'),
            'approval_status': g('approval'),
            'registered_by_id': g('registered_by') if g('registered_by') is not None else g('registered_by_id'),
            'branch_id': g('branch_id'), 'fiscal_year': g('fiscal_year'),
        }
        page = max(1, self.get_int('p') if self.request.get('p') is not None else 1)
        per_page = 50
        model = Ledger(self.db)
        result = model.find_all(tenant_id, filters, page, per_page)
        total = result['total']
        search = dict(filters)
        search['registered_by'] = filters['registered_by_id']
        self.render('ledger/index', {
            'ledgers': result['records'], 'total': total, 'search': search, 'currentPage': page,
            'totalPages': int(math.ceil(total / per_page)) if total > 0 else 1, 'perPage': per_page,
            'branches': Branch(self.db).find_all_by_tenant(tenant_id), 'years': model.get_years(tenant_id),
            'users': User(self.db).get_by_tenant(tenant_id),
            'itemTypes': ItemCategory(self.db).build_options(tenant_id),
            'transactionTypes': TRANSACTION_TYPES,
            'approvalMode': self.request.get('approval') == 'pending',
        })

    # ------------------------------------------------------------------
    # 登録
    # ------------------------------------------------------------------
    def _form(self, ledger, errors, data=None, photo_count=None):
        tenant_id = self.auth.tenant_id()
        values = {
            'ledger': ledger,
            'branches': Branch(self.db).find_all_by_tenant(tenant_id),
            'categoryOptions': ItemCategory(self.db).build_options(tenant_id),
            'errors': errors,
        }
        if data is not None:
            values['input'] = data
        if photo_count is not None:
            values['itemPhotoCount'] = photo_count
        self.render('ledger/form', values)

    def create(self):
        """登録画面（取引年月日は今日、拠点はログイン中の利用者の所属拠点。拠点が1つだけならその拠点）"""
        self.auth.require_login()
        branches = Branch(self.db).find_all_by_tenant(self.auth.tenant_id())
        default_branch = (self.auth.user() or {}).get('branch_id')
        if is_empty(default_branch) and len(branches) == 1:
            default_branch = int(branches[0]['id'])
        self._form(None, {}, {
            'transaction_date': today_str(),
            'branch_id': str(default_branch) if default_branch is not None else '',
        })

    def store(self):
        """登録（入力確認 → 保存 → 添付ファイル → 承認判定 → 重複検知 → 監査ログ）"""
        self.auth.require_login()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.auth.user_id()
        data = self.request.all()

        # 拠点はフォームの値を優先し、無ければログイン中の利用者の所属拠点
        if is_empty(data.get('branch_id')):
            data['branch_id'] = (self.auth.user() or {}).get('branch_id')
        if is_empty(data.get('branch_id')):
            self._form(None, {'general': '拠点が設定されていません。フォームで拠点を選択するか、'
                                         '管理者に連絡して拠点を割り当ててもらってください。'}, data)
        # 他テナントの拠点への不正な紐付けを防ぐ
        if not self._branch_belongs(to_int(data['branch_id']), tenant_id):
            self.forbidden('無効な拠点が指定されました。')

        errors = self._validate(data)
        if errors:
            self._form(None, errors, data)

        data['registered_by'] = user_id
        model = Ledger(self.db)
        try:
            new_id = model.create(tenant_id, data)
        except DBError as e:
            # DB のエラー内容（SQL 文など）は画面に出さず、入力内容を残したまま再表示する
            log_error('LedgerController.store failed: %s' % e)
            self._form(None, {'general': '台帳を登録できませんでした。入力内容（文字数・数値の範囲など）を確認してください。'}, data)

        success = ['台帳 #%d「%s」を登録しました。' % (new_id, data['item_name'])]

        # 相手方情報から会員を同時に登録する（チェックボックスON時）
        if not is_empty(self.request.post('register_member')):
            members = Member(self.db)
            code = trim(str(data.get('member_code') or ''))
            if code != '' and members.exists_code(tenant_id, code):
                success.append('会員番号「%s」は既に登録済みのため、会員の新規登録はスキップしました。' % code)
            else:
                if code == '':
                    code = members.generate_code(tenant_id)
                try:
                    members.create(tenant_id, {
                        'member_code': code,
                        'counterpart_type': data.get('counterpart_type') or 'individual',
                        'name': data.get('counterpart_name') or '',
                        'address': data.get('counterpart_address') or '',
                        'occupation': data.get('counterpart_occupation') or '',
                        'age': data.get('counterpart_age') or '',
                        'phone': data.get('counterpart_phone') or '',
                        'contact_name': data.get('counterpart_contact_name') or '',
                        'account': data.get('counterpart_account') or '',
                        'id_document_type': data.get('id_document_type') or '',
                        'id_document_number': data.get('id_document_number') or '',
                        'note': data.get('counterpart_note') or '',
                    })
                    # 台帳にも会員番号を反映する（承認判定・引用に使えるように）
                    self.db.execute("UPDATE `ledgers` SET `member_code` = ? WHERE `id` = ? AND `tenant_id` = ?",
                                    (code, new_id, tenant_id))
                    data['member_code'] = code
                    success.append('相手方情報から会員「%s」を新規登録しました。' % code)
                except DBError as e:
                    log_error('LedgerController.store member create failed: %s' % e)
                    success.append('会員の新規登録はできませんでした（会員番号「%s」が既に使われている可能性があります）。'
                                   '会員管理から登録してください。' % code)

        # 添付ファイル（本人確認書類が実際に保存できたかで承認判定するため、判定より先に保存する）
        file_errors = {}
        self._save_uploaded_files(new_id, tenant_id, file_errors)
        messages = []
        if file_errors:
            messages.append('台帳は登録されましたが、添付ファイルの保存に失敗しました: ' + ' / '.join(file_errors.values()))

        # 本人確認情報が未登録の場合（登録自体は許可）
        has_id_file = LedgerFile(self.db).count_by_ledger_and_type(new_id, tenant_id, 'id_document') > 0
        if is_empty(data.get('id_document_type')) and not has_id_file:
            # 会員番号が紐付いていて、その会員に本人確認情報が登録されていれば「認証済み」とみなす
            verified = False
            if not is_empty(data.get('member_code')):
                m = Member(self.db).find_by_code(tenant_id, str(data['member_code']))
                verified = m is not None and not is_empty(m.get('id_document_type'))
            if not verified:
                # 本人確認スキップ + 未認証の相手 → 管理者の承認待ち
                self.db.execute("UPDATE `ledgers` SET `approval_status` = 'pending' WHERE `id` = ? AND `tenant_id` = ?",
                                (new_id, tenant_id))
                messages.append('⚠ 本人確認情報が未登録かつ相手方が未認証（本人確認済み会員に紐付いていない）のため、'
                                'この台帳は管理者の承認待ちになりました。管理者が内容を確認して承認します。')
            else:
                messages.append('⚠ この台帳は本人確認情報が未登録です（本人確認済みの会員に紐付いているため承認は不要です）。'
                                '必要に応じて編集画面から登録してください。')
        # 複数の警告があっても消えないよう、まとめて1件にする
        if messages:
            self.flash('error', ' ／ '.join(messages))

        # 重複検知アラート（ファイル保存後に実行して保存日時を参照できるようにする）
        Alert(self.db).detect_duplicates(tenant_id, new_id)
        AuditLog(self.db).log(tenant_id, user_id, self.user_name(), None, 'create', new_id, None,
                              sanitize_for_log(data), self.request.ip())
        self.flash('success', ' '.join(success))
        self.redirect('/index.cgi?page=ledger')

    # ------------------------------------------------------------------
    # 承認
    # ------------------------------------------------------------------
    def approve(self):
        """承認待ち台帳（本人確認スキップ + 未認証の相手）を、管理者が内容確認のうえ承認する"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        ledger_id = self.post_int('id')
        record = Ledger(self.db).find_by_id(ledger_id, tenant_id)
        if record is None:
            self.not_found('台帳が見つかりません。')
        if (record.get('approval_status') or 'none') != 'pending':
            self.flash('error', 'この台帳は承認待ちではありません。')
            self.redirect('/index.cgi?page=ledger.show&id=%d' % ledger_id)
        self.db.execute(
            """UPDATE `ledgers`
             SET `approval_status` = 'approved', `approved_by` = ?, `approved_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?""", (self.auth.user_id(), ledger_id, tenant_id))
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', ledger_id,
                              {'approval_status': 'pending'},
                              {'approval_status': 'approved', 'action': 'ledger_approved'}, self.request.ip())
        self.flash('success', '台帳 #%d を承認しました。' % ledger_id)
        self.redirect('/index.cgi?page=ledger.show&id=%d' % ledger_id)

    # ------------------------------------------------------------------
    # 販売記録（在庫管理）
    # ------------------------------------------------------------------
    def _post_str(self, key, default=''):
        v = self.request.post(key, default)
        return trim(v) if isinstance(v, str) else default

    def _parse_sold_at(self, value, redirect_to):
        """datetime-local（YYYY-MM-DDTHH:MM）などを 'YYYY-MM-DD HH:MM:SS' にする"""
        dt = strtotime(value.replace('T', ' '))
        if dt is None:
            self.flash('error', '販売日時の形式が不正です。')
            self.redirect(redirect_to)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    def sale_store(self):
        self.auth.require_login()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        ledger_id = self.post_int('id')
        record = Ledger(self.db).find_by_id(ledger_id, tenant_id)
        if record is None:
            self.not_found('台帳が見つかりません。')
        quantity = to_int(self._post_str('quantity', '1'))
        sale_amount = self._post_str('sale_amount')
        sold_at = self._post_str('sold_at')
        note = self._post_str('note')
        member_code = self._post_str('member_code')
        back = '/index.cgi?page=ledger.show&id=%d' % ledger_id

        if member_code != '' and Member(self.db).find_by_code(tenant_id, member_code) is None:
            self.flash('error', '会員番号「%s」は登録されていません。先に会員管理から登録してください。' % member_code)
            self.redirect(back)
        if quantity < 1:
            self.flash('error', '販売個数は1以上で入力してください。')
            self.redirect(back)
        sales = Sale(self.db)
        remaining = int(record['quantity']) - sales.sold_quantity(ledger_id, tenant_id)
        if quantity > remaining:
            self.flash('error', '販売個数が残在庫（%d点）を超えています。' % remaining)
            self.redirect(back)
        if sale_amount != '' and (not is_digits(sale_amount) or len(sale_amount) > 12):
            self.flash('error', '販売金額は数値（円）で入力してください。')
            self.redirect(back)
        sold_at = now_str() if sold_at == '' else self._parse_sold_at(sold_at, back)
        if len(note) > 512:
            self.flash('error', '備考は512文字以内で入力してください。')
            self.redirect(back)

        # 同時に別の端末（POS 等）で販売されても在庫を超えないよう、台帳行をロックして最新の残数で確認する
        # （列を補う DDL は暗黙のコミットを伴うため、トランザクション開始前に済ませる）
        sales.ensure_schema()
        self.db.begin()
        try:
            locked = sales.lock_ledgers([ledger_id], tenant_id)
            st = locked.get(ledger_id)
            remaining_now = st['quantity'] - st['sold'] if st else None
            if remaining_now is None or quantity > remaining_now:
                self.db.rollback()
                self.flash('error', '販売個数が残在庫（%d点）を超えています。' % max(0, remaining_now or 0))
                self.redirect(back)
            sale_id = sales.create(tenant_id, {
                'ledger_id': ledger_id, 'member_code': member_code, 'quantity': quantity,
                'sale_amount': sale_amount, 'sold_at': sold_at, 'note': note, 'created_by': self.auth.user_id(),
            })
            self.db.commit()
        except ResponseDone:
            raise
        except Exception as e:
            if self.db.in_transaction:
                self.db.rollback()
            log_error('sale_store failed: %s' % e)
            self.flash('error', '販売記録の登録に失敗しました。もう一度お試しください。')
            self.redirect(back)

        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'create', sale_id, None,
                              {'kind': 'sale', 'ledger_id': ledger_id, 'quantity': quantity,
                               'sale_amount': sale_amount}, self.request.ip())
        new_remaining = remaining_now - quantity
        self.flash('success', '販売記録を追加しました。（残在庫: %d点%s）' % (new_remaining, '・売切' if new_remaining == 0 else ''))
        self.redirect(back)

    def _redirect_if_pos_sale(self, sale):
        """POS レジの会計に含まれる販売記録は個別に修正・削除させず、取引詳細へ案内する"""
        if is_empty(sale.get('transaction_id')):
            return
        self.flash('error', 'この販売記録はPOSレジの会計に含まれるため、個別に修正・削除できません。'
                            'POSの取引詳細から「取消」して会計し直してください。')
        self.redirect('/index.cgi?page=pos.show&id=%d' % to_int(sale['transaction_id']))

    def sale_edit(self):
        """販売記録の修正画面（管理者のみ）"""
        self.auth.require_admin_role()
        tenant_id = self.auth.tenant_id()
        sales = Sale(self.db)
        sale = sales.find_by_id(self.get_int('sale_id'), tenant_id)
        if sale is None:
            self.not_found('販売記録が見つかりません。')
        self._redirect_if_pos_sale(sale)
        record = Ledger(self.db).find_by_id(int(sale['ledger_id']), tenant_id)
        if record is None:
            self.not_found('台帳が見つかりません。')
        # この販売を除いた販売済数（数量の上限）
        sold_other = sales.sold_quantity(int(sale['ledger_id']), tenant_id) - int(sale['quantity'])
        self.render('sale/form', {'sale': sale, 'record': record,
                                  'maxQty': max(1, int(record['quantity']) - sold_other)})

    def sale_update(self):
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        sale_id = self.post_int('sale_id')
        sales = Sale(self.db)
        sale = sales.find_by_id(sale_id, tenant_id)
        if sale is None:
            self.not_found('販売記録が見つかりません。')
        self._redirect_if_pos_sale(sale)
        ledger_id = int(sale['ledger_id'])
        record = Ledger(self.db).find_by_id(ledger_id, tenant_id)
        back = '/index.cgi?page=ledger.show&id=%d' % ledger_id
        quantity = to_int(self._post_str('quantity', '1'))
        sale_amount = self._post_str('sale_amount')
        sold_at = self._post_str('sold_at')
        note = self._post_str('note')
        member_code = self._post_str('member_code')

        if quantity < 1:
            self.flash('error', '販売個数は1以上で入力してください。')
            self.redirect(back)
        if record is None:
            self.not_found('台帳が見つかりません。')
        if sale_amount != '' and (not is_digits(sale_amount) or len(sale_amount) > 12):
            self.flash('error', '販売金額は数値（円）で入力してください。')
            self.redirect(back)
        if member_code != '' and Member(self.db).find_by_code(tenant_id, member_code) is None:
            self.flash('error', '会員番号「%s」は登録されていません。' % member_code)
            self.redirect(back)
        sold_at = sale['sold_at'] if sold_at == '' else self._parse_sold_at(sold_at, back)
        if len(note) > 512:
            self.flash('error', '備考は512文字以内で入力してください。')
            self.redirect(back)

        # 残数の確認と更新は、台帳行をロックしたトランザクション内で行う
        sales.ensure_schema()
        self.db.begin()
        try:
            locked = sales.lock_ledgers([ledger_id], tenant_id)
            sale_now = sales.find_by_id(sale_id, tenant_id)  # ロック後の最新の値
            if ledger_id not in locked or sale_now is None:
                self.db.rollback()
                self.not_found('販売記録が見つかりません。')
            sold_other = locked[ledger_id]['sold'] - int(sale_now['quantity'])
            max_qty = locked[ledger_id]['quantity'] - sold_other
            if quantity > max_qty:
                self.db.rollback()
                self.flash('error', '販売個数が在庫（この記録分を除き残%d点）を超えています。' % max(0, max_qty))
                self.redirect(back)
            sales.update(sale_id, tenant_id, {'member_code': member_code, 'quantity': quantity,
                                              'sale_amount': sale_amount, 'sold_at': sold_at, 'note': note})
            self.db.commit()
        except ResponseDone:
            raise
        except Exception as e:
            if self.db.in_transaction:
                self.db.rollback()
            log_error('sale_update failed: %s' % e)
            self.flash('error', '販売記録の修正に失敗しました。もう一度お試しください。')
            self.redirect(back)

        before = sale_now or sale
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'edit', sale_id,
                              {'kind': 'sale', 'quantity': before['quantity'], 'sale_amount': before['sale_amount'],
                               'sold_at': before['sold_at'], 'member_code': before.get('member_code')},
                              {'kind': 'sale', 'quantity': quantity, 'sale_amount': sale_amount,
                               'sold_at': sold_at, 'member_code': member_code}, self.request.ip())
        self.flash('success', '販売記録を修正しました。（在庫数に反映されます）')
        self.redirect(back)

    def sale_delete(self):
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        sale_id = self.post_int('sale_id')
        sales = Sale(self.db)
        sale = sales.find_by_id(sale_id, tenant_id)
        if sale is None:
            self.not_found('販売記録が見つかりません。')
        self._redirect_if_pos_sale(sale)
        sales.delete(sale_id, tenant_id)
        AuditLog(self.db).log(tenant_id, self.auth.user_id(), self.user_name(), None, 'delete', sale_id,
                              {'kind': 'sale', 'ledger_id': sale['ledger_id'], 'quantity': sale['quantity'],
                               'sale_amount': sale['sale_amount']}, None, self.request.ip())
        self.flash('success', '販売記録を削除しました。（在庫数に反映されます）')
        self.redirect('/index.cgi?page=ledger.show&id=%d' % int(sale['ledger_id']))

    # ------------------------------------------------------------------
    # 詳細・編集・削除
    # ------------------------------------------------------------------
    def show(self):
        self.auth.require_login()
        tenant_id = self.auth.tenant_id()
        ledger_id = self.get_int('id')
        model = Ledger(self.db)
        record = model.find_by_id(ledger_id, tenant_id)
        if record is None:
            self.not_found('台帳が見つかりません。')
        # 過去年度の台帳は編集できないため、編集ボタン自体を出さない
        is_current_year = int(record['fiscal_year']) == model.get_fiscal_year(today_str())
        is_admin = self.auth.is_admin()
        can_edit = is_current_year and (is_admin or int(record['registered_by'] or 0) == self.auth.user_id())
        sales = Sale(self.db)
        sold = sales.sold_quantity(ledger_id, tenant_id)
        self.render('ledger/show', {
            'ledger': record, 'record': record, 'canEdit': can_edit, 'isAdmin': is_admin,
            'itemTypeLabels': item_category.STATUTORY,
            'itemPhotos': LedgerFile(self.db).find_all_by_ledger_and_type(ledger_id, tenant_id, 'item_photo'),
            'sales': sales.find_by_ledger(ledger_id, tenant_id),
            'soldQuantity': sold,
            'remaining': max(0, int(record['quantity']) - sold),
        })

    def edit(self):
        self.auth.require_login()
        tenant_id = self.auth.tenant_id()
        ledger_id = self.get_int('id')
        model = Ledger(self.db)
        record = model.find_by_id(ledger_id, tenant_id)
        if record is None:
            self.not_found('台帳が見つかりません。')
        # 一般ユーザーは自分が登録したものだけ編集できる
        if self.auth.role() != 'admin' and int(record['registered_by'] or 0) != self.auth.user_id():
            self.forbidden('自分が登録したレコードのみ編集できます。')
        if int(record['fiscal_year']) != model.get_fiscal_year(today_str()):
            self.forbidden('過去年度のデータは編集できません。')
        self._form(record, {}, None,
                   LedgerFile(self.db).count_by_ledger_and_type(ledger_id, tenant_id, 'item_photo'))

    def update(self):
        """更新（入力確認 → 更新 → 添付ファイル → 承認待ちの解除 → 監査ログ（変更前後））"""
        self.auth.require_login()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.auth.user_id()
        role = self.auth.role()
        # フォームの hidden の id を優先し、無ければ送信先 URL の id
        ledger_id = self.post_int('id') or self.get_int('id')
        data = self.request.all()
        if not is_empty(data.get('branch_id')) and not self._branch_belongs(to_int(data['branch_id']), tenant_id):
            self.forbidden('無効な拠点が指定されました。')

        model = Ledger(self.db)
        files = LedgerFile(self.db)
        errors = self._validate(data)
        if errors:
            record = model.find_by_id(ledger_id, tenant_id)
            if record is None:
                # 対象が無いまま再表示すると新規登録として保存されてしまうため 404
                self.not_found('台帳が見つかりません。')
            self._form(record, errors, data, files.count_by_ledger_and_type(ledger_id, tenant_id, 'item_photo'))

        before = model.find_by_id(ledger_id, tenant_id)
        if before is None:
            self.not_found('台帳が見つかりません。')
        try:
            model.update(ledger_id, tenant_id, user_id, role, data)
        except DBError as e:
            log_error('LedgerController.update failed: %s' % e)
            msg = ('他の操作（会計・販売登録など）と重なったため保存できませんでした。もう一度「保存」してください。'
                   if e.code in (ER_LOCK_WAIT_TIMEOUT, ER_LOCK_DEADLOCK)
                   else '台帳を保存できませんでした。入力内容（文字数・数値の範囲など）を確認してください。')
            self._form(before, {'general': msg}, data,
                       files.count_by_ledger_and_type(ledger_id, tenant_id, 'item_photo'))
        except LedgerError as e:
            self.forbidden(str(e))

        file_errors = {}
        self._save_uploaded_files(ledger_id, tenant_id, file_errors)
        if file_errors:
            self.flash('error', '台帳は更新されましたが、添付ファイルの保存に失敗しました: ' + ' / '.join(file_errors.values()))

        # 承認待ちの台帳に、本人確認情報（書類種別・書類の画像）を追加した場合や
        # 本人確認済みの会員に紐付けた場合は、承認待ちを解除する
        cleared = False
        if (before.get('approval_status') or 'none') == 'pending':
            has_id = not is_empty(data.get('id_document_type')) or \
                files.count_by_ledger_and_type(ledger_id, tenant_id, 'id_document') > 0
            if not has_id and not is_empty(data.get('member_code')):
                m = Member(self.db).find_by_code(tenant_id, str(data['member_code']))
                has_id = m is not None and not is_empty(m.get('id_document_type'))
            if has_id:
                self.db.execute(
                    "UPDATE `ledgers` SET `approval_status` = 'none' WHERE `id` = ? AND `tenant_id` = ? AND `approval_status` = 'pending'",
                    (ledger_id, tenant_id))
                cleared = True

        AuditLog(self.db).log(tenant_id, user_id, self.user_name(), None, 'edit', ledger_id,
                              sanitize_for_log(before), sanitize_for_log(data), self.request.ip())
        self.flash('success', '台帳 #%d の変更を保存しました。%s'
                   % (ledger_id, '本人確認情報が登録されたため、承認待ちを解除しました。' if cleared else ''))
        self.redirect('/index.cgi?page=ledger.show&id=%d' % ledger_id)

    def delete(self):
        """削除（管理者のみ・パスワードの再入力で確認してから論理削除）"""
        self.auth.require_admin_role()
        self.verify_csrf()
        tenant_id = self.auth.tenant_id()
        user_id = self.auth.user_id()
        ledger_id = self.post_int('id')
        if not self.auth.verify_current_password(self.request.raw_post('confirm_password')):
            self.flash('error', 'パスワードが正しくありません。')
            self.redirect('/index.cgi?page=ledger.show&id=%d' % ledger_id)
        model = Ledger(self.db)
        before = model.find_by_id(ledger_id, tenant_id)
        if before is None:
            self.not_found('台帳が見つかりません。')
        try:
            model.soft_delete(ledger_id, tenant_id, user_id)
        except LedgerError as e:
            self.not_found(str(e))
        AuditLog(self.db).log(tenant_id, user_id, self.user_name(), None, 'delete', ledger_id,
                              sanitize_for_log(before), None, self.request.ip())
        self.flash('success', '台帳 #%d「%s」を削除しました。（監査ログに削除前の内容が記録されています）'
                   % (ledger_id, before['item_name']))
        self.redirect('/index.cgi?page=ledger')

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------
    def _branch_belongs(self, branch_id, tenant_id):
        return int(self.db.value("SELECT COUNT(*) FROM `branches` WHERE `id` = ? AND `tenant_id` = ?",
                                 (branch_id, tenant_id)) or 0) > 0

    def _validate(self, data):
        """入力の確認（data は表示・保存用に整える）。エラーの辞書を返す"""
        errors = {}
        # 台帳の項目はすべて1つの値。配列などが送られた場合は不正な入力
        for key in list(data.keys()):
            if isinstance(data[key], dict):
                errors[key] = '入力値の形式が不正です。'
                errors['general'] = '入力値の形式が不正です。もう一度入力してください。'
                data[key] = ''
        for field in REQUIRED_FIELDS:
            if data.get(field) is None or data.get(field) == '':
                errors[field] = _label(field) + ' は必須です。'
        if is_empty(errors.get('transaction_type')) and data.get('transaction_type') is not None \
                and data['transaction_type'] not in TRANSACTION_TYPES:
            errors['transaction_type'] = '取引種別の値が無効です。'

        if is_empty(errors.get('quantity')) and data.get('quantity') is not None:
            q = str(data['quantity'])
            if not is_digits(q) or int(q) <= 0:
                errors['quantity'] = '数量は正の整数で入力してください。'
            elif len(q.lstrip('0')) > 9:  # DB の列（INT UNSIGNED）に収まる範囲
                errors['quantity'] = '数量は999,999,999以下で入力してください。'

        if is_empty(errors.get('transaction_amount')) and data.get('transaction_amount') is not None:
            a = data['transaction_amount']
            if not is_numeric(a) or float(a) <= 0:
                errors['transaction_amount'] = '取引金額は正の数値で入力してください。'
            elif php_round(float(a)) >= 1e12:  # DB の列（DECIMAL(12,0)）に収まる範囲（小数は丸め後で判定）
                errors['transaction_amount'] = '取引金額は999,999,999,999円以下で入力してください。'

        cp_type = data.get('counterpart_type') if data.get('counterpart_type') is not None else 'individual'
        if cp_type not in ('individual', 'corporate'):
            errors['counterpart_type'] = '相手方区分の値が不正です。'
            cp_type = 'individual'
        if cp_type == 'corporate':
            if _blank(data.get('counterpart_contact_name')):
                errors['counterpart_contact_name'] = '法人の場合は担当者名が必須です。'
        else:
            # 個人: 職業・年齢が必須（古物営業法上の記録事項）
            if _blank(data.get('counterpart_occupation')):
                errors['counterpart_occupation'] = '相手方職業 は必須です。'
            if data.get('counterpart_age') is None or data.get('counterpart_age') == '':
                errors['counterpart_age'] = '相手方年齢 は必須です。'
        age = data.get('counterpart_age')
        if is_empty(errors.get('counterpart_age')) and age is not None and age != '':
            if not is_digits(str(age)) or int(age) <= 0:
                errors['counterpart_age'] = '相手方年齢は正の整数で入力してください。'
            elif int(age) > 150:
                errors['counterpart_age'] = '相手方年齢は150以下で入力してください。'

        # マイナンバーカードの個人番号は法令上記録できないため捨てる（「未登録」の場合も捨てる）
        if (data.get('id_document_type') or '') in ('my_number', ''):
            data['id_document_number'] = ''
        # 本人確認書類種別は、書類の種別か「未登録（本人確認をスキップ）」を明示的に選ぶ
        if data.get('id_document_type') == '__unset':
            errors['id_document_type'] = ('確認書類種別を選択してください'
                                          '（本人確認をしない場合は「未登録（本人確認をスキップ）」を選択）。')
        elif not is_empty(data.get('id_document_type')) and data['id_document_type'] not in DOC_TYPES:
            errors['id_document_type'] = '本人確認書類種別の値が不正です。'
        # 「その他」は書類の内容（例: 社員証）を記録する（確認方法の記録のため必須）
        if data.get('id_document_type') == 'other' and trim(str(data.get('id_document_type_note') or '')) == '':
            errors['id_document_type_note'] = '確認書類種別で「その他」を選択した場合は、書類の内容を入力してください。'

        # 販売予定価格（任意・POSレジの単価の初期値）
        if data.get('sale_price') is not None and data.get('sale_price') != '':
            sp = mb_convert_kana_n(str(data['sale_price'])).replace(',', '').replace('，', '')
            if not is_digits(sp):
                errors['sale_price'] = '販売予定価格は0以上の整数（円）で入力してください。'
            elif len(sp.lstrip('0')) > 12:
                errors['sale_price'] = '販売予定価格は999,999,999,999円以下で入力してください。'
            else:
                data['sale_price'] = str(int(sp))

        # 文字数の上限（DB の列長）
        for field, mx in MAX_LENGTHS:
            v = data.get(field)
            if is_empty(errors.get(field)) and isinstance(v, str) and len(v) > mx:
                errors[field] = '%sは%d文字以内で入力してください。' % (_label(field), mx)
        for field, label in (('item_description', '品目の説明'), ('counterpart_note', '相手方の備考')):
            v = data.get(field)
            if isinstance(v, str) and len(v.encode('utf-8')) > 65535:
                errors[field] = label + 'が長すぎます（全角で約2万文字まで）。'
        if not is_empty(data.get('serial_number')) and len(str(data['serial_number'])) > 100:
            errors['serial_number'] = 'シリアル番号は100文字以内で入力してください。'
        if not is_empty(data.get('member_code')) and len(str(data['member_code'])) > 50:
            errors['member_code'] = '会員番号は50文字以内で入力してください。'
        if not is_empty(data.get('counterpart_account')) and len(str(data['counterpart_account'])) > 255:
            errors['counterpart_account'] = '取引アカウントは255文字以内で入力してください。'

        if is_empty(errors.get('transaction_date')) and data.get('transaction_date') is not None:
            if parse_date(data['transaction_date']) is None:
                errors['transaction_date'] = '取引年月日は YYYY-MM-DD 形式で入力してください。'

        # 古物の種類: このテナントで有効な値か（法定13区分 / 独自区分 / その他）
        if is_empty(errors.get('item_category')) and not is_empty(data.get('item_category')):
            if not ItemCategory(self.db).is_valid_value(self.auth.tenant_id(), str(data['item_category'])):
                errors['item_category'] = '古物区分の値が無効です。'
        if data.get('item_category') == 'other' and _blank(data.get('item_category_note')):
            errors['item_category_note'] = '古物の種類で「その他」を選択した場合は自由記述が必須です。'
        if data.get('transaction_type') == 'other' and _blank(data.get('transaction_type_note')):
            errors['transaction_type_note'] = '取引種別がその他の場合は補足説明が必須です。'
        return errors

    def _save_uploaded_files(self, ledger_id, tenant_id, errors):
        """添付ファイル（本人確認書類・受付表・商品画像）を暗号化して保存する。失敗は errors に追記する"""
        files = LedgerFile(self.db)
        for field, file_type in (('id_document_file', 'id_document'), ('receipt_form_file', 'purchase_receipt')):
            f = self.request.file(field)
            if f is None or f.error == UPLOAD_ERR_NO_FILE:
                continue
            try:
                saved = FileUpload().save(f, tenant_id, ledger_id, file_type)
                files.create(dict(saved, ledger_id=ledger_id, tenant_id=tenant_id, file_type=file_type))
            except UploadError as e:
                errors[field] = str(e)
        self._save_item_photos(ledger_id, tenant_id, errors)

    def _save_item_photos(self, ledger_id, tenant_id, errors):
        """商品画像（item_photos[]。1点25MBまで・台帳あたり20点まで・画像のみ）"""
        photos = self.request.file_list('item_photos')
        if not photos:
            return
        files = LedgerFile(self.db)
        existing = files.count_by_ledger_and_type(ledger_id, tenant_id, 'item_photo')
        saved = 0
        for f in photos:
            if f.error == UPLOAD_ERR_NO_FILE:
                continue
            if existing + saved >= PHOTO_MAX_COUNT:
                errors['item_photos'] = '商品画像は1件の台帳につき最大%d点までです。超過分は保存されませんでした。' % PHOTO_MAX_COUNT
                break
            if f.error != UPLOAD_ERR_OK:
                errors['item_photos'] = '商品画像「%s」のアップロードに失敗しました（サーバーのサイズ上限超過等）。' % f.filename
                continue
            if f.size > PHOTO_MAX_SIZE:
                errors['item_photos'] = '商品画像「%s」は25MBを超えているため保存されませんでした。' % f.filename
                continue
            if detect_mime(f.path) not in PHOTO_MIMES:
                errors['item_photos'] = '商品画像「%s」は対応していない形式です（JPEG/PNG/GIF/WebPのみ）。' % f.filename
                continue
            try:
                stored = FileUpload().save(f, tenant_id, ledger_id, 'item_photo')
                files.create(dict(stored, ledger_id=ledger_id, tenant_id=tenant_id, file_type='item_photo'))
                saved += 1
            except UploadError as e:
                errors['item_photos'] = '商品画像「%s」: %s' % (f.filename, e)
