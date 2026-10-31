<?php

namespace FuryoDacho\Models;

/**
 * AuditLog モデル
 * 監査ログの記録・参照を担当する。
 * 監査ログは追記専用。update / delete メソッドは提供しない。
 */
class AuditLog extends BaseModel
{
    protected string $table = 'audit_logs';

    /**
     * 監査ログを記録（追記のみ）
     *
     * @param int|null    $tenantId      テナントID（システム管理者操作時はNULL）
     * @param int|null    $userId        ユーザーID
     * @param string      $displayName   操作時点の表示名
     * @param string|null $branchName    操作時点の拠点名
     * @param string      $actionType    アクション種別（login/create/edit/delete/export/alert_action）
     * @param int|null    $targetId      操作対象レコードID
     * @param array|null  $beforeValue   変更前の値
     * @param array|null  $afterValue    変更後の値
     * @param string      $ipAddress     IPアドレス
     * @return int 生成されたID
     */
    public function log(
        ?int    $tenantId,
        ?int    $userId,
        string  $displayName,
        ?string $branchName,
        string  $actionType,
        ?int    $targetId,
        ?array  $beforeValue,
        ?array  $afterValue,
        string  $ipAddress
    ): int {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `audit_logs`
             (`tenant_id`, `user_id`, `user_display_name`, `branch_name`,
              `action_type`, `target_id`, `before_value`, `after_value`, `ip_address`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        $stmt->execute([
            $tenantId,
            $userId,
            $displayName,
            $branchName,
            $actionType,
            $targetId,
            $beforeValue !== null ? json_encode($beforeValue, JSON_UNESCAPED_UNICODE) : null,
            $afterValue  !== null ? json_encode($afterValue,  JSON_UNESCAPED_UNICODE) : null,
            $ipAddress,
        ]);
        return (int)$this->pdo->lastInsertId();
    }

    /**
     * テナントの監査ログ一覧を取得
     *
     * @param int $tenantId
     * @param int $limit
     * @param int $offset
     * @return array
     */
    public function findByTenant(int $tenantId, int $limit = 100, int $offset = 0): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `audit_logs`
             WHERE `tenant_id` = ?
             ORDER BY `created_at` DESC
             LIMIT ? OFFSET ?"
        );
        $stmt->execute([$tenantId, $limit, $offset]);
        return $stmt->fetchAll();
    }

    /**
     * 全テナントの監査ログを横断閲覧（システム管理者用）
     *
     * @param int $limit
     * @param int $offset
     * @return array
     */
    public function findAll(int $limit = 100, int $offset = 0): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT `al`.*, `t`.`name` AS `tenant_name`
             FROM `audit_logs` AS `al`
             LEFT JOIN `tenants` AS `t` ON `al`.`tenant_id` = `t`.`id`
             ORDER BY `al`.`created_at` DESC
             LIMIT ? OFFSET ?"
        );
        $stmt->execute([$limit, $offset]);
        return $stmt->fetchAll();
    }

    /**
     * 監査ログを記録（連想配列形式・後方互換）
     *
     * @return int 生成されたID
     */
    public function record(array $data): int
    {
        return $this->log(
            $data['tenant_id']        ?? null,
            $data['user_id']          ?? null,
            $data['user_display_name'],
            $data['branch_name']      ?? null,
            $data['action_type'],
            $data['target_id']        ?? null,
            $data['before_value']     ?? null,
            $data['after_value']      ?? null,
            $data['ip_address']
        );
    }

    /**
     * テナントの監査ログ一覧をフィルタ付きで取得（後方互換）
     */
    public function getByTenant(int $tenantId, array $filters = [], int $perPage = 100, int $page = 1): array
    {
        $where  = ['tenant_id = ?'];
        $params = [$tenantId];

        if (!empty($filters['action_type'])) {
            $where[]  = 'action_type = ?';
            $params[] = $filters['action_type'];
        }
        if (!empty($filters['user_id'])) {
            $where[]  = 'user_id = ?';
            $params[] = (int)$filters['user_id'];
        }
        if (!empty($filters['date_from'])) {
            $where[]  = 'created_at >= ?';
            $params[] = $filters['date_from'] . ' 00:00:00';
        }
        if (!empty($filters['date_to'])) {
            $where[]  = 'created_at <= ?';
            $params[] = $filters['date_to'] . ' 23:59:59';
        }

        $whereClause = implode(' AND ', $where);
        $offset      = ($page - 1) * $perPage;

        $stmt = $this->pdo->prepare(
            "SELECT * FROM `audit_logs`
             WHERE {$whereClause}
             ORDER BY `created_at` DESC
             LIMIT ? OFFSET ?"
        );
        $params[] = $perPage;
        $params[] = $offset;
        $stmt->execute($params);
        return $stmt->fetchAll();
    }
}
