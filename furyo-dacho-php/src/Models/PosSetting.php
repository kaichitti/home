<?php

namespace FuryoDacho\Models;

/**
 * POS 設定（店舗情報・レシート文言・消費税）
 *
 * テナント単位で1行。未設定の場合は既定値（店舗名=テナント名、税率10%・内税・切り捨て）。
 */
class PosSetting extends BaseModel
{
    protected string $table = 'pos_settings';

    public const TAX_MODES     = ['inclusive' => '内税（税込価格で入力）', 'exclusive' => '外税（税抜価格で入力）'];
    public const TAX_ROUNDINGS = ['floor' => '切り捨て', 'round' => '四捨五入', 'ceil' => '切り上げ'];

    /**
     * 設定を取得（未登録の項目は既定値で補う）
     */
    public function get(int $tenantId): array
    {
        $row = null;
        try {
            $stmt = $this->pdo->prepare("SELECT * FROM `pos_settings` WHERE `tenant_id` = ?");
            $stmt->execute([$tenantId]);
            $row = $stmt->fetch() ?: null;
        } catch (\PDOException $e) {
            // テーブル未作成（マイグレーション前）は既定値で動かす
            if ((int)($e->errorInfo[1] ?? 0) !== 1146) {
                throw $e;
            }
        }

        $tenantName = '';
        try {
            $stmt = $this->pdo->prepare("SELECT `name` FROM `tenants` WHERE `id` = ?");
            $stmt->execute([$tenantId]);
            $tenantName = (string)($stmt->fetchColumn() ?: '');
        } catch (\Throwable $e) {
            $tenantName = '';
        }

        $taxMode     = (string)($row['tax_mode'] ?? 'inclusive');
        $taxRounding = (string)($row['tax_rounding'] ?? 'floor');

        return [
            'store_name'      => (string)($row['store_name'] ?? '') !== '' ? (string)$row['store_name'] : $tenantName,
            'store_name_raw'  => (string)($row['store_name'] ?? ''),
            'tenant_name'     => $tenantName,
            'store_address'   => (string)($row['store_address'] ?? ''),
            'store_phone'     => (string)($row['store_phone'] ?? ''),
            'invoice_number'  => (string)($row['invoice_number'] ?? ''),
            'tax_rate'        => $row !== null ? (int)$row['tax_rate'] : 10,
            'tax_mode'        => isset(self::TAX_MODES[$taxMode]) ? $taxMode : 'inclusive',
            'tax_rounding'    => isset(self::TAX_ROUNDINGS[$taxRounding]) ? $taxRounding : 'floor',
            'receipt_header'  => (string)($row['receipt_header'] ?? ''),
            'receipt_footer'  => (string)($row['receipt_footer'] ?? 'ご来店ありがとうございました。'),
            'ryoshu_tadashi'  => (string)($row['ryoshu_tadashi'] ?? '') !== '' ? (string)$row['ryoshu_tadashi'] : 'お品代',
            'is_saved'        => $row !== null,
        ];
    }

    /**
     * 入力値を検証して正規化する
     *
     * @return array{0: array, 1: array<string,string>} [正規化した値, エラー]
     */
    public static function validate(array $in): array
    {
        $errors = [];
        $str = static function ($v): string {
            return is_string($v) ? trim($v) : '';
        };

        $data = [
            'store_name'     => $str($in['store_name'] ?? ''),
            'store_address'  => $str($in['store_address'] ?? ''),
            'store_phone'    => $str($in['store_phone'] ?? ''),
            'invoice_number' => strtoupper(mb_convert_kana($str($in['invoice_number'] ?? ''), 'a', 'UTF-8')),
            'tax_rate'       => $str($in['tax_rate'] ?? '10'),
            'tax_mode'       => $str($in['tax_mode'] ?? 'inclusive'),
            'tax_rounding'   => $str($in['tax_rounding'] ?? 'floor'),
            'receipt_header' => $str($in['receipt_header'] ?? ''),
            'receipt_footer' => $str($in['receipt_footer'] ?? ''),
            'ryoshu_tadashi' => $str($in['ryoshu_tadashi'] ?? ''),
        ];
        $data['invoice_number'] = str_replace(['-', ' '], '', $data['invoice_number']);
        $data['store_phone']    = mb_convert_kana($data['store_phone'], 'a', 'UTF-8');

        $limits = [
            'store_name' => [100, '店舗名'], 'store_address' => [255, '住所'], 'store_phone' => [30, '電話番号'],
            'receipt_header' => [200, 'レシート上部メッセージ'], 'receipt_footer' => [200, 'レシート下部メッセージ'],
            'ryoshu_tadashi' => [50, '領収書の但し書き'],
        ];
        foreach ($limits as $key => [$max, $label]) {
            if (mb_strlen($data[$key]) > $max) {
                $errors[$key] = $label . 'は' . $max . '文字以内で入力してください。';
            }
        }
        if ($data['invoice_number'] !== '' && !preg_match('/^T[0-9]{13}$/', $data['invoice_number'])) {
            $errors['invoice_number'] = '登録番号は「T」に続く13桁の数字で入力してください（例：T1234567890123）。';
        }
        if (!preg_match('/^[0-9]{1,2}$/', $data['tax_rate']) || (int)$data['tax_rate'] > 30) {
            $errors['tax_rate'] = '消費税率は0〜30の整数（%）で入力してください。';
        }
        if (!isset(self::TAX_MODES[$data['tax_mode']])) {
            $errors['tax_mode'] = '価格の税表示を選択してください。';
        }
        if (!isset(self::TAX_ROUNDINGS[$data['tax_rounding']])) {
            $errors['tax_rounding'] = '端数処理を選択してください。';
        }
        $data['tax_rate'] = (int)$data['tax_rate'];

        return [$data, $errors];
    }

    /**
     * 設定を保存（UPSERT）
     */
    public function save(int $tenantId, array $data, int $userId): void
    {
        $nullIfEmpty = static fn (string $v): ?string => $v === '' ? null : $v;

        $stmt = $this->pdo->prepare(
            "INSERT INTO `pos_settings`
                (`tenant_id`, `store_name`, `store_address`, `store_phone`, `invoice_number`,
                 `tax_rate`, `tax_mode`, `tax_rounding`, `receipt_header`, `receipt_footer`, `ryoshu_tadashi`, `updated_by`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
             ON DUPLICATE KEY UPDATE
                `store_name` = VALUES(`store_name`), `store_address` = VALUES(`store_address`),
                `store_phone` = VALUES(`store_phone`), `invoice_number` = VALUES(`invoice_number`),
                `tax_rate` = VALUES(`tax_rate`), `tax_mode` = VALUES(`tax_mode`), `tax_rounding` = VALUES(`tax_rounding`),
                `receipt_header` = VALUES(`receipt_header`), `receipt_footer` = VALUES(`receipt_footer`),
                `ryoshu_tadashi` = VALUES(`ryoshu_tadashi`), `updated_by` = VALUES(`updated_by`)"
        );
        $stmt->execute([
            $tenantId,
            $nullIfEmpty($data['store_name']),
            $nullIfEmpty($data['store_address']),
            $nullIfEmpty($data['store_phone']),
            $nullIfEmpty($data['invoice_number']),
            (int)$data['tax_rate'],
            $data['tax_mode'],
            $data['tax_rounding'],
            $nullIfEmpty($data['receipt_header']),
            // 空欄で保存した場合は「メッセージなし」として扱う（既定文言に戻さない）
            $data['receipt_footer'],
            $nullIfEmpty($data['ryoshu_tadashi']),
            $userId,
        ]);
    }
}
