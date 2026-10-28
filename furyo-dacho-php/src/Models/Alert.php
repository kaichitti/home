<?php

namespace FuryoDacho\Models;

/**
 * Alert モデル
 * 重複検知アラートの管理を担当する。
 */
class Alert extends BaseModel
{
    protected string $table = 'alerts';

    /**
     * テナントのアラート一覧を取得（ビュー表示用カラム付き）
     *
     * @param int         $tenantId
     * @param string|null $status   指定した場合そのステータスのみ取得
     * @return array
     */
    public function findAll(int $tenantId, ?string $status = null, ?int $limit = null, int $offset = 0): array
    {
        $where  = ['a.tenant_id = ?'];
        $params = [$tenantId];

        if ($status !== null) {
            $where[]  = 'a.status = ?';
            $params[] = $status;
        }

        $whereClause = implode(' AND ', $where);

        $sql = "SELECT
                    a.*,
                    l1.id              AS record_a_id,
                    l1.item_name       AS record_a_item_name,
                    l1.transaction_amount AS record_a_price,
                    l1.created_at      AS record_a_created_at,
                    u1.display_name    AS record_a_created_by,
                    l2.id              AS record_b_id,
                    l2.item_name       AS record_b_item_name,
                    l2.transaction_amount AS record_b_price,
                    l2.created_at      AS record_b_created_at,
                    u2.display_name    AS record_b_created_by,
                    uc.display_name    AS confirmed_by_name
                FROM `alerts` a
                LEFT JOIN `ledgers` l1 ON l1.id = a.ledger_id_1
                LEFT JOIN `ledgers` l2 ON l2.id = a.ledger_id_2
                LEFT JOIN `users`   u1 ON u1.id = l1.registered_by
                LEFT JOIN `users`   u2 ON u2.id = l2.registered_by
                LEFT JOIN `users`   uc ON uc.id = a.confirmed_by
                WHERE {$whereClause}
                ORDER BY a.created_at DESC";

        if ($limit !== null) {
            $sql .= ' LIMIT ' . (int)$limit . ' OFFSET ' . (int)$offset;
        }

        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);
        return $stmt->fetchAll();
    }

    /**
     * 条件に合致するアラート件数（ページネーション用）
     */
    public function countAll(int $tenantId, ?string $status = null): int
    {
        $where  = ['tenant_id = ?'];
        $params = [$tenantId];

        if ($status !== null) {
            $where[]  = 'status = ?';
            $params[] = $status;
        }

        $sql  = 'SELECT COUNT(*) FROM `alerts` WHERE ' . implode(' AND ', $where);
        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($params);
        return (int)$stmt->fetchColumn();
    }

    /**
     * 後方互換: getByTenant() は findAll() に委譲
     */
    public function getByTenant(int $tenantId, ?string $status = null): array
    {
        return $this->findAll($tenantId, $status);
    }

    /**
     * 未確認アラート件数を取得（ダッシュボード・サイドバーバッジ用）
     *
     * @param int $tenantId
     * @return int
     */
    public function findUnconfirmedCount(int $tenantId): int
    {
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) FROM `alerts`
             WHERE `tenant_id` = ? AND `status` = 'unconfirmed'"
        );
        $stmt->execute([$tenantId]);
        return (int)$stmt->fetchColumn();
    }

    /**
     * 後方互換: countUnconfirmed() は findUnconfirmedCount() に委譲
     */
    public function countUnconfirmed(int $tenantId): int
    {
        return $this->findUnconfirmedCount($tenantId);
    }

    /**
     * アラートを作成する。同一ペアが既に存在する場合はスキップして 0 を返す。
     *
     * @param int $tenantId
     * @param int $ledgerId1
     * @param int $ledgerId2
     * @return int 生成されたID（既存の場合は 0）
     */
    public function createIfNotExists(int $tenantId, int $ledgerId1, int $ledgerId2): int
    {
        // 小さい方を ledger_id_1 に統一して重複チェックの一意性を確保
        if ($ledgerId1 > $ledgerId2) {
            [$ledgerId1, $ledgerId2] = [$ledgerId2, $ledgerId1];
        }

        // 既存チェック
        $check = $this->pdo->prepare(
            "SELECT `id` FROM `alerts`
             WHERE `tenant_id` = ? AND `ledger_id_1` = ? AND `ledger_id_2` = ?
             LIMIT 1"
        );
        $check->execute([$tenantId, $ledgerId1, $ledgerId2]);
        if ($check->fetchColumn() !== false) {
            return 0;
        }

        $stmt = $this->pdo->prepare(
            "INSERT INTO `alerts` (`tenant_id`, `ledger_id_1`, `ledger_id_2`)
             VALUES (?, ?, ?)"
        );
        $stmt->execute([$tenantId, $ledgerId1, $ledgerId2]);
        return (int)$this->pdo->lastInsertId();
    }

    /**
     * 後方互換: create() は旧シグネチャ（配列形式）を維持しつつ createIfNotExists() に委譲
     *
     * @param array $data  ['tenant_id', 'ledger_id_1', 'ledger_id_2']
     * @return int 生成されたID
     */
    public function create(array $data): int
    {
        return $this->createIfNotExists(
            (int)$data['tenant_id'],
            (int)$data['ledger_id_1'],
            (int)$data['ledger_id_2']
        );
    }

    /**
     * アラートを確認済みにする
     *
     * @param int $id
     * @param int $tenantId
     * @param int $confirmedBy
     * @return bool
     */
    public function confirm(int $id, int $tenantId, int $confirmedBy): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `alerts`
             SET `status` = 'confirmed', `confirmed_by` = ?, `confirmed_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ? AND `status` = 'unconfirmed'"
        );
        return $stmt->execute([$confirmedBy, $id, $tenantId]);
    }

    /**
     * 新規台帳登録時に呼び出される重複検知ロジック
     *
     * 重複条件（3つすべて一致した場合にアラートを発行）：
     *   1. 同一品目名（item_name 完全一致）
     *   2. 同一取引金額（transaction_amount 完全一致）
     *   3. 本人確認書類ファイルのサーバー保存日時が秒単位で一致
     *      （ledger_files.created_at を DATE_FORMAT で秒単位に丸めて比較）
     *
     * @param int $tenantId
     * @param int $newLedgerId
     * @return void
     */
    public function detectDuplicates(int $tenantId, int $newLedgerId): void
    {
        // まず新規登録レコードを取得
        $stmtNew = $this->pdo->prepare(
            "SELECT l.item_name, l.transaction_amount,
                    DATE_FORMAT(MIN(lf.created_at), '%Y-%m-%d %H:%i:%s') AS file_created_sec
             FROM `ledgers` l
             LEFT JOIN `ledger_files` lf
               ON lf.ledger_id = l.id
              AND lf.file_type = 'id_document'
             WHERE l.id = ? AND l.tenant_id = ? AND l.deleted_at IS NULL
             GROUP BY l.id, l.item_name, l.transaction_amount"
        );
        $stmtNew->execute([$newLedgerId, $tenantId]);
        $newRecord = $stmtNew->fetch();

        // 台帳レコードが存在しない or ファイルがない（書類スキャン未添付）場合は重複判定不要
        if ($newRecord === false || $newRecord['file_created_sec'] === null) {
            return;
        }

        // 同一テナントで条件を満たす既存レコードを検索（新規レコード自身を除く）
        $stmtDup = $this->pdo->prepare(
            "SELECT l.id
             FROM `ledgers` l
             INNER JOIN `ledger_files` lf
               ON lf.ledger_id = l.id
              AND lf.file_type = 'id_document'
             WHERE l.tenant_id = ?
               AND l.id != ?
               AND l.deleted_at IS NULL
               AND l.item_name = ?
               AND l.transaction_amount = ?
               AND DATE_FORMAT(lf.created_at, '%Y-%m-%d %H:%i:%s') = ?
             GROUP BY l.id"
        );
        $stmtDup->execute([
            $tenantId,
            $newLedgerId,
            $newRecord['item_name'],
            $newRecord['transaction_amount'],
            $newRecord['file_created_sec'],
        ]);

        while ($row = $stmtDup->fetch()) {
            $this->createIfNotExists($tenantId, $newLedgerId, (int)$row['id']);
        }
    }
}
