<?php

namespace FuryoDacho\Models;

/**
 * Ledger モデル
 * 古物台帳の CRUD 操作を担当する。
 * 削除は論理削除（deleted_at）のみ。全操作に tenant_id を強制する。
 * 過去年度データの変更・削除は禁止（古物営業法準拠）。
 */
class Ledger extends BaseModel
{
    protected string $table = 'ledgers';

    public function __construct(\PDO $pdo)
    {
        parent::__construct($pdo);
        // 後から追加した列（本人確認書類「その他」の内容・販売予定価格）を未適用環境でも補う
        LedgerSchema::ensure($pdo);
    }

    /**
     * 後から追加した任意列（列が無い環境では保存しない）の値を組み立てる
     *
     * @return array<string, mixed> 列名 => 値
     */
    private function optionalColumnValues(array $data): array
    {
        $values = [];
        if (LedgerSchema::hasColumn($this->pdo, 'id_document_type_note')) {
            $note = trim((string)($data['id_document_type_note'] ?? ''));
            // 「その他」以外では補足を保存しない（種別を変えた後に古い補足が残らないように）
            $values['id_document_type_note'] = (($data['id_document_type'] ?? '') === 'other' && $note !== '') ? $note : null;
        }
        if (LedgerSchema::hasColumn($this->pdo, 'sale_price')) {
            $price = trim((string)($data['sale_price'] ?? ''));
            $values['sale_price'] = $price !== '' ? (int)$price : null;
        }
        return $values;
    }

    /**
     * 台帳一覧を取得（複合フィルタ + ページネーション）
     *
     * @param int   $tenantId
     * @param array $filters  使用可能キー:
     *                        date_from, date_to, item_category, transaction_type,
     *                        item_name, counterpart_name, registered_by_id,
     *                        branch_id, fiscal_year
     * @param int   $page
     * @param int   $perPage
     * @return array ['records' => array, 'total' => int]
     */
    public function findAll(int $tenantId, array $filters = [], int $page = 1, int $perPage = 50): array
    {
        try {
            return $this->findAllInner($tenantId, $filters, $page, $perPage);
        } catch (\PDOException $e) {
            // sales テーブル未作成環境（マイグレーション未実行）でも一覧が落ちないよう自動作成
            if (($e->errorInfo[0] ?? '') === '42S02' || strpos($e->getMessage(), '1146') !== false) {
                $this->pdo->exec(
                    "CREATE TABLE IF NOT EXISTS `sales` (
                        `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        `tenant_id`   INT UNSIGNED    NOT NULL,
                        `ledger_id`   BIGINT UNSIGNED NOT NULL,
                        `member_code` VARCHAR(50)     NULL DEFAULT NULL,
                        `quantity`    INT UNSIGNED    NOT NULL DEFAULT 1,
                        `sale_amount` DECIMAL(12,0)   NULL DEFAULT NULL,
                        `sold_at`     DATETIME        NOT NULL,
                        `note`        VARCHAR(512)    NULL DEFAULT NULL,
                        `created_by`  INT UNSIGNED    NULL DEFAULT NULL,
                        `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (`id`),
                        INDEX `idx_sales_tenant_sold` (`tenant_id`, `sold_at`),
                        INDEX `idx_sales_ledger_id`   (`ledger_id`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
                );
                return $this->findAllInner($tenantId, $filters, $page, $perPage);
            }
            throw $e;
        }
    }

    private function findAllInner(int $tenantId, array $filters = [], int $page = 1, int $perPage = 50): array
    {
        $where  = ['l.tenant_id = ?', 'l.deleted_at IS NULL'];
        $params = [$tenantId];

        if (!empty($filters['date_from'])) {
            $where[]  = 'l.transaction_date >= ?';
            $params[] = $filters['date_from'];
        }
        if (!empty($filters['date_to'])) {
            $where[]  = 'l.transaction_date <= ?';
            $params[] = $filters['date_to'];
        }
        if (!empty($filters['item_category'])) {
            $where[]  = 'l.item_category = ?';
            $params[] = $filters['item_category'];
        }
        if (!empty($filters['transaction_type'])) {
            $where[]  = 'l.transaction_type = ?';
            $params[] = $filters['transaction_type'];
        }
        // 部分一致検索。「%」「_」は文字として検索する（以前は「_」だけで全件に一致していた）
        $like = static fn ($v): string => '%' . strtr((string)$v, ['\\' => '\\\\', '%' => '\\%', '_' => '\\_']) . '%';
        if (!empty($filters['item_name']) && is_string($filters['item_name'])) {
            $where[]  = 'l.item_name LIKE ?';
            $params[] = $like($filters['item_name']);
        }
        if (!empty($filters['counterpart_name']) && is_string($filters['counterpart_name'])) {
            $where[]  = 'l.counterpart_name LIKE ?';
            $params[] = $like($filters['counterpart_name']);
        }
        if (!empty($filters['serial_number']) && is_string($filters['serial_number'])) {
            $where[]  = 'l.serial_number LIKE ?';
            $params[] = $like($filters['serial_number']);
        }
        if (!empty($filters['approval_status'])
            && in_array($filters['approval_status'], ['pending', 'approved'], true)) {
            $where[]  = 'l.approval_status = ?';
            $params[] = $filters['approval_status'];
        }
        if (!empty($filters['registered_by_id'])) {
            $where[]  = 'l.registered_by = ?';
            $params[] = (int)$filters['registered_by_id'];
        }
        if (!empty($filters['branch_id'])) {
            $where[]  = 'l.branch_id = ?';
            $params[] = (int)$filters['branch_id'];
        }
        if (!empty($filters['fiscal_year'])) {
            $where[]  = 'l.fiscal_year = ?';
            $params[] = (int)$filters['fiscal_year'];
        }

        // 後方互換: transaction_date_from / transaction_date_to キーにも対応
        if (empty($filters['date_from']) && !empty($filters['transaction_date_from'])) {
            $where[]  = 'l.transaction_date >= ?';
            $params[] = $filters['transaction_date_from'];
        }
        if (empty($filters['date_to']) && !empty($filters['transaction_date_to'])) {
            $where[]  = 'l.transaction_date <= ?';
            $params[] = $filters['transaction_date_to'];
        }

        $whereClause = implode(' AND ', $where);
        $offset      = ($page - 1) * $perPage;

        // 総件数を取得
        $countSql = "SELECT COUNT(*) FROM `ledgers` l WHERE {$whereClause}";
        $countStmt = $this->pdo->prepare($countSql);
        $countStmt->execute($params);
        $total = (int)$countStmt->fetchColumn();

        // レコード取得
        $sql = "SELECT l.*,
                       b.name AS branch_name,
                       u.display_name AS registered_by_name,
                       COALESCE(sq.sold_qty, 0) AS sold_quantity
                FROM `ledgers` l
                LEFT JOIN `branches` b ON b.id = l.branch_id
                LEFT JOIN `users`    u ON u.id  = l.registered_by
                LEFT JOIN (
                    SELECT `ledger_id`, SUM(`quantity`) AS sold_qty
                    FROM `sales` GROUP BY `ledger_id`
                ) sq ON sq.`ledger_id` = l.id
                WHERE {$whereClause}
                ORDER BY l.transaction_date DESC, l.id DESC
                LIMIT ? OFFSET ?";

        $params[] = $perPage;
        $params[] = $offset;

        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);
        $records = $stmt->fetchAll();

        return ['records' => $records, 'total' => $total];
    }

    /**
     * 後方互換: getByTenant() は findAll() のレコード配列を返す
     */
    public function getByTenant(int $tenantId, array $filters = [], int $perPage = 50, int $page = 1): array
    {
        $result = $this->findAll($tenantId, $filters, $page, $perPage);
        return $result['records'];
    }

    /**
     * IDとテナントIDで台帳を取得
     *
     * @param int $id
     * @param int $tenantId
     * @return array|null
     */
    public function findById(int $id, int $tenantId): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT l.*,
                    b.name AS branch_name,
                    u.display_name AS registered_by_name,
                    uu.display_name AS updated_by_name,
                    MAX(CASE WHEN lf.file_type = 'id_document'      THEN 1 END) AS has_id_document,
                    MAX(CASE WHEN lf.file_type = 'purchase_receipt' THEN 1 END) AS has_receipt_form
             FROM `ledgers` l
             LEFT JOIN `branches`     b  ON b.id  = l.branch_id
             LEFT JOIN `users`        u  ON u.id  = l.registered_by
             LEFT JOIN `users`        uu ON uu.id = l.updated_by
             LEFT JOIN `ledger_files` lf ON lf.ledger_id = l.id
             WHERE l.id = ? AND l.tenant_id = ? AND l.deleted_at IS NULL
             GROUP BY l.id, b.name, u.display_name, uu.display_name"
        );
        $stmt->execute([$id, $tenantId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    /**
     * 台帳を作成
     * fiscal_year は transaction_date から自動計算する（4月始まり）。
     *
     * @param int   $tenantId
     * @param array $data
     * @return int 生成されたID
     */
    public function create(int $tenantId, array $data): int
    {
        $fiscalYear = $this->getFiscalYear($data['transaction_date']);

        $stmt = $this->pdo->prepare(
            "INSERT INTO `ledgers` (
                `tenant_id`, `branch_id`, `transaction_date`, `transaction_type`, `transaction_type_note`,
                `item_category`, `item_category_note`, `item_name`, `serial_number`, `item_description`, `quantity`, `transaction_amount`,
                `member_code`, `counterpart_type`,
                `counterpart_name`, `counterpart_address`, `counterpart_occupation`, `counterpart_age`, `counterpart_phone`,
                `counterpart_contact_name`, `counterpart_account`, `counterpart_note`,
                `id_document_type`, `id_document_number`,
                `registered_by`, `updated_by`, `fiscal_year`
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        $stmt->execute([
            $tenantId,
            $data['branch_id'],
            $data['transaction_date'],
            $data['transaction_type'],
            $data['transaction_type_note'] ?? null,
            $data['item_category'],
            $data['item_category'] === 'other' ? ($data['item_category_note'] ?? null) : null,
            $data['item_name'],
            ($data['serial_number'] ?? '') !== '' ? $data['serial_number'] : null,
            $data['item_description'] ?? null,
            (int)($data['quantity'] ?? 1),
            $data['transaction_amount'] ?? null,
            ($data['member_code'] ?? '') !== '' ? $data['member_code'] : null,
            ($data['counterpart_type'] ?? '') === 'corporate' ? 'corporate' : 'individual',
            $data['counterpart_name'],
            $data['counterpart_address'],
            ($data['counterpart_occupation'] ?? '') !== '' ? $data['counterpart_occupation'] : null,
            ($data['counterpart_age'] ?? '') !== '' ? (int)$data['counterpart_age'] : null,
            ($data['counterpart_phone'] ?? '') !== '' ? $data['counterpart_phone'] : null,
            ($data['counterpart_contact_name'] ?? '') !== '' ? $data['counterpart_contact_name'] : null,
            ($data['counterpart_account'] ?? '') !== '' ? $data['counterpart_account'] : null,
            ($data['counterpart_note'] ?? '') !== '' ? $data['counterpart_note'] : null,
            ($data['id_document_type'] ?? '') !== '' ? $data['id_document_type'] : null,
            ($data['id_document_number'] ?? '') !== '' ? $data['id_document_number'] : null,
            $data['registered_by'],
            $data['registered_by'],
            $fiscalYear,
        ]);
        $newId = (int)$this->pdo->lastInsertId();

        // 後から追加した任意列は、列が存在する場合のみ保存する
        $optional = $this->optionalColumnValues($data);
        if (!empty($optional)) {
            $sets = implode(', ', array_map(static fn ($c) => "`{$c}` = ?", array_keys($optional)));
            $this->pdo->prepare("UPDATE `ledgers` SET {$sets} WHERE `id` = ? AND `tenant_id` = ?")
                ->execute(array_merge(array_values($optional), [$newId, $tenantId]));
        }

        return $newId;
    }

    /**
     * 台帳を更新
     * - role=admin: 全件更新可
     * - role=user: 自分のレコードのみ（registered_by === $userId）
     * - 現在年度以外（過去年度）のレコードは更新不可
     *
     * @param int    $id
     * @param int    $tenantId
     * @param int    $userId
     * @param string $role      'admin' or 'user'
     * @param array  $data
     * @return bool
     * @throws \RuntimeException 権限不足または過去年度データの場合
     */
    public function update(int $id, int $tenantId, int $userId, string $role, array $data): bool
    {
        // 既存レコードを取得
        $existing = $this->findById($id, $tenantId);
        if ($existing === null) {
            throw new \RuntimeException('台帳が見つかりません。');
        }

        // 過去年度データ保護
        $currentFiscalYear = $this->getFiscalYear(date('Y-m-d'));
        if ((int)$existing['fiscal_year'] !== $currentFiscalYear) {
            throw new \RuntimeException('過去年度のデータは編集できません。');
        }

        // ロールによるアクセス制御
        if ($role !== 'admin' && (int)$existing['registered_by'] !== $userId) {
            throw new \RuntimeException('自分が登録したレコードのみ編集できます。');
        }

        // 在庫整合性: 数量は販売済数を下回る値に変更できない
        // （下回ると残在庫が負になり、在庫管理・POSの検証が破綻するため）。
        // 同時に POS 等で販売されても破綻しないよう、台帳行をロックしてから最新の
        // 販売数で検証し、そのまま更新する（Sale::lockLedgers と同じ手順）。
        $newQty = (int)($data['quantity'] ?? 1);
        $ownTx  = !$this->pdo->inTransaction();
        if ($ownTx) {
            $this->pdo->beginTransaction();
        }
        try {
            $lock = $this->pdo->prepare(
                "SELECT `quantity` FROM `ledgers`
                 WHERE `id` = ? AND `tenant_id` = ? AND `deleted_at` IS NULL
                 FOR UPDATE"
            );
            $lock->execute([$id, $tenantId]);
            if ($lock->fetchColumn() === false) {
                throw new \RuntimeException('台帳が見つかりません。');
            }
            try {
                // ロック取得後の通常SELECT（＝最新のコミット済み販売数を読む）
                $soldStmt = $this->pdo->prepare(
                    "SELECT COALESCE(SUM(`quantity`), 0) FROM `sales` WHERE `ledger_id` = ? AND `tenant_id` = ?"
                );
                $soldStmt->execute([$id, $tenantId]);
                $soldQty = (int)$soldStmt->fetchColumn();
            } catch (\PDOException $e) {
                // sales テーブル未作成環境では販売ゼロとして扱う
                $soldQty = 0;
            }
            if ($newQty < $soldQty) {
                throw new \RuntimeException('数量を販売済数（' . $soldQty . '点）より小さくすることはできません。先に販売記録を調整してください。');
            }

            // 取引日を変更した場合に年度がズレたままにならないよう再計算する
            $fiscalYear = $this->getFiscalYear($data['transaction_date']);

            // branch_id はフォーム未指定の場合は既存値を維持
            $branchId = !empty($data['branch_id'])
                ? (int)$data['branch_id']
                : (int)$existing['branch_id'];

            $stmt = $this->pdo->prepare(
                "UPDATE `ledgers` SET
                    `branch_id` = ?,
                    `transaction_date` = ?, `transaction_type` = ?, `transaction_type_note` = ?,
                    `item_category` = ?, `item_category_note` = ?, `item_name` = ?, `serial_number` = ?, `item_description` = ?,
                    `quantity` = ?, `transaction_amount` = ?,
                    `member_code` = ?, `counterpart_type` = ?,
                    `counterpart_name` = ?, `counterpart_address` = ?,
                    `counterpart_occupation` = ?, `counterpart_age` = ?, `counterpart_phone` = ?,
                    `counterpart_contact_name` = ?, `counterpart_account` = ?, `counterpart_note` = ?,
                    `id_document_type` = ?, `id_document_number` = ?,
                    `fiscal_year` = ?,
                    `updated_by` = ?, `updated_at` = NOW()
                 WHERE `id` = ? AND `tenant_id` = ? AND `deleted_at` IS NULL"
            );
            $ok = $stmt->execute([
                $branchId,
                $data['transaction_date'],
                $data['transaction_type'],
                $data['transaction_type_note'] ?? null,
                $data['item_category'],
                $data['item_category'] === 'other' ? ($data['item_category_note'] ?? null) : null,
                $data['item_name'],
                ($data['serial_number'] ?? '') !== '' ? $data['serial_number'] : null,
                $data['item_description'] ?? null,
                (int)($data['quantity'] ?? 1),
                $data['transaction_amount'] ?? null,
                ($data['member_code'] ?? '') !== '' ? $data['member_code'] : null,
                ($data['counterpart_type'] ?? '') === 'corporate' ? 'corporate' : 'individual',
                $data['counterpart_name'],
                $data['counterpart_address'],
                ($data['counterpart_occupation'] ?? '') !== '' ? $data['counterpart_occupation'] : null,
                ($data['counterpart_age'] ?? '') !== '' ? (int)$data['counterpart_age'] : null,
                ($data['counterpart_phone'] ?? '') !== '' ? $data['counterpart_phone'] : null,
                ($data['counterpart_contact_name'] ?? '') !== '' ? $data['counterpart_contact_name'] : null,
                ($data['counterpart_account'] ?? '') !== '' ? $data['counterpart_account'] : null,
                ($data['counterpart_note'] ?? '') !== '' ? $data['counterpart_note'] : null,
                ($data['id_document_type'] ?? '') !== '' ? $data['id_document_type'] : null,
                ($data['id_document_number'] ?? '') !== '' ? $data['id_document_number'] : null,
                $fiscalYear,
                $userId,
                $id,
                $tenantId,
            ]);

            $optional = $this->optionalColumnValues($data);
            if ($ok && !empty($optional)) {
                $sets = implode(', ', array_map(static fn ($c) => "`{$c}` = ?", array_keys($optional)));
                $this->pdo->prepare("UPDATE `ledgers` SET {$sets} WHERE `id` = ? AND `tenant_id` = ? AND `deleted_at` IS NULL")
                    ->execute(array_merge(array_values($optional), [$id, $tenantId]));
            }

            if ($ownTx) {
                $this->pdo->commit();
            }
            return $ok;
        } catch (\Throwable $e) {
            if ($ownTx && $this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $e;
        }
    }

    /**
     * 台帳を論理削除
     * 削除前の値を監査ログ用に返すため、before_value として既存レコードを返す。
     *
     * @param int $id
     * @param int $tenantId
     * @param int $userId
     * @return bool
     * @throws \RuntimeException 対象が存在しない場合
     */
    public function softDelete(int $id, int $tenantId, int $userId): bool
    {
        $existing = $this->findById($id, $tenantId);
        if ($existing === null) {
            throw new \RuntimeException('台帳が見つかりません。');
        }

        $stmt = $this->pdo->prepare(
            "UPDATE `ledgers`
             SET `deleted_at` = NOW(), `updated_by` = ?, `updated_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ? AND `deleted_at` IS NULL"
        );
        return $stmt->execute([$userId, $id, $tenantId]);
    }

    /**
     * テナントの台帳総件数を取得
     *
     * @param int   $tenantId
     * @param array $filters
     * @return int
     */
    public function countByTenant(int $tenantId, array $filters = []): int
    {
        $where  = ['tenant_id = ?', 'deleted_at IS NULL'];
        $params = [$tenantId];

        if (!empty($filters['branch_id'])) {
            $where[]  = 'branch_id = ?';
            $params[] = (int)$filters['branch_id'];
        }
        if (!empty($filters['fiscal_year'])) {
            $where[]  = 'fiscal_year = ?';
            $params[] = (int)$filters['fiscal_year'];
        }
        if (!empty($filters['transaction_date_from'])) {
            $where[]  = 'transaction_date >= ?';
            $params[] = $filters['transaction_date_from'];
        }
        if (!empty($filters['transaction_date_to'])) {
            $where[]  = 'transaction_date <= ?';
            $params[] = $filters['transaction_date_to'];
        }

        $whereClause = implode(' AND ', $where);
        $stmt = $this->pdo->prepare("SELECT COUNT(*) FROM `ledgers` WHERE {$whereClause}");
        $stmt->execute($params);
        return (int)$stmt->fetchColumn();
    }

    /**
     * 会計年度を算出する（4月始まり）
     * 例: 2024-03-31 → 2023, 2024-04-01 → 2024
     *
     * @param string $date Y-m-d 形式の日付
     * @return int 会計年度（西暦）
     */
    public function getFiscalYear(string $date): int
    {
        $month = (int)date('n', strtotime($date));
        $year  = (int)date('Y', strtotime($date));
        return $month >= 4 ? $year : $year - 1;
    }

    /**
     * テナントに存在する年度一覧を取得（過去データ閲覧用プルダウン）
     *
     * @param int $tenantId
     * @return array int[] 降順
     */
    public function getYears(int $tenantId): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT DISTINCT `fiscal_year`
             FROM `ledgers`
             WHERE `tenant_id` = ? AND `deleted_at` IS NULL
             ORDER BY `fiscal_year` DESC"
        );
        $stmt->execute([$tenantId]);
        return $stmt->fetchAll(\PDO::FETCH_COLUMN);
    }

    /**
     * 今月の登録件数を取得（ダッシュボード用）
     *
     * @param int $tenantId
     * @return int
     */
    public function countThisMonth(int $tenantId): int
    {
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) FROM `ledgers`
             WHERE `tenant_id` = ? AND `deleted_at` IS NULL
               AND `transaction_date` >= DATE_FORMAT(NOW(), '%Y-%m-01')
               AND `transaction_date` < DATE_FORMAT(DATE_ADD(NOW(), INTERVAL 1 MONTH), '%Y-%m-01')"
        );
        $stmt->execute([$tenantId]);
        return (int)$stmt->fetchColumn();
    }

    /**
     * 最近の登録レコードを取得（ダッシュボード用）
     *
     * @param int $tenantId
     * @param int $limit
     * @return array
     */
    public function getRecent(int $tenantId, int $limit = 5): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT l.*,
                    b.name AS branch_name,
                    u.display_name AS registered_by_name
             FROM `ledgers` l
             LEFT JOIN `branches` b ON b.id = l.branch_id
             LEFT JOIN `users`    u ON u.id = l.registered_by
             WHERE l.tenant_id = ? AND l.deleted_at IS NULL
             ORDER BY l.created_at DESC, l.id DESC
             LIMIT ?"
        );
        $stmt->execute([$tenantId, $limit]);
        return $stmt->fetchAll();
    }
}
