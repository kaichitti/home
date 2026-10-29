"""
POSレジ（ログイン必須）

会計の流れ:
  在庫検索 → カート（単価×数量・単品値引）→ 小計値引・消費税 → 支払方法・お預り/お釣り
  → [会計確定] 端末のレシートプリンタ接続を確認
       接続あり : 決済完了 → レシートを印刷
       接続なし : 確認ダイアログ →「許可」で決済完了 → レシートを画面に発行（後から印刷可）

会計1回ごとに pos_transactions（レシート番号・支払・税）と明細のスナップショットを保存し、
明細ごとに sales（販売記録）を作成して在庫を減らす。取消（管理者）は販売記録を削除して在庫を戻す。
"""
import json
import math
import re
import secrets
import time

from ..core.controller import BaseController
from ..core.response import Response, ResponseDone
from ..db import DBError, ER_DUP_ENTRY, ER_LOCK_DEADLOCK, ER_LOCK_WAIT_TIMEOUT
from ..helpers import csv_writer, pos_calculator, rate_limiter, receipt_layout
from ..helpers.pos_calculator import CalcError
from ..logger import log_error
from ..models import ledger_schema, pos_schema
from ..models import pos_setting as pos_setting_mod
from ..models.audit_log import AuditLog
from ..models.branch import Branch
from ..models.member import Member
from ..models.pos_closing import DENOMINATIONS, PosClosing
from ..models.pos_setting import PosSetting
from ..models.pos_transaction import PosTransaction
from ..models.sale import Sale
from ..util import (http_build_query, is_digits, is_empty, like_escape, mb_convert_kana_a, mb_convert_kana_n,
                    now_str, number_format, parse_date, rawurlencode, strip_controls, to_int, today_str, trim)

MAX_LINES = 100

CSV_HEADER = ['会計日時', 'レシート番号', 'レジ番号', '状態', '拠点', '担当者', '支払方法', '会員番号', '会員名', '明細No',
              '台帳ID', '品名', 'シリアル番号', '数量', '単価', '単品値引', '明細金額', '売上計上額', '会計小計', '小計値引',
              '税区分', '税率(%)', '消費税等', '会計合計', 'お預り', 'お釣り', '取消日時', '取消理由']


class StockError(Exception):
    """在庫不足（他の端末で先に販売された等）"""


def int_or_none(v):
    """整数として解釈できる値（整数・数字だけの文字列）なら int、それ以外は None"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r'[0-9]{1,12}', v):
        return int(v)
    if isinstance(v, float) and v == v and math.floor(v) == v and abs(v) < 1e12:
        return int(v)
    return None


def norm_date(value, default):
    value = trim(value) if isinstance(value, str) else ''
    return value if parse_date(value) is not None else default


def register_or_none(v):
    """レジ番号（1〜99）として解釈できれば int、それ以外は None"""
    if (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, str) and is_digits(v)):
        n = int(v)
        return n if 1 <= n <= 99 else None
    return None


def filter_query(f, extra=None):
    """画面の絞り込み条件を URL のクエリに戻す（ページ送り・CSV 出力用）"""
    q = [
        ('date_from', f.get('date_from') or ''),
        ('date_to', f.get('date_to') or ''),
        ('status', f.get('status') or ''),
        ('payment_method', f.get('payment_method') or ''),
        ('receipt_no', f.get('receipt_no') or ''),
        ('member', f.get('member') or ''),
        ('member_id', int(f['member_id']) if not is_empty(f.get('member_id')) else ''),
        ('cashier', f.get('cashier') or ''),
        ('keyword', f.get('keyword') or ''),
        ('ledger_id', int(f['ledger_id']) if not is_empty(f.get('ledger_id')) else ''),
        ('register', f.get('register_no') if f.get('register_no') is not None else ''),
        ('branch', f.get('branch_id') if f.get('branch_id') is not None else ''),
    ]
    out = {k: v for k, v in q if v != '' and v is not None}
    for k, v in (extra or {}).items():
        out.setdefault(k, v)
    return http_build_query(out)


def normalize_receipt_no(value, today):
    """
    入力・読み取ったレシート番号を正規化する（できなければ None）
      「20261023-0001」… そのまま / 「202610230001」… バーコード（ハイフンなし）/「1」「0001」… 本日の連番
    """
    v = mb_convert_kana_a(trim(value))
    for a, b in (('ー', '-'), ('－', '-'), ('―', '-'), ('‐', '-'), (' ', ''), ('No.', ''), ('NO.', ''),
                 ('no.', ''), ('#', '')):
        v = v.replace(a, b)
    m = re.fullmatch(r'([0-9]{8})-?([0-9]{4,6})', v)
    if m:
        y = int(m.group(1)[:4])
        if 2000 <= y <= 2100 and parse_date('%s-%s-%s' % (m.group(1)[:4], m.group(1)[4:6], m.group(1)[6:])):
            return m.group(1) + '-' + m.group(2)
        return None
    if re.fullmatch(r'[0-9]{1,6}', v) and int(v) > 0:
        return today.replace('-', '') + '-%04d' % int(v)
    return None


def _num(v):
    """金額・枚数の入力（全角数字・カンマ・円記号・空白を許す）。空欄は 0、不正なら None"""
    if not isinstance(v, str):
        v = ''
    v = mb_convert_kana_n(v)
    for ch in (',', '，', '¥', '￥', '\\', ' ', '　'):
        v = v.replace(ch, '')
    if v == '':
        return 0
    return int(v) if re.fullmatch(r'[0-9]{1,10}', v) else None


def _csv_safe(v):
    """数式として評価されないよう無害化（負の数値はそのまま）"""
    s = '' if v is None else str(v)
    if s != '' and s[0] in ('=', '+', '-', '@', '\t', '\r') and not re.fullmatch(r'-[0-9]+', s):
        return "'" + s
    return s


class PosController(BaseController):
    # ------------------------------------------------------------------
    # 共通
    # ------------------------------------------------------------------
    def _setup(self):
        pos_schema.ensure(self.db)

    def _json(self, data, status=200):
        self.json(data, status, no_store=True)

    def _json_error(self, message, code='error', status=400, extra=None):
        data = {'ok': False, 'code': code, 'error': message}
        if extra:
            data.update(extra)
        self._json(data, status)

    def _require_auth_json(self):
        """JSON API 用の認証確認（未ログイン時はログイン画面へ移動せず 401 を返す。画面側はカートを保持できる）"""
        if not self.auth.is_logged_in():
            self._json_error('ログインの有効期限が切れました。別のタブで再ログインしてから、もう一度お試しください（カートは保存されています）。',
                             'session', 401)
        if self.auth.must_change_password():
            self._json_error('パスワードの変更が必要です。', 'password', 403)

    def _verify_csrf_json(self):
        if not self.request.is_post():
            self._json_error('不正なリクエストです。', 'method', 405)
        token = self.request.raw_post('_csrf_token')
        stored = str(self.session.get('_csrf_token') or '')
        if token == '' or stored == '' or not secrets.compare_digest(stored, token):
            self._json_error('セッションの有効期限が切れたか、不正なリクエストです。ページを再読み込みしてください（カートは保存されています）。',
                             'csrf', 403)

    def _register_filter(self, key='register', post=False):
        return register_or_none(self.request.post(key, '') if post else self.request.get(key, ''))

    def _branch_filter(self):
        b = self.request.get('branch', '')
        return int(b) if isinstance(b, str) and is_digits(b) and int(b) > 0 else None

    def _audit(self, action, target_id, before, after):
        try:
            AuditLog(self.db).log(self.auth.tenant_id(), self.auth.user_id(), self.user_name(), None, action,
                                  target_id, before, after, self.request.ip())
        except Exception as e:
            log_error('audit log failed: %s' % e)

    def _get_s(self, key):
        v = self.request.get(key, '')
        return v if isinstance(v, str) else ''

    def _output_print(self, layout, title):
        """印刷用レイアウトを HTML（ブラウザ印刷・画面表示）または JSON（直結プリンタ）で返す"""
        if self._get_s('format') == 'json':
            self._json({'ok': True, 'title': title, 'layout': layout})
        self.render('pos/print', {
            'printLayout': layout, 'title': title,
            'paper': 58 if self._get_s('w') == '58' else 80,
            'embed': self._get_s('embed') == '1',
        })

    # ------------------------------------------------------------------
    # レジ画面・在庫検索
    # ------------------------------------------------------------------
    def index(self):
        self.auth.require_login()
        self._setup()
        tenant_id = self.auth.tenant_id()
        self.render('pos/index', {
            'settings': PosSetting(self.db).get(tenant_id),
            'posUserKey': 't%du%d' % (tenant_id, self.auth.user_id()),
            'isAdmin': self.auth.is_admin(),
        })

    def search(self):
        """在庫検索（JSON）。q: 品名・シリアル番号・台帳番号 / exact=1: バーコード読取"""
        self._require_auth_json()
        ledger_schema.ensure(self.db)
        # 在庫・シリアル番号の機械的な列挙を防ぐ（1分間に120回まで）
        if not rate_limiter.hit(self.session, 'pos.search', 120, 60):
            self._json({'ok': False, 'items': [], 'error': '短時間に検索が集中しています。しばらく待ってから再度お試しください。'}, 429)
        keyword = trim(self._get_s('q'))[:100]
        exact = self._get_s('exact') == '1'
        items = Sale(self.db).search_in_stock(self.auth.tenant_id(), keyword, 30, exact)
        self._json({'ok': True, 'items': [{
            'ledger_id': int(r['id']),
            'item_name': str(r['item_name']),
            'serial_number': str(r['serial_number'] or ''),
            'remaining': int(r['remaining']),
            'purchase_date': str(r['transaction_date']),
            'pending': (r.get('approval_status') or '') == 'pending',
            # 販売予定価格（台帳に登録されていればカートの単価に自動入力する）
            'sale_price': int(r['sale_price']) if r.get('sale_price') is not None else None,
        } for r in items]})

    # ------------------------------------------------------------------
    # 会計確定
    # ------------------------------------------------------------------
    def checkout(self):
        """
        会計確定（JSON）。POST: _csrf_token, payload（JSON）
          payload = {client_token, items: [{ledger_id, quantity, unit_price, line_discount}],
                     discount: {type, value}, payment: {method, tendered, ref},
                     member_code, note, receipt_mode: print|unprinted, register_no, expected_total}
        """
        self._require_auth_json()
        self._verify_csrf_json()
        self._setup()
        tenant_id = self.auth.tenant_id()
        user_id = self.auth.user_id()
        user = self.auth.user() or {}

        try:
            payload = json.loads(self.request.raw_post('payload'))
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self._json_error('会計データが不正です。ページを再読み込みしてください。')

        # 二重送信防止キー（通信エラー後の再送でも同じ会計が二重に登録されない）
        token = payload.get('client_token', '')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9-]{16,64}', token):
            self._json_error('会計データが不正です（送信キー）。ページを再読み込みしてください。')
        txs = PosTransaction(self.db)
        existing = txs.find_by_token(tenant_id, token)
        if existing is not None:
            self._json(self._checkout_response(existing, True))

        # ---- 明細 ----
        items = payload.get('items')
        if isinstance(items, dict):
            items = list(items.values())
        if not isinstance(items, list) or len(items) == 0:
            self._json_error('カートが空です。')
        if len(items) > MAX_LINES:
            self._json_error('1回の会計で処理できるのは%d明細までです。' % MAX_LINES)
        lines = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                self._json_error('明細の形式が不正です。')
            ledger_id = int_or_none(item.get('ledger_id'))
            qty = int_or_none(item.get('quantity'))
            price = int_or_none(item.get('unit_price'))
            ldisc = int_or_none(item.get('line_discount') if item.get('line_discount') is not None else 0)
            if ledger_id is None or ledger_id <= 0:
                self._json_error('明細%dの商品が不正です。' % (i + 1))
            if qty is None or qty < 1:
                self._json_error('明細%dの数量が不正です。' % (i + 1))
            if price is None:
                self._json_error('明細%dの単価を入力してください（0円の場合は0）。' % (i + 1), 'validation', 400, {'line': i})
            if ldisc is None:
                self._json_error('明細%dの値引額が不正です。' % (i + 1), 'validation', 400, {'line': i})
            lines.append({'ledger_id': ledger_id, 'quantity': qty, 'unit_price': price, 'line_discount': ldisc})

        # ---- その他の入力 ----
        discount_in = payload.get('discount') if isinstance(payload.get('discount'), dict) else {}
        d_type = discount_in.get('type') if discount_in.get('type') in ('none', 'amount', 'percent') else 'none'
        d_value = int_or_none(discount_in.get('value') if discount_in.get('value') is not None else 0)
        if d_value is None:
            self._json_error('値引の入力が不正です。')
        payment_in = payload.get('payment') if isinstance(payload.get('payment'), dict) else {}
        method = payment_in.get('method') if isinstance(payment_in.get('method'), str) else ''
        tendered_raw = payment_in.get('tendered')
        tendered = None if tendered_raw is None or tendered_raw == '' else int_or_none(tendered_raw)
        if tendered_raw is not None and tendered_raw != '' and tendered is None:
            self._json_error('お預り金額は数値（円）で入力してください。')

        def s(v):
            # 前後の空白と制御文字を取り除く（Request の値と同じ扱い）
            return strip_controls(trim(v)) if isinstance(v, str) else ''

        payment_ref = s(payment_in.get('ref'))
        member_code = s(payload.get('member_code'))
        note = s(payload.get('note'))
        receipt_mode = 'unprinted' if payload.get('receipt_mode') == 'unprinted' else 'print'
        # レジ番号（端末の「POS設定・プリンタ」で設定。未設定・不正値は記録しない）
        register_no = register_or_none(payload.get('register_no'))
        expected_total = int_or_none(payload.get('expected_total'))
        if len(payment_ref) > 100:
            self._json_error('承認番号等は100文字以内で入力してください。')
        if len(member_code) > 50:
            self._json_error('会員番号は50文字以内で入力してください。')
        if len(note) > 400:
            self._json_error('備考は400文字以内で入力してください。')
        member = None
        if member_code != '':
            member = Member(self.db).find_by_code(tenant_id, member_code)
            if member is None:
                self._json_error('会員番号「%s」は登録されていません。先に会員管理から登録するか、空欄にしてください。' % member_code,
                                 'member')

        # ---- 商品（台帳）の存在確認と品名のスナップショット ----
        ledger_ids = []
        for l in lines:
            if l['ledger_id'] not in ledger_ids:
                ledger_ids.append(l['ledger_id'])
        rows = self.db.query(
            """SELECT `id`, `item_name`, `serial_number` FROM `ledgers`
             WHERE `tenant_id` = ? AND `deleted_at` IS NULL AND `id` IN (%s)""" % ','.join('?' * len(ledger_ids)),
            [tenant_id] + ledger_ids)
        ledgers = {int(r['id']): r for r in rows}
        for lid in ledger_ids:
            if lid not in ledgers:
                self._json_error('台帳 #%d の商品が見つかりません（削除された可能性があります）。カートから外してください。' % lid, 'stock')

        # ---- 金額計算（サーバー側で計算し直し、画面の合計と一致することを確認） ----
        settings = PosSetting(self.db).get(tenant_id)
        try:
            calc = pos_calculator.calculate(lines, {'type': d_type, 'value': d_value},
                                            {'rate': settings['tax_rate'], 'mode': settings['tax_mode'],
                                             'rounding': settings['tax_rounding']})
        except CalcError as e:
            self._json_error(str(e), 'validation')
        # 画面の合計との一致確認は、お預り金額の確認より先に行う
        if expected_total is None or expected_total != calc['total']:
            self._json_error('画面の合計金額（¥%s）と計算結果（¥%s）が一致しません。消費税の設定が変更された可能性があります。'
                             'ページを再読み込みしてからやり直してください。'
                             % (number_format(expected_total or 0), number_format(calc['total'])),
                             'total_mismatch', 409, {'server_total': calc['total']})
        try:
            pay = pos_calculator.payment(method, calc['total'], tendered)
        except CalcError as e:
            self._json_error(str(e), 'validation')

        requested = {}
        for l in lines:
            requested[l['ledger_id']] = requested.get(l['ledger_id'], 0) + l['quantity']
        store_info = json.dumps({
            'store_name': settings['store_name'], 'store_address': settings['store_address'],
            'store_phone': settings['store_phone'], 'invoice_number': settings['invoice_number'],
            'receipt_header': settings['receipt_header'], 'receipt_footer': settings['receipt_footer'],
        }, ensure_ascii=False, separators=(',', ':')).replace('/', '\\/')

        c = {'tenant_id': tenant_id, 'user_id': user_id, 'user': user, 'token': token, 'lines': lines,
             'ledgers': ledgers, 'calc': calc, 'pay': pay, 'payment_ref': payment_ref, 'member_code': member_code,
             'member': member, 'note': note, 'receipt_mode': receipt_mode, 'requested': requested,
             'store_info': store_info, 'register_no': register_no}

        # 同時実行でデッドロック・ロック待ちタイムアウトになった場合は少し待ってやり直す
        attempt = 1
        while True:
            try:
                tx_id = self._run_checkout(c)
                break
            except StockError as e:
                self._json_error(str(e), 'stock', 409)
            except DBError as e:
                if self.db.in_transaction:
                    self.db.rollback()
                if e.code == ER_DUP_ENTRY and 'uq_pos_tx_token' in e.message:
                    # 同じ送信キーの会計が並行して確定済み → その会計を返す
                    dup = txs.find_by_token(tenant_id, token)
                    if dup is not None:
                        self._json(self._checkout_response(dup, True))
                if e.code in (ER_LOCK_DEADLOCK, ER_LOCK_WAIT_TIMEOUT) and attempt < 3:
                    time.sleep(0.15 * attempt)
                    attempt += 1
                    continue
                log_error('POS checkout failed: %s' % e)
                self._json_error('会計処理に失敗しました。もう一度お試しください。（決済は完了していません）', 'server', 500)
            except ResponseDone:
                raise
            except Exception as e:
                if self.db.in_transaction:
                    self.db.rollback()
                log_error('POS checkout failed: %s' % e)
                self._json_error('会計処理に失敗しました。もう一度お試しください。（決済は完了していません）', 'server', 500)
        tx = txs.find_by_id(tx_id, tenant_id)
        self._json(self._checkout_response(tx or {'id': tx_id}, False))

    def _run_checkout(self, c):
        """会計の登録本体（1トランザクション）。会計 ID を返す（在庫不足は StockError）"""
        db = self.db
        sales = Sale(db)
        txs = PosTransaction(db)
        db.begin()
        # 対象台帳の行を ID 順にロックしてから最新の残数で確認する
        # （トランザクション開始後、このロックより前に通常の SELECT を実行しないこと）
        locked = sales.lock_ledgers(list(c['requested'].keys()), c['tenant_id'])
        for lid in sorted(c['requested']):
            st = locked.get(lid)
            remaining = st['quantity'] - st['sold'] if st else None
            if remaining is None or c['requested'][lid] > remaining:
                db.rollback()
                name = str((c['ledgers'].get(lid) or {}).get('item_name') or '#%d' % lid)
                raise StockError('「%s」の残在庫（%d点）が不足しています（カート内 合計%d点）。'
                                 '他の会計で販売された可能性があります。数量を確認してください。'
                                 % (name, max(0, remaining or 0), c['requested'][lid]))

        now = now_str()
        receipt_no = txs.next_receipt_no(c['tenant_id'], now[:10])
        calc = c['calc']
        user = c['user']
        tx_id = txs.insert({
            'tenant_id': c['tenant_id'],
            'branch_id': int(user['branch_id']) if not is_empty(user.get('branch_id')) else None,
            'register_no': c['register_no'],
            'receipt_no': receipt_no,
            'client_token': c['token'],
            'member_code': c['member_code'],
            'member_id': int(c['member']['id']) if c['member'] is not None else None,
            'member_name': str(c['member']['name']) if c['member'] is not None else '',
            'item_count': calc['item_count'],
            'subtotal': calc['subtotal'],
            'discount_type': calc['discount_type'],
            'discount_value': calc['discount_value'],
            'discount_amount': calc['discount_amount'],
            'tax_mode': calc['tax_mode'],
            'tax_rate': calc['tax_rate'],
            'tax_amount': calc['tax_amount'],
            'total': calc['total'],
            'payment_method': c['pay']['method'],
            'tendered': c['pay']['tendered'],
            'change_amount': c['pay']['change'],
            'payment_ref': '' if c['pay']['method'] == 'cash' else c['payment_ref'],
            'note': c['note'],
            'store_info': c['store_info'],
            'cashier_name': str(user.get('display_name') or ''),
            # プリンタ未接続を「許可」して決済した場合は画面発行（未印刷）として記録する
            'receipt_status': 'unprinted' if c['receipt_mode'] == 'unprinted' else 'pending',
            'created_by': c['user_id'],
            'created_at': now,
        })
        sale_note = '[POS] ' + receipt_no + (' ' + c['note'] if c['note'] != '' else '')
        audit_lines = []
        for i, l in enumerate(c['lines']):
            ledger = c['ledgers'][l['ledger_id']]
            alloc = calc['lines'][i]['allocated']
            sale_id = sales.create(c['tenant_id'], {
                'ledger_id': l['ledger_id'], 'transaction_id': tx_id, 'member_code': c['member_code'],
                'quantity': l['quantity'], 'sale_amount': alloc, 'sold_at': now, 'note': sale_note[:512],
                'created_by': c['user_id'],
            })
            txs.insert_item({
                'transaction_id': tx_id, 'tenant_id': c['tenant_id'], 'ledger_id': l['ledger_id'],
                'sale_id': sale_id, 'line_no': i + 1, 'item_name': str(ledger['item_name']),
                'serial_number': str(ledger.get('serial_number') or ''), 'quantity': l['quantity'],
                'unit_price': l['unit_price'], 'line_discount': l['line_discount'],
                'amount': calc['lines'][i]['amount'], 'allocated_amount': alloc,
            })
            audit_lines.append({'ledger_id': l['ledger_id'], 'sale_id': sale_id, 'quantity': l['quantity'],
                                'amount': alloc})
        AuditLog(db).log(c['tenant_id'], c['user_id'], str(user.get('display_name') or ''), None, 'create', tx_id,
                         None, {
                             'kind': 'pos_transaction', 'receipt_no': receipt_no, 'register_no': c['register_no'],
                             'member_code': c['member_code'] if c['member_code'] != '' else None,
                             'total': calc['total'], 'discount': calc['discount_amount'], 'tax': calc['tax_amount'],
                             'payment_method': c['pay']['method'], 'receipt_mode': c['receipt_mode'],
                             'lines': audit_lines,
                         }, self.request.ip())
        db.commit()
        return tx_id

    def _checkout_response(self, tx, duplicate):
        tx_id = int(tx['id'])
        return {
            'ok': True,
            'duplicate': duplicate,
            'transaction': {
                'id': tx_id,
                'receipt_no': str(tx.get('receipt_no') or ''),
                'register_no': int(tx['register_no']) if tx.get('register_no') is not None else None,
                'member_name': str(tx.get('member_name') or ''),
                'total': to_int(tx.get('total')),
                'tendered': to_int(tx.get('tendered')),
                'change': to_int(tx.get('change_amount')),
                'payment_method': str(tx.get('payment_method') or ''),
                'receipt_status': str(tx.get('receipt_status') or ''),
                'print_count': to_int(tx.get('print_count')),
                'created_at': str(tx.get('created_at') or ''),
            },
            'receipt_url': '/index.cgi?page=pos.receipt&id=%d' % tx_id,
            'show_url': '/index.cgi?page=pos.show&id=%d' % tx_id,
        }

    def printed(self):
        """印刷結果の記録（JSON）。POST: id, doc (receipt|ryoshu), result (printed|failed)"""
        self._require_auth_json()
        self._verify_csrf_json()
        tenant_id = self.auth.tenant_id()
        tx_id = self.post_int('id')
        doc = 'ryoshu' if self.request.post('doc', 'receipt') == 'ryoshu' else 'receipt'
        result = 'printed' if self.request.post('result', '') == 'printed' else 'failed'
        rec = PosTransaction(self.db).record_print(tx_id, tenant_id, doc, result)
        if rec is None:
            self._json_error('取引が見つかりません。', 'not_found', 404)
        # 領収書の発行とレシートの再発行は、不正防止のため監査ログに残す
        is_reprint = doc == 'receipt' and int(rec['before']['print_count']) > 0
        if result == 'printed' and (doc == 'ryoshu' or is_reprint):
            self._audit('export', tx_id, None, {
                'kind': 'pos_print',
                'doc': '領収書' if doc == 'ryoshu' else 'レシート（再発行）',
                'count': int(rec['after']['ryoshu_count']) if doc == 'ryoshu' else int(rec['after']['print_count']),
            })
        self._json({'ok': True, 'receipt_status': rec['after']['receipt_status'],
                    'print_count': int(rec['after']['print_count'])})

    # ------------------------------------------------------------------
    # レシート・領収書
    # ------------------------------------------------------------------
    def receipt(self):
        """レシート / 領収書（HTML or JSON）。GET: id, doc, to（宛名）, tadashi（但し書き）, w, embed, format"""
        self.auth.require_login()
        self._setup()
        tenant_id = self.auth.tenant_id()
        txs = PosTransaction(self.db)
        tx = txs.find_by_id(self.get_int('id'), tenant_id)
        if tx is None:
            if self._get_s('format') == 'json':
                self._json_error('取引が見つかりません。', 'not_found', 404)
            self.not_found('取引が見つかりません。')
        if self._get_s('doc') == 'ryoshu':
            to = self._get_s('to')[:40]
            tadashi = self._get_s('tadashi')[:50]
            if tadashi == '':
                tadashi = PosSetting(self.db).get(tenant_id)['ryoshu_tadashi']
            layout = receipt_layout.ryoshu(tx, to, tadashi, int(tx['ryoshu_count']) > 0)
            self._output_print(layout, '領収書 ' + str(tx['receipt_no']))
        items = txs.items(int(tx['id']), tenant_id)
        layout = receipt_layout.receipt(tx, items, int(tx['print_count']) > 0)
        self._output_print(layout, 'レシート ' + str(tx['receipt_no']))

    def print_test(self):
        """テスト印刷"""
        self.auth.require_login()
        self._setup()
        self._output_print(receipt_layout.test(PosSetting(self.db).get(self.auth.tenant_id())), 'テスト印刷')

    # ------------------------------------------------------------------
    # 取引履歴・詳細・取消・CSV
    # ------------------------------------------------------------------
    def _history_filters(self):
        today = today_str()

        def s(key, mx):
            return trim(self._get_s(key))[:mx]

        frm = norm_date(self.request.get('date_from', ''), today)
        to = norm_date(self.request.get('date_to', ''), today)
        if frm > to:
            frm, to = to, frm
        status = s('status', 20)
        method = s('payment_method', 20)
        return {
            'date_from': frm,
            'date_to': to,
            'status': status if status in ('completed', 'voided') else '',
            'payment_method': method if method in receipt_layout.PAYMENT_LABELS else '',
            'receipt_no': s('receipt_no', 20),
            # 会員: 会員番号の完全一致または会員名の部分一致（旧 URL の member_code も受け付ける）
            'member': s('member', 50) if s('member', 50) != '' else s('member_code', 50),
            'member_id': int(s('member_id', 10)) if is_digits(s('member_id', 10)) else 0,
            'cashier': s('cashier', 50),
            'keyword': s('keyword', 100),
            'ledger_id': int(s('ledger_id', 18)) if is_digits(s('ledger_id', 18)) else 0,
            'register_no': self._register_filter(),
            'branch_id': self._branch_filter(),
        }

    def _page(self):
        p = self.request.get('p', '1')
        return max(1, int(p)) if isinstance(p, str) and is_digits(p) else 1

    def lookup(self):
        """レシート番号で取引を呼び出す（明細・再印刷・領収書・取消の画面へ）。GET: no, format=json"""
        as_json = self._get_s('format') == 'json'
        if as_json:
            self._require_auth_json()
        else:
            # ルートは JSON 応答のため認証なしで登録している。画面遷移の場合はここで確認する
            self.auth.require_login()
            if self.auth.must_change_password():
                self.redirect('/index.cgi?page=change_password')
        self._setup()
        raw = self.request.get('no', '')
        no = normalize_receipt_no(raw, today_str()) if isinstance(raw, str) else None
        tx = PosTransaction(self.db).find_by_receipt_no(self.auth.tenant_id(), no) if no is not None else None
        shown = raw[:30] if isinstance(raw, str) else ''
        if as_json:
            if tx is None:
                self._json({'ok': False, 'error': 'レシート番号「%s」の取引は見つかりません。' % shown})
            self._json({'ok': True, 'id': int(tx['id']), 'receipt_no': tx['receipt_no'],
                        'url': '/index.cgi?page=pos.show&id=%d' % int(tx['id'])})
        if tx is None:
            self.flash('error', 'レシート番号「%s」の取引は見つかりません。（例：20261023-0001、本日分は連番だけ「1」でも可）' % shown)
            self.redirect('/index.cgi?page=pos.history')
        self.redirect('/index.cgi?page=pos.show&id=%d' % int(tx['id']))

    def member_search(self):
        """会員検索（JSON・POSレジの会員選択）。GET: q（会員番号・氏名・電話番号の一部）"""
        self._require_auth_json()
        # 会員情報の機械的な列挙を防ぐ（1分間に30回まで）
        if not rate_limiter.hit(self.session, 'pos.member', 30, 60):
            self._json({'ok': False, 'members': [], 'error': '短時間に検索が集中しています。しばらく待ってから再度お試しください。'}, 429)
        q = trim(self._get_s('q'))[:50]
        if len(q) < 1:
            self._json({'ok': True, 'members': []})
        tenant_id = self.auth.tenant_id()
        like = '%' + like_escape(q) + '%'
        digits = re.sub(r'[^0-9]', '', mb_convert_kana_n(q))
        sql = ("SELECT `id`, `member_code`, `name`, `counterpart_type`, `phone` FROM `members` "
               "WHERE `tenant_id` = ? AND (`member_code` LIKE ? OR `name` LIKE ?"
               + (" OR REPLACE(REPLACE(`phone`, '-', ''), ' ', '') LIKE ?" if len(digits) >= 4 else '')
               + ") ORDER BY (`member_code` = ?) DESC, `member_code` ASC LIMIT 20")
        params = [tenant_id, like, like]
        if len(digits) >= 4:
            params.append('%' + digits + '%')
        params.append(q)
        try:
            rows = self.db.query(sql, params)
        except DBError:
            rows = []
        stats = PosTransaction(self.db).member_stats(tenant_id, [r['id'] for r in rows])
        out = []
        for m in rows:
            phone = re.sub(r'[^0-9]', '', str(m.get('phone') or ''))
            st = stats.get(int(m['id'])) or {'count': 0, 'total': 0, 'last_at': None}
            out.append({
                'id': int(m['id']),
                'member_code': str(m['member_code']),
                'name': str(m['name']),
                'corporate': m['counterpart_type'] == 'corporate',
                # 電話番号は本人確認の目安として下4桁だけ返す
                'phone_tail': phone[-4:] if len(phone) >= 4 else '',
                'visits': st['count'],
                'last_at': str(st['last_at'])[:10] if st['last_at'] is not None else '',
            })
        self._json({'ok': True, 'members': out})

    def history(self):
        self.auth.require_login()
        self._setup()
        tenant_id = self.auth.tenant_id()
        filters = self._history_filters()
        page = self._page()
        per_page = 50
        txs = PosTransaction(self.db)
        result = txs.search(tenant_id, filters, page, per_page)
        self.render('pos/history', {
            'rows': result['rows'], 'total': result['total'], 'sumTotal': result['sum_total'],
            'sumCount': result['sum_count'], 'filters': filters, 'page': page,
            'totalPages': max(1, int(math.ceil(result['total'] / per_page))),
            'branches': Branch(self.db).find_all_by_tenant(tenant_id), 'registers': txs.register_numbers(tenant_id),
            'isAdmin': self.auth.is_admin(), 'activePage': 'pos.history',
        })

    def items(self):
        """レジ明細検索（明細単位の検索・集計）"""
        self.auth.require_login()
        self._setup()
        tenant_id = self.auth.tenant_id()
        filters = self._history_filters()
        page = self._page()
        per_page = 100
        txs = PosTransaction(self.db)
        result = txs.search_items(tenant_id, filters, page, per_page)
        self.render('pos/items', {
            'rows': result['rows'], 'total': result['total'], 'sumQty': result['qty'],
            'sumAmount': result['amount'], 'sumAlloc': result['allocated'], 'filters': filters, 'page': page,
            'totalPages': max(1, int(math.ceil(result['total'] / per_page))),
            'branches': Branch(self.db).find_all_by_tenant(tenant_id), 'registers': txs.register_numbers(tenant_id),
            'isAdmin': self.auth.is_admin(), 'activePage': 'pos.items',
        })

    def show(self):
        self.auth.require_login()
        self._setup()
        tenant_id = self.auth.tenant_id()
        txs = PosTransaction(self.db)
        tx = txs.find_by_id(self.get_int('id'), tenant_id)
        if tx is None:
            self.not_found('取引が見つかりません。')
        self.render('pos/show', {
            'tx': tx, 'items': txs.items(int(tx['id']), tenant_id),
            'settings': PosSetting(self.db).get(tenant_id), 'isAdmin': self.auth.is_admin(),
            'activePage': 'pos.history',
        })

    def void_transaction(self):
        """会計の取消（返品・管理者のみ）: 販売記録を削除して在庫を戻す"""
        self.auth.require_admin_role()
        self.verify_csrf()
        self._setup()
        tenant_id = self.auth.tenant_id()
        tx_id = self.post_int('id')
        reason = self.post_string('reason')
        back = '/index.cgi?page=pos.show&id=%d' % tx_id
        if reason == '' or len(reason) > 255:
            self.flash('error', '取消理由を255文字以内で入力してください。')
            self.redirect(back)
        txs = PosTransaction(self.db)
        try:
            before = txs.void(tx_id, tenant_id, self.auth.user_id(), reason)
        except Exception as e:
            log_error('POS void failed: %s' % e)
            self.flash('error', '取消処理に失敗しました。もう一度お試しください。')
            self.redirect(back)
        if before is None:
            self.flash('error', 'この取引は取消できません（既に取消済みか、見つかりません）。')
            self.redirect(back)
        items = txs.items(tx_id, tenant_id)
        self._audit('delete', tx_id, {
            'kind': 'pos_transaction', 'receipt_no': before['receipt_no'], 'total': int(before['total']),
            'payment_method': before['payment_method'],
            'lines': [{'ledger_id': int(i['ledger_id']),
                       'sale_id': int(i['sale_id']) if i['sale_id'] is not None else None,
                       'quantity': int(i['quantity'])} for i in items],
        }, {'kind': 'pos_void', 'status': 'voided', 'reason': reason})
        if before['payment_method'] == 'cash':
            refund = '現金 ¥%s を返金してください。' % number_format(int(before['total']))
        else:
            refund = '%sの取消（返金）手続きを各決済端末で行ってください。' % receipt_layout.PAYMENT_LABELS.get(before['payment_method'], 'その他')
        self.flash('success', '✓ 取引 No.%s を取り消し、在庫を戻しました。%s' % (before['receipt_no'], refund))
        self.redirect(back)

    def export(self):
        """取引明細の CSV 出力（管理者のみ）。mode=items はレジ明細検索の条件で出力する"""
        self.auth.require_admin_role()
        self._setup()
        tenant_id = self.auth.tenant_id()
        filters = self._history_filters()
        line_mode = self._get_s('mode') == 'items'
        rows = PosTransaction(self.db).export_rows(tenant_id, filters, 20000, line_mode)
        self._audit('export', None, None, {'kind': 'pos_csv', 'count': len(rows), 'filters': filters})
        span = filters['date_from'].replace('-', '') + '-' + filters['date_to'].replace('-', '')
        out = ['﻿', csv_writer.row(CSV_HEADER)]
        for r in rows:
            out.append(csv_writer.row([_csv_safe(v) for v in [
                r['created_at'], r['receipt_no'], r['register_no'] if r['register_no'] is not None else '',
                '取消' if r['status'] == 'voided' else '完了', r['branch_name'] or '',
                r['cashier_name'] or '', receipt_layout.PAYMENT_LABELS.get(r['payment_method'], r['payment_method']),
                r['member_code'] or '', r['member_name'] or '', r['line_no'], r['ledger_id'], r['item_name'],
                r['serial_number'] or '', r['quantity'], to_int(r['unit_price']), to_int(r['line_discount']),
                to_int(r['amount']), to_int(r['allocated_amount']), to_int(r['subtotal']), to_int(r['discount_amount']),
                '外税' if r['tax_mode'] == 'exclusive' else '内税', r['tax_rate'], to_int(r['tax_amount']),
                to_int(r['total']), to_int(r['tendered']), to_int(r['change_amount']),
                r['voided_at'] or '', r['void_reason'] or '',
            ]]))
        raise ResponseDone(Response(''.join(out).encode('utf-8'), 200, 'text/csv; charset=UTF-8', [
            ('Content-Disposition', 'attachment; filename="pos_sales_%s.csv"; filename*=UTF-8\'\'%s'
             % (span, rawurlencode('POS売上明細_%s.csv' % span))),
            ('Cache-Control', 'no-cache, no-store, must-revalidate'),
        ]))

    # ------------------------------------------------------------------
    # レジ精算（日計）
    # ------------------------------------------------------------------
    @staticmethod
    def _branch_label(branch_id, branches):
        if branch_id is None:
            return '全拠点'
        for b in branches:
            if int(b['id']) == branch_id:
                return str(b['name'])
        return '拠点 #%d' % branch_id

    def daily(self):
        self.auth.require_login()
        self._setup()
        tenant_id = self.auth.tenant_id()
        date = norm_date(self.request.get('date', ''), today_str())
        branch_id = self._branch_filter()
        register_no = self._register_filter()
        branches = Branch(self.db).find_all_by_tenant(tenant_id)
        if branch_id is not None and self._branch_label(branch_id, branches) == '拠点 #%d' % branch_id:
            branch_id = None  # 他テナントの拠点 ID は無視する
        txs = PosTransaction(self.db)
        self.render('pos/daily', {
            'date': date, 'branchId': branch_id, 'registerNo': register_no,
            'registers': txs.register_numbers(tenant_id), 'branches': branches,
            'branchLabel': self._branch_label(branch_id, branches),
            'summary': txs.daily_summary(tenant_id, date, branch_id, register_no),
            'closings': PosClosing(self.db).find_by_date(tenant_id, date),
            'closedId': self.get_int('closed'),
            'denominations': DENOMINATIONS,
            'activePage': 'pos.daily',
        })

    def close(self):
        """精算の記録。POST: date, branch, register, opening_float, den[金種]=枚数, counted_cash, note"""
        self.auth.require_login()
        self.verify_csrf()
        self._setup()
        tenant_id = self.auth.tenant_id()
        date = norm_date(self.request.post('date', ''), '')
        branch_in = self.request.post('branch', '')
        branch_id = int(branch_in) if isinstance(branch_in, str) and is_digits(branch_in) and int(branch_in) > 0 else None
        branches = Branch(self.db).find_all_by_tenant(tenant_id)
        if branch_id is not None and self._branch_label(branch_id, branches) == '拠点 #%d' % branch_id:
            branch_id = None
        register_no = self._register_filter('register', True)
        back = ('/index.cgi?page=pos.daily&date=' + rawurlencode(date)
                + ('&branch=%d' % branch_id if branch_id is not None else '')
                + ('&register=%d' % register_no if register_no is not None else ''))
        if date == '' or date > today_str():
            self.flash('error', '営業日が不正です（未来の日付は精算できません）。')
            self.redirect('/index.cgi?page=pos.daily')

        opening = _num(self.request.post('opening_float', ''))
        counted = _num(self.request.post('counted_cash', ''))
        note = self.post_string('note')
        mx = pos_calculator.MAX_AMOUNT
        if opening is None or counted is None or opening > mx or counted > mx:
            self.flash('error', '釣銭準備金・現金実査額は0以上の数値（円）で入力してください。')
            self.redirect(back)
        if len(note) > 400:
            self.flash('error', '備考は400文字以内で入力してください。')
            self.redirect(back)

        den_in = self.request.post('den', {})
        denominations = {}
        den_total = 0
        for face in DENOMINATIONS:
            cnt = _num(den_in.get(str(face), '')) if isinstance(den_in, dict) else 0
            if cnt is None or cnt > 100000:
                self.flash('error', '%s円の枚数が不正です。' % number_format(face))
                self.redirect(back)
            denominations[str(face)] = cnt
            den_total += face * cnt
        # 金種を入力した場合は金種の合計を実査額とする
        if den_total > 0:
            counted = den_total

        summary = PosTransaction(self.db).daily_summary(tenant_id, date, branch_id, register_no)
        # 理論現金残高 = 釣銭準備金 + 当日の現金売上 − 当日に返金した前日以前の現金会計
        expected = opening + int(summary['cash_sales']) - int(summary.get('refund_prev_cash') or 0)
        closing_id = PosClosing(self.db).create({
            'tenant_id': tenant_id, 'branch_id': branch_id, 'register_no': register_no, 'biz_date': date,
            'tx_count': int(summary['tx_count']), 'sales_total': int(summary['total']),
            'cash_sales': int(summary['cash_sales']), 'opening_float': opening, 'expected_cash': expected,
            'counted_cash': counted, 'difference': counted - expected, 'denominations': denominations,
            'summary': summary, 'note': note, 'closed_by': self.auth.user_id(), 'closed_by_name': self.user_name(),
        })
        self._audit('create', closing_id, None, {
            'kind': 'pos_closing', 'biz_date': date, 'branch_id': branch_id, 'register_no': register_no,
            'sales_total': int(summary['total']), 'expected_cash': expected, 'counted_cash': counted,
            'difference': counted - expected,
        })
        diff = counted - expected
        if diff == 0:
            self.flash('success', '✓ 精算を記録しました（過不足なし）。')
        else:
            self.flash('error', '精算を記録しました。現金に過不足があります（%s¥%s）。'
                       % ('+' if diff > 0 else '-', number_format(abs(diff))))
        self.redirect(back + '&closed=%d' % closing_id)

    def closing_print(self):
        """精算レポートの印刷（HTML or JSON）"""
        self.auth.require_login()
        self._setup()
        tenant_id = self.auth.tenant_id()
        closing = PosClosing(self.db).find_by_id(self.get_int('id'), tenant_id)
        if closing is None:
            if self._get_s('format') == 'json':
                self._json_error('精算記録が見つかりません。', 'not_found', 404)
            self.not_found('精算記録が見つかりません。')
        settings = PosSetting(self.db).get(tenant_id)
        if closing['branch_id'] is not None:
            label = str(closing.get('branch_name') or '拠点 #%s' % closing['branch_id'])
        else:
            label = '全拠点'
        reg = 'レジ%02d' % int(closing['register_no']) if not is_empty(closing.get('register_no')) else '全レジ'
        self._output_print(receipt_layout.closing(closing, settings['store_name'], label, reg),
                           'レジ精算 ' + str(closing['biz_date']))

    # ------------------------------------------------------------------
    # 設定
    # ------------------------------------------------------------------
    def settings(self):
        self.auth.require_login()
        self._setup()
        self.render('pos/settings', {
            'settings': PosSetting(self.db).get(self.auth.tenant_id()), 'isAdmin': self.auth.is_admin(),
            'errors': {}, 'activePage': 'pos.settings',
        })

    def settings_save(self):
        self.auth.require_admin_role()
        self.verify_csrf()
        self._setup()
        tenant_id = self.auth.tenant_id()
        model = PosSetting(self.db)
        before = model.get(tenant_id)
        data, errors = pos_setting_mod.validate(self.request.form)
        # 制御文字を取り除く（改行は残す）
        data = {k: strip_controls(v) if isinstance(v, str) else v for k, v in data.items()}
        if errors:
            merged = dict(before)
            merged.update(data)
            merged['store_name_raw'] = data['store_name']
            self.render('pos/settings', {'settings': merged, 'isAdmin': True, 'errors': errors,
                                         'activePage': 'pos.settings'})
        model.save(tenant_id, data, self.auth.user_id())
        b = {'kind': 'pos_settings'}
        for k in ('store_name_raw', 'store_address', 'store_phone', 'invoice_number', 'tax_rate', 'tax_mode',
                  'tax_rounding', 'receipt_header', 'receipt_footer', 'ryoshu_tadashi'):
            b[k] = before[k]
        a = {'kind': 'pos_settings'}
        a.update(data)
        self._audit('edit', None, b, a)
        self.flash('success', '✓ 店舗・レシート設定を保存しました。')
        self.redirect('/index.cgi?page=pos.settings')
