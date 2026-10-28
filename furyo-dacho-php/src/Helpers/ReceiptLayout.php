<?php

namespace FuryoDacho\Helpers;

/**
 * レシート・領収書・精算レポートの「レイアウト」を組み立てる
 *
 * レイアウトは幅に依存しない行の配列で、次の2通りに描画される:
 *  - views/pos/print.php           : HTML（ブラウザ印刷・画面表示）
 *  - views/pos/_printer.php (JS)   : Canvas → ESC/POS ラスター（USB / シリアル直結プリンタ）
 * 同じレイアウトから両方を描くため、紙と画面の内容が食い違わない。
 *
 * 行の種類:
 *  ['t' => 'text', 'v' => 文字列, 'a' => 'l'|'c'|'r', 's' => 1|2（文字サイズ）, 'b' => 太字]
 *  ['t' => 'row',  'l' => 左, 'r' => 右, 's' => 1|2, 'b' => 太字]   … 左右振り分け
 *  ['t' => 'hr'] 破線 / ['t' => 'hr2'] 二重線 / ['t' => 'feed', 'n' => 行数]
 *  ['t' => 'box', 'v' => 文字列]  … 収入印紙欄などの枠
 *  ['t' => 'barcode', 'v' => 値, 'm' => モジュール幅の配列]  … CODE128（Code128::modules）
 */
final class ReceiptLayout
{
    public const PAYMENT_LABELS = [
        'cash'   => '現金',
        'credit' => 'クレジットカード',
        'emoney' => '電子マネー',
        'qr'     => 'QRコード決済',
        'other'  => 'その他',
    ];

    private const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];

    public static function yen(int $v): string
    {
        return ($v < 0 ? '-¥' : '¥') . number_format(abs($v));
    }

    public static function jpDateTime(string $datetime, bool $withTime = true): string
    {
        $ts = strtotime($datetime);
        if ($ts === false) {
            return $datetime;
        }
        $s = date('Y年n月j日', $ts) . '(' . self::WEEKDAYS[(int)date('w', $ts)] . ')';
        return $withTime ? $s . ' ' . date('H:i', $ts) : $s;
    }

    private static function t(string $v, string $a = 'l', int $s = 1, bool $b = false): array
    {
        return ['t' => 'text', 'v' => $v, 'a' => $a, 's' => $s, 'b' => $b];
    }

    private static function row(string $l, string $r, int $s = 1, bool $b = false): array
    {
        return ['t' => 'row', 'l' => $l, 'r' => $r, 's' => $s, 'b' => $b];
    }

    /**
     * 店舗情報（会計時点のスナップショットを優先）
     */
    private static function storeLines(array $store, string $align = 'c'): array
    {
        $out = [];
        if (($store['store_address'] ?? '') !== '') {
            $out[] = self::t((string)$store['store_address'], $align);
        }
        if (($store['store_phone'] ?? '') !== '') {
            $out[] = self::t('TEL ' . $store['store_phone'], $align);
        }
        if (($store['invoice_number'] ?? '') !== '') {
            $out[] = self::t('登録番号 ' . $store['invoice_number'], $align);
        }
        return $out;
    }

    private static function multiline(string $text, string $align = 'c'): array
    {
        $out = [];
        foreach (preg_split('/\R/u', $text) ?: [] as $line) {
            if (trim($line) !== '') {
                $out[] = self::t($line, $align);
            }
        }
        return $out;
    }

    /**
     * 税率ごとの対象額・消費税額（適格簡易請求書の記載事項）
     */
    private static function taxLines(array $tx): array
    {
        $rate = (int)$tx['tax_rate'];
        if ($rate <= 0) {
            return [];
        }
        $total = (int)$tx['total'];
        $tax   = (int)$tx['tax_amount'];
        if (($tx['tax_mode'] ?? 'inclusive') === 'exclusive') {
            return [
                self::row('(' . $rate . '%対象 税抜', self::yen($total - $tax) . ')'),
                self::row('(' . $rate . '%消費税等', self::yen($tax) . ')'),
            ];
        }
        return [
            self::row('(' . $rate . '%対象', self::yen($total) . ')'),
            self::row('(内消費税等', self::yen($tax) . ')'),
        ];
    }

    /**
     * レシート
     *
     * @param array $tx    pos_transactions の行
     * @param array $items pos_transaction_items の行
     * @param bool  $reprint 再発行（2回目以降の印刷）
     */
    public static function receipt(array $tx, array $items, bool $reprint = false): array
    {
        $store = self::storeInfo($tx);
        $L = [];

        if (($tx['status'] ?? '') === 'voided') {
            $L[] = self::t('【取引取消】', 'c', 2, true);
        }
        if ($reprint) {
            $L[] = self::t('【再発行】', 'c', 1, true);
        }
        $L[] = self::t((string)($store['store_name'] ?? ''), 'c', 2, true);
        $L = array_merge($L, self::storeLines($store));
        if (($store['receipt_header'] ?? '') !== '') {
            $L = array_merge($L, self::multiline((string)$store['receipt_header']));
        }
        $L[] = ['t' => 'hr'];
        $L[] = self::t('レシート', 'c', 1, true);
        $L[] = self::t(self::jpDateTime((string)$tx['created_at']));
        $L[] = self::row(self::registerLabel($tx) . 'No.' . $tx['receipt_no'], '担当 ' . ($tx['cashier_name'] ?? ''));
        if (!empty($tx['member_code'])) {
            $L[] = self::t('会員番号 ' . $tx['member_code']
                . (!empty($tx['member_name']) ? '  ' . $tx['member_name'] . ' 様' : ''));
        }
        $L[] = ['t' => 'hr'];

        foreach ($items as $it) {
            $qty   = (int)$it['quantity'];
            $unit  = (int)$it['unit_price'];
            $ldisc = (int)$it['line_discount'];
            $L[] = self::t((string)$it['item_name']);
            if (!empty($it['serial_number'])) {
                $L[] = self::t('  SN:' . $it['serial_number']);
            }
            $L[] = self::row('  @' . number_format($unit) . ' × ' . $qty, self::yen($unit * $qty));
            if ($ldisc > 0) {
                $L[] = self::row('  値引', self::yen(-$ldisc));
            }
        }
        $L[] = ['t' => 'hr'];

        $L[] = self::row('小計 (' . (int)$tx['item_count'] . '点)', self::yen((int)$tx['subtotal']));
        if ((int)$tx['discount_amount'] > 0) {
            $label = ($tx['discount_type'] ?? '') === 'percent'
                ? '値引 (' . (int)$tx['discount_value'] . '%)'
                : '値引';
            $L[] = self::row($label, self::yen(-(int)$tx['discount_amount']));
        }
        if (($tx['tax_mode'] ?? '') === 'exclusive' && (int)$tx['tax_rate'] > 0) {
            $L[] = self::row('消費税等 (' . (int)$tx['tax_rate'] . '%)', self::yen((int)$tx['tax_amount']));
        }
        $L[] = ['t' => 'hr2'];
        $L[] = self::row('合計', self::yen((int)$tx['total']), 2, true);
        $L = array_merge($L, self::taxLines($tx));
        $L[] = ['t' => 'feed', 'n' => 1];

        $method = (string)$tx['payment_method'];
        if ($method === 'cash') {
            $L[] = self::row('お預り (現金)', self::yen((int)$tx['tendered']));
            $L[] = self::row('お釣り', self::yen((int)$tx['change_amount']), 1, true);
        } else {
            $L[] = self::row(self::PAYMENT_LABELS[$method] ?? 'その他', self::yen((int)$tx['total']));
            if (!empty($tx['payment_ref'])) {
                $L[] = self::t('  承認番号等 ' . $tx['payment_ref']);
            }
        }

        if (($tx['status'] ?? '') === 'voided') {
            $L[] = ['t' => 'hr'];
            $L[] = self::t('この取引は取り消されました', 'c', 1, true);
            if (!empty($tx['voided_at'])) {
                $L[] = self::t('取消日時 ' . self::jpDateTime((string)$tx['voided_at']), 'c');
            }
        }

        if (($store['receipt_footer'] ?? '') !== '') {
            $L[] = ['t' => 'hr'];
            $L = array_merge($L, self::multiline((string)$store['receipt_footer']));
        }
        // レシート番号のバーコード（POSレジの検索欄で読み取ると取引の明細・再印刷を開ける）
        $L = array_merge($L, self::receiptBarcode((string)$tx['receipt_no']));
        $L[] = ['t' => 'feed', 'n' => 1];
        return $L;
    }

    /**
     * レジ番号の表示（「レジ01 」。レジ番号の無い過去の会計は空）
     */
    public static function registerLabel(array $tx): string
    {
        $no = (int)($tx['register_no'] ?? 0);
        return $no > 0 ? 'レジ' . sprintf('%02d', $no) . ' ' : '';
    }

    /**
     * レシート番号のバーコード行（数字のみで符号化し、下に番号を印字）
     */
    private static function receiptBarcode(string $receiptNo): array
    {
        $value = str_replace('-', '', $receiptNo);
        try {
            $modules = Code128::modules($value);
        } catch (\InvalidArgumentException $e) {
            return [];
        }
        return [
            ['t' => 'feed', 'n' => 1],
            ['t' => 'barcode', 'v' => $value, 'm' => $modules],
            self::t($receiptNo, 'c'),
        ];
    }

    /**
     * 領収書
     */
    public static function ryoshu(array $tx, string $addressee, string $tadashi, bool $reprint = false): array
    {
        $store = self::storeInfo($tx);
        $total = (int)$tx['total'];
        $L = [];

        if (($tx['status'] ?? '') === 'voided') {
            $L[] = self::t('【取引取消】', 'c', 2, true);
        }
        if ($reprint) {
            $L[] = self::t('【再発行】', 'c', 1, true);
        }
        $L[] = self::t('領 収 書', 'c', 2, true);
        $L[] = ['t' => 'feed', 'n' => 1];
        $L[] = self::t(($addressee !== '' ? $addressee : '　　　　　　　　') . ' 様', 'l', 1, true);
        $L[] = ['t' => 'hr2'];
        $L[] = self::t(self::yen($total) . '-', 'c', 2, true);
        $L[] = ['t' => 'hr2'];
        $L[] = self::t('但し ' . ($tadashi !== '' ? $tadashi : 'お品代') . 'として');
        $L[] = self::t('上記正に領収いたしました。');
        $L = array_merge($L, self::taxLines($tx));
        $L[] = self::t('お支払方法 ' . (self::PAYMENT_LABELS[(string)$tx['payment_method']] ?? 'その他'));
        $L[] = ['t' => 'feed', 'n' => 1];
        $L[] = self::t(self::jpDateTime((string)$tx['created_at'], false));
        $L[] = self::t(self::registerLabel($tx) . 'No.' . $tx['receipt_no']);
        $L[] = ['t' => 'feed', 'n' => 1];
        $L[] = self::t((string)($store['store_name'] ?? ''), 'l', 1, true);
        $L = array_merge($L, self::storeLines($store, 'l'));

        // 印紙税: 現金受領で記載金額（消費税額を区分記載した場合は税抜）が5万円以上なら収入印紙が必要
        $base = (int)$tx['tax_rate'] > 0 ? $total - (int)$tx['tax_amount'] : $total;
        if ((string)$tx['payment_method'] === 'cash' && $base >= 50000) {
            $L[] = ['t' => 'feed', 'n' => 1];
            $L[] = ['t' => 'box', 'v' => '収入印紙'];
        }
        $L[] = ['t' => 'feed', 'n' => 1];
        return $L;
    }

    /**
     * レジ精算レポート
     *
     * @param array $closing pos_closings の行（summary / denominations は配列に展開済み）
     */
    public static function closing(array $closing, string $storeName, string $branchLabel, string $registerLabel = '全レジ'): array
    {
        $sum = $closing['summary'] ?? [];
        $L = [];
        $L[] = self::t('レジ精算レポート', 'c', 2, true);
        $L[] = self::t($storeName, 'c');
        $L[] = ['t' => 'hr'];
        $L[] = self::t('営業日 ' . self::jpDateTime((string)$closing['biz_date'], false));
        $L[] = self::t('拠点 ' . $branchLabel . ' ／ ' . $registerLabel);
        $L[] = self::t('精算 ' . self::jpDateTime((string)$closing['created_at']));
        $L[] = self::t('担当 ' . ($closing['closed_by_name'] ?? ''));
        $L[] = ['t' => 'hr'];
        $L[] = self::row('取引件数', number_format((int)($sum['tx_count'] ?? 0)) . '件');
        $L[] = self::row('販売点数', number_format((int)($sum['item_count'] ?? 0)) . '点');
        $L[] = self::row('小計', self::yen((int)($sum['subtotal'] ?? 0)));
        $L[] = self::row('値引', self::yen(-(int)($sum['discount'] ?? 0)));
        $L[] = self::row('売上合計', self::yen((int)($sum['total'] ?? 0)), 1, true);
        $L[] = self::row('  うち消費税等', self::yen((int)($sum['tax'] ?? 0)));
        $L[] = ['t' => 'hr'];
        $L[] = self::t('支払方法別', 'l', 1, true);
        foreach (self::PAYMENT_LABELS as $key => $label) {
            $p = $sum['by_method'][$key] ?? ['count' => 0, 'total' => 0];
            if ((int)$p['count'] === 0) {
                continue;
            }
            $L[] = self::row('  ' . $label . ' ' . (int)$p['count'] . '件', self::yen((int)$p['total']));
        }
        $L[] = self::row('取消', (int)($sum['void_count'] ?? 0) . '件 ' . self::yen((int)($sum['void_total'] ?? 0)));
        $L[] = ['t' => 'hr'];
        $L[] = self::row('釣銭準備金', self::yen((int)$closing['opening_float']));
        $L[] = self::row('現金売上', self::yen((int)$closing['cash_sales']));
        if ((int)($sum['refund_prev_cash'] ?? 0) > 0) {
            $L[] = self::row('前日以前分の現金返金', self::yen(-(int)$sum['refund_prev_cash']));
        }
        $L[] = self::row('理論現金残高', self::yen((int)$closing['expected_cash']));
        $L[] = self::row('現金実査額', self::yen((int)$closing['counted_cash']));
        $diff = (int)$closing['difference'];
        $L[] = self::row('過不足', ($diff > 0 ? '+' : '') . self::yen($diff), 1, true);

        $den = $closing['denominations'] ?? [];
        if (is_array($den) && array_sum(array_map('intval', $den)) > 0) {
            $L[] = ['t' => 'hr'];
            $L[] = self::t('金種内訳', 'l', 1, true);
            foreach ($den as $face => $count) {
                if ((int)$count > 0) {
                    $L[] = self::row('  ' . number_format((int)$face) . '円 × ' . (int)$count, self::yen((int)$face * (int)$count));
                }
            }
        }
        if (!empty($closing['note'])) {
            $L[] = ['t' => 'hr'];
            $L[] = self::t('備考 ' . $closing['note']);
        }
        $L[] = ['t' => 'feed', 'n' => 1];
        return $L;
    }

    /**
     * テスト印刷
     */
    public static function test(array $settings): array
    {
        return [
            self::t('テスト印刷', 'c', 2, true),
            self::t((string)($settings['store_name'] ?? ''), 'c'),
            ['t' => 'hr'],
            self::t(self::jpDateTime(date('Y-m-d H:i:s'))),
            self::t('日本語：あいうえお 漢字 カタカナ ｶﾀｶﾅ'),
            self::t('ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789'),
            self::row('左寄せ', '右寄せ ¥12,345'),
            self::row('合計', '¥12,345', 2, true),
            ['t' => 'hr2'],
            self::t('この内容が正しく印刷されていれば', 'c'),
            self::t('プリンタの設定は完了です。', 'c'),
            ['t' => 'feed', 'n' => 1],
        ];
    }

    /**
     * 会計時点の店舗情報（JSON）を取り出す
     */
    public static function storeInfo(array $tx): array
    {
        $info = [];
        if (!empty($tx['store_info'])) {
            $decoded = json_decode((string)$tx['store_info'], true);
            if (is_array($decoded)) {
                $info = $decoded;
            }
        }
        return $info;
    }
}
