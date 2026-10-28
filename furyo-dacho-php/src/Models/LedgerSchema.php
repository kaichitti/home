<?php

namespace FuryoDacho\Models;

/**
 * 台帳（ledgers）に後から追加した列の定義と自動追加（2026-10-26）
 *
 * - id_document_type_note : 本人確認書類「その他」の内容。
 *     以前は入力欄だけがあり保存先の列が無かったため、入力しても黙って捨てられていた
 *     （古物営業法上の「確認の方法」の記録が欠ける）。
 * - sale_price            : 販売予定価格（売価・任意）。POSレジでカートに入れた時の単価の初期値。
 *
 * migrate.php / schema.sql と同じ定義を使い、マイグレーション未実行の環境でも
 * 台帳を扱う画面を開いた時点で不足分を追加する（POS の自動作成と同じ方針）。
 */
final class LedgerSchema
{
    /** @var array<string, bool>|null 列名キャッシュ（列を追加したら破棄する） */
    private static ?array $columns = null;
    /**
     * @return array<int, array{column:string, ddl:string}>
     */
    public static function columnUpgrades(): array
    {
        return [
            ['column' => 'id_document_type_note', 'ddl' =>
                "ALTER TABLE `ledgers`
                 ADD COLUMN `id_document_type_note` VARCHAR(255) NULL DEFAULT NULL
                 COMMENT '本人確認書類の種別が「その他」の場合の内容' AFTER `id_document_type`"],
            ['column' => 'sale_price', 'ddl' =>
                "ALTER TABLE `ledgers`
                 ADD COLUMN `sale_price` DECIMAL(12,0) NULL DEFAULT NULL
                 COMMENT '販売予定価格（売価・任意。POSレジの単価の初期値）' AFTER `transaction_amount`"],
        ];
    }

    /**
     * 未追加の列名一覧
     *
     * @return string[]
     */
    public static function missingColumns(\PDO $pdo): array
    {
        $have = [];
        foreach ($pdo->query("SHOW COLUMNS FROM `ledgers`")->fetchAll() as $row) {
            $have[(string)($row['Field'] ?? '')] = true;
        }
        $missing = [];
        foreach (self::columnUpgrades() as $u) {
            if (!isset($have[$u['column']])) {
                $missing[] = $u['column'];
            }
        }
        return $missing;
    }

    /**
     * 不足している列を追加する（DDL のためトランザクション外で呼ぶこと）
     *
     * @return int 追加した列の数
     */
    public static function apply(\PDO $pdo): int
    {
        $missing = self::missingColumns($pdo);
        $n = 0;
        foreach (self::columnUpgrades() as $u) {
            if (!in_array($u['column'], $missing, true)) {
                continue;
            }
            try {
                $pdo->exec($u['ddl']);
                $n++;
                self::$columns = null;
            } catch (\PDOException $e) {
                if ((int)($e->errorInfo[1] ?? 0) !== 1060) { // 列が既に存在（並行実行）
                    throw $e;
                }
            }
        }
        return $n;
    }

    /**
     * リクエスト内で1回だけ確認して不足分を追加する。
     * トランザクション中は何もしない。権限不足等で追加できない場合も例外は投げない
     * （列が無い環境では保存時に該当項目だけ省いて動作する: Ledger::hasColumn）。
     */
    public static function ensure(\PDO $pdo): void
    {
        static $checked = false;
        if ($checked || $pdo->inTransaction()) {
            return;
        }
        $checked = true;
        try {
            self::apply($pdo);
        } catch (\Throwable $e) {
            error_log('[furyo-dacho] ledger schema check failed: ' . $e->getMessage());
        }
    }

    /**
     * 列が存在するか（追加できなかった環境での保存・表示の切替用）
     */
    public static function hasColumn(\PDO $pdo, string $column): bool
    {
        if (self::$columns === null) {
            self::$columns = [];
            try {
                foreach ($pdo->query("SHOW COLUMNS FROM `ledgers`")->fetchAll() as $row) {
                    self::$columns[(string)($row['Field'] ?? '')] = true;
                }
            } catch (\Throwable $e) {
                self::$columns = [];
            }
        }
        return isset(self::$columns[$column]);
    }
}
