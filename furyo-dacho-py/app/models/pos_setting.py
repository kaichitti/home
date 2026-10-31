"""
POS 設定（店舗情報・レシート文言・消費税）

テナント単位で1行。未設定の場合は既定値（店舗名=テナント名、税率10%・内税・切り捨て）。
"""
import re

from ..db import DBError, ER_NO_SUCH_TABLE
from ..util import mb_convert_kana_a, to_int, trim
from .base import BaseModel

TAX_MODES = {'inclusive': '内税（税込価格で入力）', 'exclusive': '外税（税抜価格で入力）'}
TAX_ROUNDINGS = {'floor': '切り捨て', 'round': '四捨五入', 'ceil': '切り上げ'}


def _s(v):
    return '' if v is None else str(v)


def _ascii_upper(s):
    """PHP の strtoupper（半角英字だけを大文字にする）"""
    return ''.join(chr(ord(c) - 32) if 'a' <= c <= 'z' else c for c in s)


def validate(values):
    """入力値を確認して整える。(整えた値, エラー) を返す"""
    errors = {}

    def s(key, default=''):
        v = values.get(key, default)
        return trim(v) if isinstance(v, str) else ''

    data = {
        'store_name': s('store_name'),
        'store_address': s('store_address'),
        'store_phone': s('store_phone'),
        'invoice_number': _ascii_upper(mb_convert_kana_a(s('invoice_number'))),
        'tax_rate': s('tax_rate', '10'),
        'tax_mode': s('tax_mode', 'inclusive'),
        'tax_rounding': s('tax_rounding', 'floor'),
        'receipt_header': s('receipt_header'),
        'receipt_footer': s('receipt_footer'),
        'ryoshu_tadashi': s('ryoshu_tadashi'),
    }
    data['invoice_number'] = data['invoice_number'].replace('-', '').replace(' ', '')
    data['store_phone'] = mb_convert_kana_a(data['store_phone'])

    limits = [
        ('store_name', 100, '店舗名'), ('store_address', 255, '住所'), ('store_phone', 30, '電話番号'),
        ('receipt_header', 200, 'レシート上部メッセージ'), ('receipt_footer', 200, 'レシート下部メッセージ'),
        ('ryoshu_tadashi', 50, '領収書の但し書き'),
    ]
    for key, mx, label in limits:
        if len(data[key]) > mx:
            errors[key] = '%sは%d文字以内で入力してください。' % (label, mx)
    if data['invoice_number'] != '' and not re.fullmatch(r'T[0-9]{13}', data['invoice_number']):
        errors['invoice_number'] = '登録番号は「T」に続く13桁の数字で入力してください（例：T1234567890123）。'
    if not re.fullmatch(r'[0-9]{1,2}', data['tax_rate']) or int(data['tax_rate']) > 30:
        errors['tax_rate'] = '消費税率は0〜30の整数（%）で入力してください。'
    if data['tax_mode'] not in TAX_MODES:
        errors['tax_mode'] = '価格の税表示を選択してください。'
    if data['tax_rounding'] not in TAX_ROUNDINGS:
        errors['tax_rounding'] = '端数処理を選択してください。'
    data['tax_rate'] = to_int(data['tax_rate'])
    return data, errors


class PosSetting(BaseModel):
    table = 'pos_settings'

    def get(self, tenant_id):
        """設定を取得する（未登録の項目は既定値で補う）"""
        row = None
        try:
            row = self.db.query_one("SELECT * FROM `pos_settings` WHERE `tenant_id` = ?", (int(tenant_id),))
        except DBError as e:
            if e.code != ER_NO_SUCH_TABLE:  # テーブル未作成（マイグレーション前）は既定値で動かす
                raise
        try:
            tenant_name = _s(self.db.value("SELECT `name` FROM `tenants` WHERE `id` = ?", (int(tenant_id),)) or '')
        except Exception:
            tenant_name = ''
        r = row or {}
        tax_mode = _s(r.get('tax_mode') or 'inclusive')
        tax_rounding = _s(r.get('tax_rounding') or 'floor')
        return {
            'store_name': _s(r.get('store_name')) if _s(r.get('store_name')) != '' else tenant_name,
            'store_name_raw': _s(r.get('store_name')),
            'tenant_name': tenant_name,
            'store_address': _s(r.get('store_address')),
            'store_phone': _s(r.get('store_phone')),
            'invoice_number': _s(r.get('invoice_number')),
            'tax_rate': int(r['tax_rate']) if row is not None else 10,
            'tax_mode': tax_mode if tax_mode in TAX_MODES else 'inclusive',
            'tax_rounding': tax_rounding if tax_rounding in TAX_ROUNDINGS else 'floor',
            'receipt_header': _s(r.get('receipt_header')),
            'receipt_footer': _s(r['receipt_footer'] if r.get('receipt_footer') is not None else 'ご来店ありがとうございました。'),
            'ryoshu_tadashi': _s(r.get('ryoshu_tadashi')) if _s(r.get('ryoshu_tadashi')) != '' else 'お品代',
            'is_saved': row is not None,
        }

    def save(self, tenant_id, data, user_id):
        def none_if_empty(v):
            return None if v == '' else v
        self.db.execute(
            """INSERT INTO `pos_settings`
                (`tenant_id`, `store_name`, `store_address`, `store_phone`, `invoice_number`,
                 `tax_rate`, `tax_mode`, `tax_rounding`, `receipt_header`, `receipt_footer`, `ryoshu_tadashi`, `updated_by`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON DUPLICATE KEY UPDATE
                `store_name` = VALUES(`store_name`), `store_address` = VALUES(`store_address`),
                `store_phone` = VALUES(`store_phone`), `invoice_number` = VALUES(`invoice_number`),
                `tax_rate` = VALUES(`tax_rate`), `tax_mode` = VALUES(`tax_mode`), `tax_rounding` = VALUES(`tax_rounding`),
                `receipt_header` = VALUES(`receipt_header`), `receipt_footer` = VALUES(`receipt_footer`),
                `ryoshu_tadashi` = VALUES(`ryoshu_tadashi`), `updated_by` = VALUES(`updated_by`)""",
            (int(tenant_id), none_if_empty(data['store_name']), none_if_empty(data['store_address']),
             none_if_empty(data['store_phone']), none_if_empty(data['invoice_number']), int(data['tax_rate']),
             data['tax_mode'], data['tax_rounding'], none_if_empty(data['receipt_header']),
             # 空欄で保存した場合は「メッセージなし」として扱う（既定文言に戻さない）
             data['receipt_footer'],
             none_if_empty(data['ryoshu_tadashi']), int(user_id)))
