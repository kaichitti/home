<?php

namespace FuryoDacho\Helpers;

/**
 * POS 会計の金額計算（サーバー側が正）
 *
 * 画面（views/pos/index.php の calcTotals）も同じ手順で計算する。変更する場合は両方を揃えること。
 *
 *  明細金額  = 単価 × 数量 − 単品値引
 *  小計      = Σ 明細金額
 *  小計値引  = 円指定: min(指定額, 小計) / %指定: floor(小計 × % / 100)
 *  内税: 合計 = 小計 − 小計値引、消費税 = 合計 × 税率 / (100 + 税率) を端数処理
 *  外税: 税抜額 = 小計 − 小計値引、消費税 = 税抜額 × 税率 / 100 を端数処理、合計 = 税抜額 + 消費税
 *
 * 売上記録（sales.sale_amount）には、合計（税込のお支払額）を明細金額の比で按分した額を
 * 計上する（端数は最大剰余法で配分し、按分額の合計が必ず合計と一致する）。
 *
 * 整数演算のみで計算するため、金額の上限を 999,999,999 円に制限している
 * （按分時の 合計 × 明細金額 が 64bit 整数の範囲に収まるように）。
 */
final class PosCalculator
{
    public const MAX_AMOUNT   = 999999999;
    public const MAX_QUANTITY = 9999;

    /**
     * @param array<int, array{quantity:int, unit_price:int, line_discount:int}> $lines
     * @param array{type:string, value:int} $discount
     * @param array{rate:int, mode:string, rounding:string} $tax
     * @return array{
     *   lines: array<int, array{gross:int, amount:int, allocated:int}>,
     *   item_count:int, subtotal:int, discount_type:string, discount_value:int, discount_amount:int,
     *   taxable:int, tax_amount:int, total:int
     * }
     * @throws \InvalidArgumentException 入力が範囲外の場合（メッセージは利用者向け）
     */
    public static function calculate(array $lines, array $discount, array $tax): array
    {
        if ($lines === []) {
            throw new \InvalidArgumentException('明細がありません。');
        }

        $outLines  = [];
        $subtotal  = 0;
        $itemCount = 0;
        foreach ($lines as $i => $line) {
            $qty   = (int)$line['quantity'];
            $price = (int)$line['unit_price'];
            $ldisc = (int)($line['line_discount'] ?? 0);

            if ($qty < 1 || $qty > self::MAX_QUANTITY) {
                throw new \InvalidArgumentException('数量は1〜' . self::MAX_QUANTITY . 'で入力してください。');
            }
            if ($price < 0 || $price > self::MAX_AMOUNT) {
                throw new \InvalidArgumentException('単価は0〜' . number_format(self::MAX_AMOUNT) . '円で入力してください。');
            }
            $gross = $price * $qty;
            if ($gross > self::MAX_AMOUNT) {
                throw new \InvalidArgumentException('1明細の金額が上限（' . number_format(self::MAX_AMOUNT) . '円）を超えています。');
            }
            if ($ldisc < 0 || $ldisc > $gross) {
                throw new \InvalidArgumentException('単品値引は0円以上、明細金額以下で入力してください。');
            }

            $amount    = $gross - $ldisc;
            $subtotal += $amount;
            $itemCount += $qty;
            if ($subtotal > self::MAX_AMOUNT) {
                throw new \InvalidArgumentException('会計金額が上限（' . number_format(self::MAX_AMOUNT) . '円）を超えています。');
            }
            $outLines[$i] = ['gross' => $gross, 'amount' => $amount, 'allocated' => 0];
        }

        // 小計値引
        $dType  = (string)($discount['type'] ?? 'none');
        $dValue = (int)($discount['value'] ?? 0);
        $dAmount = 0;
        if ($dType === 'amount') {
            if ($dValue < 0 || $dValue > self::MAX_AMOUNT) {
                throw new \InvalidArgumentException('値引額が不正です。');
            }
            if ($dValue > $subtotal) {
                throw new \InvalidArgumentException('値引額が小計を超えています。');
            }
            $dAmount = $dValue;
        } elseif ($dType === 'percent') {
            if ($dValue < 0 || $dValue > 100) {
                throw new \InvalidArgumentException('値引率は0〜100%で入力してください。');
            }
            $dAmount = intdiv($subtotal * $dValue, 100);
        } else {
            $dType  = 'none';
            $dValue = 0;
        }
        if ($dAmount === 0 && $dType !== 'none' && $dValue === 0) {
            $dType = 'none';
        }

        $afterDiscount = $subtotal - $dAmount;

        // 消費税
        $rate     = (int)($tax['rate'] ?? 0);
        $mode     = ($tax['mode'] ?? 'inclusive') === 'exclusive' ? 'exclusive' : 'inclusive';
        $rounding = (string)($tax['rounding'] ?? 'floor');
        if ($rate < 0 || $rate > 30) {
            throw new \InvalidArgumentException('消費税率の設定が不正です。');
        }

        if ($mode === 'inclusive') {
            $total     = $afterDiscount;
            $taxAmount = $rate > 0 ? self::divRound($total * $rate, 100 + $rate, $rounding) : 0;
            $taxable   = $total; // 税込の対象額
        } else {
            $taxAmount = $rate > 0 ? self::divRound($afterDiscount * $rate, 100, $rounding) : 0;
            $total     = $afterDiscount + $taxAmount;
            $taxable   = $afterDiscount; // 税抜の対象額
        }

        // 合計を明細金額の比で按分（最大剰余法）
        $outLines = self::allocate($outLines, $subtotal, $total);

        return [
            'lines'           => $outLines,
            'item_count'      => $itemCount,
            'subtotal'        => $subtotal,
            'discount_type'   => $dType,
            'discount_value'  => $dValue,
            'discount_amount' => $dAmount,
            'tax_mode'        => $mode,
            'tax_rate'        => $rate,
            'taxable'         => $taxable,
            'tax_amount'      => $taxAmount,
            'total'           => $total,
        ];
    }

    /**
     * 支払の検証とお釣りの計算
     *
     * @return array{method:string, tendered:int, change:int}
     */
    public static function payment(string $method, int $total, ?int $tendered): array
    {
        $methods = ['cash', 'credit', 'emoney', 'qr', 'other'];
        if (!in_array($method, $methods, true)) {
            throw new \InvalidArgumentException('支払方法を選択してください。');
        }
        if ($method !== 'cash') {
            // 現金以外は合計額ちょうどの決済として扱う
            return ['method' => $method, 'tendered' => $total, 'change' => 0];
        }
        if ($tendered === null) {
            throw new \InvalidArgumentException('お預り金額を入力してください。');
        }
        if ($tendered < $total) {
            throw new \InvalidArgumentException('お預り金額が合計（¥' . number_format($total) . '）に足りません。');
        }
        if ($tendered > self::MAX_AMOUNT || $tendered - $total > 10000000) {
            throw new \InvalidArgumentException('お預り金額が大きすぎます。入力内容を確認してください。');
        }
        return ['method' => 'cash', 'tendered' => $tendered, 'change' => $tendered - $total];
    }

    /**
     * 整数の割り算を端数処理する（a, b > 0 を前提）
     */
    public static function divRound(int $a, int $b, string $rounding): int
    {
        if ($a <= 0) {
            return 0;
        }
        switch ($rounding) {
            case 'ceil':
                return intdiv($a + $b - 1, $b);
            case 'round':
                return intdiv(2 * $a + $b, 2 * $b);
            case 'floor':
            default:
                return intdiv($a, $b);
        }
    }

    /**
     * @param array<int, array{gross:int, amount:int, allocated:int}> $lines
     */
    private static function allocate(array $lines, int $subtotal, int $total): array
    {
        if ($subtotal <= 0) {
            // 全明細0円（無償提供など）の場合は按分しない
            foreach ($lines as $i => $l) {
                $lines[$i]['allocated'] = 0;
            }
            if ($total > 0 && $lines !== []) {
                $first = array_key_first($lines);
                $lines[$first]['allocated'] = $total;
            }
            return $lines;
        }

        $assigned   = 0;
        $remainders = [];
        foreach ($lines as $i => $l) {
            $num   = $total * $l['amount']; // 上限制限により 64bit に収まる
            $share = intdiv($num, $subtotal);
            $lines[$i]['allocated'] = $share;
            $assigned += $share;
            $remainders[$i] = $num % $subtotal;
        }
        $left = $total - $assigned;
        if ($left > 0) {
            // 余りの大きい順（同じなら先の明細）に1円ずつ配る
            uksort($remainders, static function ($a, $b) use ($remainders) {
                return $remainders[$b] <=> $remainders[$a] ?: $a <=> $b;
            });
            foreach (array_keys($remainders) as $i) {
                if ($left <= 0) {
                    break;
                }
                $lines[$i]['allocated']++;
                $left--;
            }
        }
        return $lines;
    }
}
