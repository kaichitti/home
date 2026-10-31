<?php

namespace FuryoDacho\Models;

/**
 * Tenant モデル
 * テナント（事業者）の CRUD 操作を担当する。
 * codeカラムによるテナント特定に対応。
 */
class Tenant extends BaseModel
{
    protected string $table = 'tenants';

    /**
     * 全テナント一覧を取得（削除済み含む）
     */
    public function findAll(): array
    {
        $stmt = $this->pdo->query(
            "SELECT * FROM `tenants` WHERE `status` != 'deleted' ORDER BY `id` ASC"
        );
        return $stmt->fetchAll();
    }

    /**
     * アクティブなテナント一覧を取得
     */
    public function getActive(): array
    {
        $stmt = $this->pdo->query(
            "SELECT * FROM `tenants` WHERE `status` = 'active' ORDER BY `id` ASC"
        );
        return $stmt->fetchAll();
    }

    /**
     * IDでテナントを取得
     */
    public function findById(int $id): ?array
    {
        $stmt = $this->pdo->prepare("SELECT * FROM `tenants` WHERE `id` = ?");
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    /**
     * テナントコードでテナントを取得（ログイン時のテナント特定）
     */
    public function findByCode(string $code): ?array
    {
        $stmt = $this->pdo->prepare("SELECT * FROM `tenants` WHERE `code` = ?");
        $stmt->execute([$code]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    /**
     * テナントコードの重複チェック
     */
    public function isCodeTaken(string $code, ?int $excludeId = null): bool
    {
        if ($excludeId !== null) {
            $stmt = $this->pdo->prepare(
                "SELECT COUNT(*) FROM `tenants` WHERE `code` = ? AND `id` != ?"
            );
            $stmt->execute([$code, $excludeId]);
        } else {
            $stmt = $this->pdo->prepare("SELECT COUNT(*) FROM `tenants` WHERE `code` = ?");
            $stmt->execute([$code]);
        }
        return (int)$stmt->fetchColumn() > 0;
    }

    /**
     * テナントを作成
     *
     * @param array{code: string, name: string, type: string, status?: string} $data
     * @return int 生成されたID
     */
    public function create(array $data): int
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `tenants` (`code`, `name`, `type`, `status`) VALUES (?, ?, ?, ?)"
        );
        $stmt->execute([
            $data['code'],
            $data['name'],
            $data['type'],
            $data['status'] ?? 'active',
        ]);
        return (int)$this->pdo->lastInsertId();
    }

    /**
     * テナント情報を更新
     */
    public function update(int $id, array $data): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `tenants` SET `code` = ?, `name` = ?, `type` = ?, `status` = ?, `updated_at` = NOW()
             WHERE `id` = ?"
        );
        return $stmt->execute([
            $data['code'],
            $data['name'],
            $data['type'],
            $data['status'],
            $id,
        ]);
    }

    /**
     * テナントを停止（status = suspended）
     */
    public function suspend(int $id): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `tenants` SET `status` = 'suspended', `updated_at` = NOW() WHERE `id` = ?"
        );
        return $stmt->execute([$id]);
    }

    /**
     * テナントを論理削除（status = deleted）
     * 削除前に softDelete() を呼び出した後、呼び出し元で全ユーザーを無効化すること
     */
    public function delete(int $id): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `tenants` SET `status` = 'deleted', `updated_at` = NOW() WHERE `id` = ?"
        );
        return $stmt->execute([$id]);
    }

    /**
     * テナントを論理削除（旧名・後方互換）
     */
    public function softDelete(int $id): bool
    {
        return $this->delete($id);
    }
    /**
     * テナント一覧に利用状況（ユーザー数・台帳件数・最終ログイン）を付けて返す
     *
     * @param bool $includeDeleted 削除済みのテナントも含めるか
     */
    public function findAllWithStats(bool $includeDeleted = false): array
    {
        $where = $includeDeleted ? '' : "WHERE t.`status` != 'deleted'";
        $stmt = $this->pdo->query(
            "SELECT t.*,
                    COALESCE(u.user_count, 0)   AS user_count,
                    COALESCE(u.active_count, 0) AS active_user_count,
                    u.last_login_at,
                    COALESCE(l.ledger_count, 0) AS ledger_count
             FROM `tenants` t
             LEFT JOIN (
                 SELECT `tenant_id`, COUNT(*) AS user_count, SUM(`is_active` = 1) AS active_count,
                        MAX(`last_login_at`) AS last_login_at
                 FROM `users` GROUP BY `tenant_id`
             ) u ON u.`tenant_id` = t.`id`
             LEFT JOIN (
                 SELECT `tenant_id`, COUNT(*) AS ledger_count
                 FROM `ledgers` WHERE `deleted_at` IS NULL GROUP BY `tenant_id`
             ) l ON l.`tenant_id` = t.`id`
             {$where}
             ORDER BY t.`id` ASC"
        );
        return $stmt->fetchAll();
    }

    /**
     * 停止中のテナントを再開する（削除済みは対象外）
     */
    public function resume(int $id): bool
    {
        $stmt = $this->pdo->prepare(
            "UPDATE `tenants` SET `status` = 'active', `updated_at` = NOW() WHERE `id` = ? AND `status` = 'suspended'"
        );
        $stmt->execute([$id]);
        return $stmt->rowCount() > 0;
    }
}
