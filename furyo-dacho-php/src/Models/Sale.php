<?php

namespace FuryoDacho\Models;

/**
 * Sale モデル - 販売記録（在庫管理）
 *
 * 台帳（仕入記録）1件に対して複数回の販売を記録できる。
 * 残在庫 = ledgers.quantity - SUM(sales.quantity)
 */
class Sale extends BaseModel
{
    protected string $table = 'sales';

    private function ensureTable(): void
    {
        $this->pdo->exec(
            "CREATE TABLE IF NOT EXISTS `sales` (
                `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `tenant_id`   INT UNSIGNED    NOT NULL,
                `ledger_id`   BIGINT UNSIGNED NOT NULL,
                `transaction_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT 'POS会計（pos_transactions.id）。台帳画面からの販売はNULL',
                `member_code` VARCHAR(50)     NULL DEFAULT NULL COMMENT '販売先の会員番号（任意）',
                `quantity`    INT UNSIGNED    NOT NULL DEFAULT 1,
                `sale_amount` DECIMAL(12,0)   NULL DEFAULT NULL,
                `sold_at`     DATETIME        NOT NULL,
                `note`        VARCHAR(512)    NULL DEFAULT NULL,
                `created_by`  INT UNSIGNED    NULL DEFAULT NULL,
                `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                INDEX `idx_sales_tenant_sold` (`tenant_id`, `sold_at`),
                INDEX `idx_sales_ledger_id`   (`ledger_id`),
                INDEX `idx_sales_transaction_id` (`transaction_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
              COMMENT='販売記録（在庫管理）'"
        );
    }

    /**
     * @template T
     * @param callable(): T $fn
     * @return T
     */
    private function withTable(callable $fn)
    {
        try {
            return $fn();
        } catch (\PDOException $e) {
            if (($e->errorInfo[0] ?? '') === '42S02' || strpos($e->getMessage(), '1146') !== false) {
                $this->ensureTable();
                return $fn();
            }
            // sales テーブルはあるが member_code / transaction_id 列が無い（マイグレーション未実行）
            // 環境では列を補ってから再実行する。ただし DDL は暗黙コミットを伴うため、
            // トランザクション中は補修せず呼び出し元のエラー処理に任せる
            // （会計・販売登録は開始前に ensureSchema() で補修済みにしている）。
            if ((int)($e->errorInfo[1] ?? 0) === 1054 && !$this->pdo->inTransaction()) {
                if (strpos($e->getMessage(), 'member_code') !== false) {
                    $this->addMemberCodeColumn();
                    return $fn();
                }
                if (strpos($e->getMessage(), 'transaction_id') !== false) {
                    $this->addTransactionIdColumn();
                    return $fn();
                }
            }
            throw $e;
        }
    }

    /**
     * sales テーブルと member_code / transaction_id 列の存在を保証する
     * （トランザクション開始前に呼ぶこと。DDL は暗黙コミットを伴うため）
     */
    public function ensureSchema(): void
    {
        static $ok = false;
        if ($ok || $this->pdo->inTransaction()) {
            return;
        }
        try {
            $cols = [];
            foreach ($this->pdo->query("SHOW COLUMNS FROM `sales`")->fetchAll() as $c) {
                $cols[(string)($c['Field'] ?? '')] = true;
            }
            if (!isset($cols['member_code'])) {
                $this->addMemberCodeColumn();
            }
            if (!isset($cols['transaction_id'])) {
                $this->addTransactionIdColumn();
            }
            $ok = true;
        } catch (\PDOException $e) {
            if (($e->errorInfo[0] ?? '') === '42S02' || strpos($e->getMessage(), '1146') !== false) {
                $this->ensureTable(); // 新規作成時は member_code / transaction_id 列を含む
                $ok = true;
                return;
            }
            // スキーマ確認に失敗しても本処理は継続し、本処理側で通常どおりエラー処理する
        }
    }

    /**
     * transaction_id 列（POS会計との紐付け）を追加する（既に存在する場合は何もしない）
     */
    private function addTransactionIdColumn(): void
    {
        try {
            $this->pdo->exec(PosSchema::salesTransactionColumnDdl());
        } catch (\PDOException $e) {
            if (!in_array((int)($e->errorInfo[1] ?? 0), [1060, 1061], true)) { // 列・索引が既に存在
                throw $e;
            }
        }
    }

    /**
     * member_code 列を追加する（既に存在する場合は何もしない）
     */
    private function addMemberCodeColumn(): void
    {
        try {
            $this->pdo->exec(
                "ALTER TABLE `sales` ADD COLUMN `member_code` VARCHAR(50) NULL DEFAULT NULL
                 COMMENT '販売先の会員番号（任意）' AFTER `ledger_id`"
            );
        } catch (\PDOException $e) {
            if ((int)($e->errorInfo[1] ?? 0) !== 1060) { // 1060 = 列が既に存在
                throw $e;
            }
        }
    }

    /**
     * 販売記録を作成
     */
    public function create(int $tenantId, array $data): int
    {
        return $this->withTable(function () use ($tenantId, $data): int {
            $stmt = $this->pdo->prepare(
                "INSERT INTO `sales`
                    (`tenant_id`, `ledger_id`, `transaction_id`, `member_code`, `quantity`, `sale_amount`, `sold_at`, `note`, `created_by`)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            );
            $stmt->execute([
                $tenantId,
                (int)$data['ledger_id'],
                !empty($data['transaction_id']) ? (int)$data['transaction_id'] : null,
                ($data['member_code'] ?? '') !== '' ? $data['member_code'] : null,
                max(1, (int)$data['quantity']),
                ($data['sale_amount'] ?? '') !== '' ? $data['sale_amount'] : null,
                $data['sold_at'],
                ($data['note'] ?? '') !== '' ? $data['note'] : null,
                $data['created_by'] ?? null,
            ]);
            return (int)$this->pdo->lastInsertId();
        });
    }

    public function findById(int $id, int $tenantId): ?array
    {
        return $this->withTable(function () use ($id, $tenantId): ?array {
            $stmt = $this->pdo->prepare(
                "SELECT * FROM `sales` WHERE `id` = ? AND `tenant_id` = ?"
            );
            $stmt->execute([$id, $tenantId]);
            $row = $stmt->fetch();
            return $row ?: null;
        });
    }

    /**
     * 台帳に紐づく販売記録一覧（記録者名・POSレシート番号付き）
     */
    public function findByLedger(int $ledgerId, int $tenantId): array
    {
        return $this->withTable(function () use ($ledgerId, $tenantId): array {
            try {
                $stmt = $this->pdo->prepare(
                    "SELECT s.*, u.display_name AS created_by_name, t.receipt_no AS pos_receipt_no
                     FROM `sales` s
                     LEFT JOIN `users` u ON u.id = s.created_by
                     LEFT JOIN `pos_transactions` t ON t.id = s.transaction_id AND t.tenant_id = s.tenant_id
                     WHERE s.`ledger_id` = ? AND s.`tenant_id` = ?
                     ORDER BY s.`sold_at` DESC, s.`id` DESC"
                );
                $stmt->execute([$ledgerId, $tenantId]);
                return $stmt->fetchAll();
            } catch (\PDOException $e) {
                // POS テーブル・列が未作成の環境（マイグレーション前）は従来の一覧
                if (!in_array((int)($e->errorInfo[1] ?? 0), [1146, 1054], true)) {
                    throw $e;
                }
            }
            $stmt = $this->pdo->prepare(
                "SELECT s.*, u.display_name AS created_by_name
                 FROM `sales` s
                 LEFT JOIN `users` u ON u.id = s.created_by
                 WHERE s.`ledger_id` = ? AND s.`tenant_id` = ?
                 ORDER BY s.`sold_at` DESC, s.`id` DESC"
            );
            $stmt->execute([$ledgerId, $tenantId]);
            return $stmt->fetchAll();
        });
    }

    /**
     * トランザクション内で台帳行をまとめてロックし、各台帳の仕入数と販売済数を返す
     *
     * 在庫を変える処理（POS会計・販売追加・販売修正・台帳の数量変更）は、必ず先に
     * この方法で対象台帳の行ロックを取る。これにより複数端末で同時に処理しても、
     * 後続の処理は先行処理のコミット後の販売数で検証される（在庫超過の防止）。
     *
     * 実装上の注意:
     * - 台帳行は1つのSQLで ID の昇順にロックする（端末間でロック順が揃いデッドロックしない）。
     * - 販売数の合計はロック取得「後」に通常の（ロックしない）SELECT で読む。
     *   REPEATABLE READ では最初の通常SELECTの時点でスナップショットが作られるため、
     *   全ロック取得後に読めば先行処理のコミット済みの販売も見える。
     *   （以前は SUM ... FOR UPDATE で販売テーブルにギャップロックを掛けており、
     *     別の商品・別テナントの同時会計どうしでもデッドロックしていた）
     * - そのため、トランザクション開始後はこのメソッドより前に通常の SELECT を実行しないこと。
     *
     * @param int[] $ledgerIds
     * @return array<int, array{quantity:int, sold:int}> 台帳ID => 状態（存在しない・削除済みは含まない）
     */
    public function lockLedgers(array $ledgerIds, int $tenantId): array
    {
        $ids = array_values(array_unique(array_map('intval', $ledgerIds)));
        $ids = array_values(array_filter($ids, static fn (int $i): bool => $i > 0));
        if ($ids === []) {
            return [];
        }
        sort($ids);
        $ph = implode(',', array_fill(0, count($ids), '?'));

        // 主キーで行を特定させ、対象の台帳行だけをロックする
        // （tenant_id の索引が選ばれると、テナントの全台帳と隙間までロックされ同時処理が詰まる）
        $stmt = $this->pdo->prepare(
            "SELECT `id`, `quantity` FROM `ledgers` FORCE INDEX (PRIMARY)
             WHERE `tenant_id` = ? AND `deleted_at` IS NULL AND `id` IN ($ph)
             ORDER BY `id` ASC
             FOR UPDATE"
        );
        $stmt->execute(array_merge([$tenantId], $ids));

        $state = [];
        foreach ($stmt->fetchAll() as $row) {
            $state[(int)$row['id']] = ['quantity' => (int)$row['quantity'], 'sold' => 0];
        }
        if ($state === []) {
            return [];
        }

        $lockedIds = array_keys($state);
        $ph2  = implode(',', array_fill(0, count($lockedIds), '?'));
        $sum  = $this->pdo->prepare(
            "SELECT `ledger_id`, COALESCE(SUM(`quantity`), 0) AS sold FROM `sales`
             WHERE `tenant_id` = ? AND `ledger_id` IN ($ph2)
             GROUP BY `ledger_id`"
        );
        $sum->execute(array_merge([$tenantId], $lockedIds));
        foreach ($sum->fetchAll() as $row) {
            $state[(int)$row['ledger_id']]['sold'] = (int)$row['sold'];
        }

        return $state;
    }

    /**
     * 台帳の販売済み数量合計
     */
    public function soldQuantity(int $ledgerId, int $tenantId): int
    {
        return $this->withTable(function () use ($ledgerId, $tenantId): int {
            $stmt = $this->pdo->prepare(
                "SELECT COALESCE(SUM(`quantity`), 0) FROM `sales`
                 WHERE `ledger_id` = ? AND `tenant_id` = ?"
            );
            $stmt->execute([$ledgerId, $tenantId]);
            return (int)$stmt->fetchColumn();
        });
    }

    /**
     * 販売記録を更新（修正）
     */
    public function update(int $id, int $tenantId, array $data): bool
    {
        return $this->withTable(function () use ($id, $tenantId, $data): bool {
            $stmt = $this->pdo->prepare(
                "UPDATE `sales` SET
                    `member_code` = ?, `quantity` = ?, `sale_amount` = ?, `sold_at` = ?, `note` = ?
                 WHERE `id` = ? AND `tenant_id` = ?"
            );
            return $stmt->execute([
                ($data['member_code'] ?? '') !== '' ? $data['member_code'] : null,
                max(1, (int)$data['quantity']),
                ($data['sale_amount'] ?? '') !== '' ? $data['sale_amount'] : null,
                $data['sold_at'],
                ($data['note'] ?? '') !== '' ? $data['note'] : null,
                $id,
                $tenantId,
            ]);
        });
    }

    public function delete(int $id, int $tenantId): bool
    {
        return $this->withTable(function () use ($id, $tenantId): bool {
            $stmt = $this->pdo->prepare(
                "DELETE FROM `sales` WHERE `id` = ? AND `tenant_id` = ?"
            );
            return $stmt->execute([$id, $tenantId]);
        });
    }

    /**
     * 売上推移の集計
     *
     * @param string $granularity day|week|month|year
     * @return array<int, array{period: string, total: string, cnt: int, qty: int}>
     */
    public function aggregate(int $tenantId, string $from, string $to, string $granularity): array
    {
        $expr = self::periodExpr('s.`sold_at`', $granularity);
        return $this->withTable(function () use ($tenantId, $from, $to, $expr): array {
            $stmt = $this->pdo->prepare(
                "SELECT {$expr} AS period,
                        COALESCE(SUM(s.`sale_amount`), 0) AS total,
                        COUNT(*) AS cnt,
                        COALESCE(SUM(s.`quantity`), 0) AS qty
                 FROM `sales` s
                 WHERE s.`tenant_id` = ? AND s.`sold_at` >= ? AND s.`sold_at` < DATE_ADD(?, INTERVAL 1 DAY)
                 GROUP BY period
                 ORDER BY period ASC"
            );
            $stmt->execute([$tenantId, $from . ' 00:00:00', $to]);
            return $stmt->fetchAll();
        });
    }

    /**
     * 仕入（台帳）推移の集計
     */
    public function aggregatePurchases(int $tenantId, string $from, string $to, string $granularity): array
    {
        $expr = self::periodExpr('l.`transaction_date`', $granularity);
        $stmt = $this->pdo->prepare(
            "SELECT {$expr} AS period,
                    COALESCE(SUM(l.`transaction_amount`), 0) AS total,
                    COUNT(*) AS cnt,
                    COALESCE(SUM(l.`quantity`), 0) AS qty
             FROM `ledgers` l
             WHERE l.`tenant_id` = ? AND l.`deleted_at` IS NULL
               AND l.`transaction_date` >= ? AND l.`transaction_date` <= ?
             GROUP BY period
             ORDER BY period ASC"
        );
        $stmt->execute([$tenantId, $from, $to]);
        return $stmt->fetchAll();
    }

    /**
     * 期間粒度ごとの GROUP BY 式（ラベルにもなる）
     */
    public static function periodExpr(string $column, string $granularity): string
    {
        switch ($granularity) {
            case 'year':
                return "DATE_FORMAT({$column}, '%Y')";
            case 'month':
                return "DATE_FORMAT({$column}, '%Y-%m')";
            case 'week':
                // 週の開始日（月曜）をラベルにする
                return "DATE_FORMAT(DATE_SUB(DATE({$column}), INTERVAL WEEKDAY({$column}) DAY), '%Y-%m-%d')";
            case 'day':
            default:
                return "DATE_FORMAT({$column}, '%Y-%m-%d')";
        }
    }

    /**
     * POS用: 在庫のある台帳を検索（残数付き）
     *
     * - 品名・シリアル番号の部分一致。数字（「#123」「L123」も可）は台帳番号としても照合する。
     * - $exact = true のとき（バーコード読取・Enter確定）はシリアル番号の完全一致と
     *   台帳番号の一致のみを返す（部分一致で別商品を拾わないため）。
     * - LIKE のワイルドカード（% _）は文字として扱う（以前は「_」で全件に一致していた）。
     */
    public function searchInStock(int $tenantId, string $keyword = '', int $limit = 30, bool $exact = false): array
    {
        return $this->withTable(function () use ($tenantId, $keyword, $limit, $exact): array {
            // 販売予定価格（2026-10-26 追加列）。列が無い環境では NULL として返す
            $salePriceCol = LedgerSchema::hasColumn($this->pdo, 'sale_price') ? 'l.`sale_price`' : 'NULL';
            $sql = "SELECT l.`id`, l.`item_name`, l.`serial_number`, l.`quantity`,
                           l.`transaction_amount`, l.`transaction_date`, l.`approval_status`,
                           {$salePriceCol} AS sale_price,
                           COALESCE(s.sold_qty, 0) AS sold_quantity,
                           (l.`quantity` - COALESCE(s.sold_qty, 0)) AS remaining
                    FROM `ledgers` l
                    LEFT JOIN (
                        SELECT `ledger_id`, SUM(`quantity`) AS sold_qty
                        FROM `sales` WHERE `tenant_id` = ? GROUP BY `ledger_id`
                    ) s ON s.`ledger_id` = l.`id`
                    WHERE l.`tenant_id` = ? AND l.`deleted_at` IS NULL
                      AND (l.`quantity` - COALESCE(s.sold_qty, 0)) > 0";
            $params = [$tenantId, $tenantId];

            $idCandidate = 0;
            if (preg_match('/^(?:#|L|l)?0*([1-9][0-9]{0,17})$/', $keyword, $m)) {
                $idCandidate = (int)$m[1];
            }

            if ($keyword !== '') {
                if ($exact) {
                    $sql .= " AND (l.`serial_number` = ?" . ($idCandidate > 0 ? " OR l.`id` = ?" : '') . ")";
                    $params[] = $keyword;
                } else {
                    $like = '%' . strtr($keyword, ['\\' => '\\\\', '%' => '\\%', '_' => '\\_']) . '%';
                    $sql .= " AND (l.`item_name` LIKE ? OR l.`serial_number` LIKE ?" . ($idCandidate > 0 ? " OR l.`id` = ?" : '') . ")";
                    $params[] = $like;
                    $params[] = $like;
                }
                if ($idCandidate > 0) {
                    $params[] = $idCandidate;
                }
            }

            $sql .= " ORDER BY l.`id` DESC LIMIT " . max(1, min(100, $limit));
            $stmt = $this->pdo->prepare($sql);
            $stmt->execute($params);
            return $stmt->fetchAll();
        });
    }
}
