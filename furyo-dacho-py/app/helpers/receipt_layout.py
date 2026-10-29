"""
レシート・領収書・精算レポートの「レイアウト」を組み立てる

レイアウトは幅に依存しない行のリストで、次の2通りに描画される（紙と画面の内容が食い違わない）:
  - views/pos/print.html          : HTML（ブラウザ印刷・画面表示）
  - views/pos/_printer.html (JS)  : Canvas → ESC/POS ラスター（USB / シリアル直結プリンタ）

行の種類:
  {'t': 'text', 'v': 文字列, 'a': 'l'|'c'|'r', 's': 1|2（文字サイズ）, 'b': 太字}
  {'t': 'row',  'l': 左, 'r': 右, 's': 1|2, 'b': 太字}   … 左右振り分け
  {'t': 'hr'} 破線 / {'t': 'hr2'} 二重線 / {'t': 'feed', 'n': 行数}
  {'t': 'box', 'v': 文字列}  … 収入印紙欄などの枠
  {'t': 'barcode', 'v': 値, 'm': モジュール幅のリスト}  … CODE128
"""
import json
import re

from ..util import is_empty, jp_datetime, now_str, number_format, to_int, yen
from . import code128

PAYMENT_LABELS = {
    'cash': '現金',
    'credit': 'クレジットカード',
    'emoney': '電子マネー',
    'qr': 'QRコード決済',
    'other': 'その他',
}


def _t(v, a='l', s=1, b=False):
    return {'t': 'text', 'v': v, 'a': a, 's': s, 'b': b}


def _row(left, right, s=1, b=False):
    return {'t': 'row', 'l': left, 'r': right, 's': s, 'b': b}


def _s(v):
    return '' if v is None else str(v)


def store_info(tx):
    """会計時点の店舗情報（JSON）"""
    if not is_empty(tx.get('store_info')):
        try:
            v = json.loads(tx['store_info'])
            if isinstance(v, dict):
                return v
        except ValueError:
            pass
    return {}


def _store_lines(store, align='c'):
    out = []
    if _s(store.get('store_address')) != '':
        out.append(_t(_s(store['store_address']), align))
    if _s(store.get('store_phone')) != '':
        out.append(_t('TEL ' + _s(store['store_phone']), align))
    if _s(store.get('invoice_number')) != '':
        out.append(_t('登録番号 ' + _s(store['invoice_number']), align))
    return out


def _multiline(text, align='c'):
    # PHP の \R（改行）と trim() と同じ扱い
    lines = re.split('\r\n|[\n\x0b\x0c\r\x85\u2028\u2029]', text)
    return [_t(line, align) for line in lines if line.strip(' \t\n\r\0\x0b') != '']


def _tax_lines(tx):
    rate = to_int(tx.get('tax_rate'))
    if rate <= 0:
        return []
    total = to_int(tx.get('total'))
    tax = to_int(tx.get('tax_amount'))
    if (tx.get('tax_mode') or 'inclusive') == 'exclusive':
        return [_row('(%d%%対象 税抜' % rate, yen(total - tax) + ')'),
                _row('(%d%%消費税等' % rate, yen(tax) + ')')]
    return [_row('(%d%%対象' % rate, yen(total) + ')'),
            _row('(内消費税等', yen(tax) + ')')]


def register_label(tx):
    """「レジ01 」（レジ番号の無い過去の会計は空）"""
    no = to_int(tx.get('register_no'))
    return 'レジ%02d ' % no if no > 0 else ''


def _receipt_barcode(receipt_no):
    value = receipt_no.replace('-', '')
    try:
        mods = code128.modules(value)
    except ValueError:
        return []
    return [{'t': 'feed', 'n': 1}, {'t': 'barcode', 'v': value, 'm': mods}, _t(receipt_no, 'c')]


def receipt(tx, items, reprint=False):
    store = store_info(tx)
    L = []
    if tx.get('status') == 'voided':
        L.append(_t('【取引取消】', 'c', 2, True))
    if reprint:
        L.append(_t('【再発行】', 'c', 1, True))
    L.append(_t(_s(store.get('store_name')), 'c', 2, True))
    L += _store_lines(store)
    if _s(store.get('receipt_header')) != '':
        L += _multiline(_s(store['receipt_header']))
    L.append({'t': 'hr'})
    L.append(_t('レシート', 'c', 1, True))
    L.append(_t(jp_datetime(tx.get('created_at'))))
    L.append(_row(register_label(tx) + 'No.' + _s(tx.get('receipt_no')), '担当 ' + _s(tx.get('cashier_name'))))
    if not is_empty(tx.get('member_code')):
        L.append(_t('会員番号 ' + _s(tx['member_code'])
                    + (('  ' + _s(tx['member_name']) + ' 様') if not is_empty(tx.get('member_name')) else '')))
    L.append({'t': 'hr'})
    for it in items:
        qty = to_int(it.get('quantity'))
        unit = to_int(it.get('unit_price'))
        ldisc = to_int(it.get('line_discount'))
        L.append(_t(_s(it.get('item_name'))))
        if not is_empty(it.get('serial_number')):
            L.append(_t('  SN:' + _s(it['serial_number'])))
        L.append(_row('  @%s × %d' % (number_format(unit), qty), yen(unit * qty)))
        if ldisc > 0:
            L.append(_row('  値引', yen(-ldisc)))
    L.append({'t': 'hr'})
    L.append(_row('小計 (%d点)' % to_int(tx.get('item_count')), yen(tx.get('subtotal'))))
    if to_int(tx.get('discount_amount')) > 0:
        label = ('値引 (%d%%)' % to_int(tx.get('discount_value'))) if tx.get('discount_type') == 'percent' else '値引'
        L.append(_row(label, yen(-to_int(tx.get('discount_amount')))))
    if tx.get('tax_mode') == 'exclusive' and to_int(tx.get('tax_rate')) > 0:
        L.append(_row('消費税等 (%d%%)' % to_int(tx.get('tax_rate')), yen(tx.get('tax_amount'))))
    L.append({'t': 'hr2'})
    L.append(_row('合計', yen(tx.get('total')), 2, True))
    L += _tax_lines(tx)
    L.append({'t': 'feed', 'n': 1})
    method = _s(tx.get('payment_method'))
    if method == 'cash':
        L.append(_row('お預り (現金)', yen(tx.get('tendered'))))
        L.append(_row('お釣り', yen(tx.get('change_amount')), 1, True))
    else:
        L.append(_row(PAYMENT_LABELS.get(method, 'その他'), yen(tx.get('total'))))
        if not is_empty(tx.get('payment_ref')):
            L.append(_t('  承認番号等 ' + _s(tx['payment_ref'])))
    if tx.get('status') == 'voided':
        L.append({'t': 'hr'})
        L.append(_t('この取引は取り消されました', 'c', 1, True))
        if not is_empty(tx.get('voided_at')):
            L.append(_t('取消日時 ' + jp_datetime(tx['voided_at']), 'c'))
    if _s(store.get('receipt_footer')) != '':
        L.append({'t': 'hr'})
        L += _multiline(_s(store['receipt_footer']))
    L += _receipt_barcode(_s(tx.get('receipt_no')))
    L.append({'t': 'feed', 'n': 1})
    return L


def ryoshu(tx, addressee, tadashi, reprint=False):
    """領収書"""
    store = store_info(tx)
    total = to_int(tx.get('total'))
    L = []
    if tx.get('status') == 'voided':
        L.append(_t('【取引取消】', 'c', 2, True))
    if reprint:
        L.append(_t('【再発行】', 'c', 1, True))
    L.append(_t('領 収 書', 'c', 2, True))
    L.append({'t': 'feed', 'n': 1})
    L.append(_t((addressee if addressee != '' else '　' * 8) + ' 様', 'l', 1, True))
    L.append({'t': 'hr2'})
    L.append(_t(yen(total) + '-', 'c', 2, True))
    L.append({'t': 'hr2'})
    L.append(_t('但し ' + (tadashi if tadashi != '' else 'お品代') + 'として'))
    L.append(_t('上記正に領収いたしました。'))
    L += _tax_lines(tx)
    L.append(_t('お支払方法 ' + PAYMENT_LABELS.get(_s(tx.get('payment_method')), 'その他')))
    L.append({'t': 'feed', 'n': 1})
    L.append(_t(jp_datetime(tx.get('created_at'), False)))
    L.append(_t(register_label(tx) + 'No.' + _s(tx.get('receipt_no'))))
    L.append({'t': 'feed', 'n': 1})
    L.append(_t(_s(store.get('store_name')), 'l', 1, True))
    L += _store_lines(store, 'l')
    # 印紙税: 現金受領で記載金額（消費税額を区分記載した場合は税抜）が5万円以上なら収入印紙が必要
    base = total - to_int(tx.get('tax_amount')) if to_int(tx.get('tax_rate')) > 0 else total
    if _s(tx.get('payment_method')) == 'cash' and base >= 50000:
        L.append({'t': 'feed', 'n': 1})
        L.append({'t': 'box', 'v': '収入印紙'})
    L.append({'t': 'feed', 'n': 1})
    return L


def closing(c, store_name, branch_label, reg_label='全レジ'):
    """レジ精算レポート（c は pos_closings の行。summary / denominations は展開済み）"""
    s = c.get('summary') or {}
    L = [
        _t('レジ精算レポート', 'c', 2, True),
        _t(store_name, 'c'),
        {'t': 'hr'},
        _t('営業日 ' + jp_datetime(c.get('biz_date'), False)),
        _t('拠点 ' + branch_label + ' ／ ' + reg_label),
        _t('精算 ' + jp_datetime(c.get('created_at'))),
        _t('担当 ' + _s(c.get('closed_by_name'))),
        {'t': 'hr'},
        _row('取引件数', number_format(to_int(s.get('tx_count'))) + '件'),
        _row('販売点数', number_format(to_int(s.get('item_count'))) + '点'),
        _row('小計', yen(s.get('subtotal'))),
        _row('値引', yen(-to_int(s.get('discount')))),
        _row('売上合計', yen(s.get('total')), 1, True),
        _row('  うち消費税等', yen(s.get('tax'))),
        {'t': 'hr'},
        _t('支払方法別', 'l', 1, True),
    ]
    by_method = s.get('by_method') or {}
    for key, label in PAYMENT_LABELS.items():
        p = by_method.get(key) or {'count': 0, 'total': 0}
        if to_int(p.get('count')) == 0:
            continue
        L.append(_row('  %s %d件' % (label, to_int(p.get('count'))), yen(p.get('total'))))
    L.append(_row('取消', '%d件 %s' % (to_int(s.get('void_count')), yen(s.get('void_total')))))
    L.append({'t': 'hr'})
    L.append(_row('釣銭準備金', yen(c.get('opening_float'))))
    L.append(_row('現金売上', yen(c.get('cash_sales'))))
    if to_int(s.get('refund_prev_cash')) > 0:
        L.append(_row('前日以前分の現金返金', yen(-to_int(s.get('refund_prev_cash')))))
    L.append(_row('理論現金残高', yen(c.get('expected_cash'))))
    L.append(_row('現金実査額', yen(c.get('counted_cash'))))
    diff = to_int(c.get('difference'))
    L.append(_row('過不足', ('+' if diff > 0 else '') + yen(diff), 1, True))
    den = c.get('denominations') or {}
    if isinstance(den, dict) and sum(to_int(v) for v in den.values()) > 0:
        L.append({'t': 'hr'})
        L.append(_t('金種内訳', 'l', 1, True))
        for face, count in den.items():
            if to_int(count) > 0:
                L.append(_row('  %s円 × %d' % (number_format(to_int(face)), to_int(count)),
                              yen(to_int(face) * to_int(count))))
    if not is_empty(c.get('note')):
        L.append({'t': 'hr'})
        L.append(_t('備考 ' + _s(c['note'])))
    L.append({'t': 'feed', 'n': 1})
    return L


def test(settings):
    """テスト印刷"""
    return [
        _t('テスト印刷', 'c', 2, True),
        _t(_s(settings.get('store_name')), 'c'),
        {'t': 'hr'},
        _t(jp_datetime(now_str())),
        _t('日本語：あいうえお 漢字 カタカナ ｶﾀｶﾅ'),
        _t('ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789'),
        _row('左寄せ', '右寄せ ¥12,345'),
        _row('合計', '¥12,345', 2, True),
        {'t': 'hr2'},
        _t('この内容が正しく印刷されていれば', 'c'),
        _t('プリンタの設定は完了です。', 'c'),
        {'t': 'feed', 'n': 1},
    ]
