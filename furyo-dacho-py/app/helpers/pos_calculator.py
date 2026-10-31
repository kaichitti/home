"""
POS 会計の金額計算（サーバー側が正）

画面（views/pos/index.html の calc）も同じ手順で計算する。変更する場合は両方をそろえること。

  明細金額 = 単価 × 数量 − 単品値引
  小計     = Σ 明細金額
  小計値引 = 円指定: 指定額 / %指定: 小計 × % ÷ 100（切り捨て）
  内税: 合計 = 小計 − 小計値引、消費税 = 合計 × 税率 ÷ (100 + 税率) を端数処理
  外税: 税抜額 = 小計 − 小計値引、消費税 = 税抜額 × 税率 ÷ 100 を端数処理、合計 = 税抜額 + 消費税

売上記録（sales.sale_amount）には、合計を明細金額の比で按分した額を計上する
（端数は最大剰余法で配分し、按分額の合計が必ず合計と一致する）。整数だけで計算する。
"""
from ..util import number_format

MAX_AMOUNT = 999999999
MAX_QUANTITY = 9999
PAYMENT_METHODS = ('cash', 'credit', 'emoney', 'qr', 'other')


class CalcError(ValueError):
    """利用者に表示するメッセージ付きの入力エラー"""


def calculate(lines, discount, tax):
    if not lines:
        raise CalcError('明細がありません。')
    out_lines = []
    subtotal = 0
    item_count = 0
    for line in lines:
        qty = int(line['quantity'])
        price = int(line['unit_price'])
        ldisc = int(line.get('line_discount') or 0)
        if qty < 1 or qty > MAX_QUANTITY:
            raise CalcError('数量は1〜%dで入力してください。' % MAX_QUANTITY)
        if price < 0 or price > MAX_AMOUNT:
            raise CalcError('単価は0〜%s円で入力してください。' % number_format(MAX_AMOUNT))
        gross = price * qty
        if gross > MAX_AMOUNT:
            raise CalcError('1明細の金額が上限（%s円）を超えています。' % number_format(MAX_AMOUNT))
        if ldisc < 0 or ldisc > gross:
            raise CalcError('単品値引は0円以上、明細金額以下で入力してください。')
        amount = gross - ldisc
        subtotal += amount
        item_count += qty
        if subtotal > MAX_AMOUNT:
            raise CalcError('会計金額が上限（%s円）を超えています。' % number_format(MAX_AMOUNT))
        out_lines.append({'gross': gross, 'amount': amount, 'allocated': 0})

    d_type = str(discount.get('type') or 'none')
    d_value = int(discount.get('value') or 0)
    d_amount = 0
    if d_type == 'amount':
        if d_value < 0 or d_value > MAX_AMOUNT:
            raise CalcError('値引額が不正です。')
        if d_value > subtotal:
            raise CalcError('値引額が小計を超えています。')
        d_amount = d_value
    elif d_type == 'percent':
        if d_value < 0 or d_value > 100:
            raise CalcError('値引率は0〜100%で入力してください。')
        d_amount = subtotal * d_value // 100
    else:
        d_type = 'none'
        d_value = 0
    if d_amount == 0 and d_type != 'none' and d_value == 0:
        d_type = 'none'

    after = subtotal - d_amount
    rate = int(tax.get('rate') or 0)
    mode = 'exclusive' if tax.get('mode') == 'exclusive' else 'inclusive'
    rounding = str(tax.get('rounding') or 'floor')
    if rate < 0 or rate > 30:
        raise CalcError('消費税率の設定が不正です。')
    if mode == 'inclusive':
        total = after
        tax_amount = div_round(total * rate, 100 + rate, rounding) if rate > 0 else 0
        taxable = total
    else:
        tax_amount = div_round(after * rate, 100, rounding) if rate > 0 else 0
        total = after + tax_amount
        taxable = after

    _allocate(out_lines, subtotal, total)
    return {
        'lines': out_lines,
        'item_count': item_count,
        'subtotal': subtotal,
        'discount_type': d_type,
        'discount_value': d_value,
        'discount_amount': d_amount,
        'tax_mode': mode,
        'tax_rate': rate,
        'taxable': taxable,
        'tax_amount': tax_amount,
        'total': total,
    }


def payment(method, total, tendered):
    """支払の検証とお釣りの計算"""
    if method not in PAYMENT_METHODS:
        raise CalcError('支払方法を選択してください。')
    if method != 'cash':
        return {'method': method, 'tendered': total, 'change': 0}  # 現金以外は合計額ちょうど
    if tendered is None:
        raise CalcError('お預り金額を入力してください。')
    if tendered < total:
        raise CalcError('お預り金額が合計（¥%s）に足りません。' % number_format(total))
    if tendered > MAX_AMOUNT or tendered - total > 10000000:
        raise CalcError('お預り金額が大きすぎます。入力内容を確認してください。')
    return {'method': 'cash', 'tendered': tendered, 'change': tendered - total}


def div_round(a, b, rounding):
    """整数の割り算の端数処理（a, b > 0）"""
    if a <= 0:
        return 0
    if rounding == 'ceil':
        return (a + b - 1) // b
    if rounding == 'round':
        return (2 * a + b) // (2 * b)
    return a // b


def _allocate(lines, subtotal, total):
    if subtotal <= 0:
        # 全明細0円（無償提供など）の場合は按分しない
        for line in lines:
            line['allocated'] = 0
        if total > 0 and lines:
            lines[0]['allocated'] = total
        return
    assigned = 0
    remainders = []
    for i, line in enumerate(lines):
        num = total * line['amount']
        share = num // subtotal
        line['allocated'] = share
        assigned += share
        remainders.append((num % subtotal, i))
    left = total - assigned
    if left > 0:
        # 余りの大きい順（同じなら先の明細）に1円ずつ配る
        for _, i in sorted(remainders, key=lambda x: (-x[0], x[1])):
            if left <= 0:
                break
            lines[i]['allocated'] += 1
            left -= 1
