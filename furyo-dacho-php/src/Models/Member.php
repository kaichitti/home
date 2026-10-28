<?php

namespace FuryoDacho\Models;

/**
 * Member モデル
 * 会員（相手方情報・本人確認情報の引用元）を管理する。
 *
 * 台帳登録時に会員番号を指定すると本人確認情報を引用できる（任意）。
 * 台帳側には値をコピーして保存するスナップショット方式のため、
 * 会員情報を後から変更・削除しても過去の台帳記録は変わらない。
 */
class Member extends BaseModel
{
    protected string $table = 'members';

    /**
     * テーブル未作成環境での致命的エラーを防ぐ自動作成
     */
    private function ensureTable(): void
    {
        $this->pdo->exec(
            "CREATE TABLE IF NOT EXISTS `members` (
                `id`                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
                `tenant_id`          INT UNSIGNED NOT NULL,
                `member_code`        VARCHAR(50)  NOT NULL COMMENT '会員番号（テナント内一意）',
                `counterpart_type`   ENUM('individual','corporate') NOT NULL DEFAULT 'individual',
                `name`               VARCHAR(255) NOT NULL COMMENT '氏名（法人の場合は名称）',
                `address`            VARCHAR(512) NULL DEFAULT NULL,
                `occupation`         VARCHAR(255) NULL DEFAULT NULL,
                `age`                TINYINT UNSIGNED NULL DEFAULT NULL,
                `phone`              VARCHAR(20)  NULL DEFAULT NULL,
                `contact_name`       VARCHAR(255) NULL DEFAULT NULL COMMENT '担当者名（法人）',
                `account`            VARCHAR(255) NULL DEFAULT NULL COMMENT '取引アカウント',
                `id_document_type`   ENUM('driver_license','my_number','passport','health_insurance','residence_card','residence_status','special_permanent','other') NULL DEFAULT NULL,
                `id_document_number` VARCHAR(64)  NULL DEFAULT NULL,
                `note`               TEXT         NULL DEFAULT NULL,
                `created_at`         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                `updated_at`         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                UNIQUE INDEX `uq_members_tenant_code` (`tenant_id`, `member_code`),
                INDEX `idx_members_tenant_id` (`tenant_id`),
                INDEX `idx_members_name` (`name`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
              COMMENT='会員（相手方情報の引用元）'"
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
            throw $e;
        }
    }

    /**
     * 一覧取得（会員番号・氏名で部分一致検索可）
     */
    public function search(int $tenantId, ?string $keyword = null, int $limit = 50, int $offset = 0): array
    {
        return $this->withTable(function () use ($tenantId, $keyword, $limit, $offset): array {
            $sql    = "SELECT * FROM `members` WHERE `tenant_id` = ?";
            $params = [$tenantId];

            if ($keyword !== null && $keyword !== '') {
                $sql .= " AND (`member_code` LIKE ? OR `name` LIKE ?)";
                $like = '%' . $keyword . '%';
                $params[] = $like;
                $params[] = $like;
            }

            $sql .= " ORDER BY `member_code` ASC LIMIT " . (int)$limit . " OFFSET " . (int)$offset;
            $stmt = $this->pdo->prepare($sql);
            $stmt->execute($params);
            return $stmt->fetchAll();
        });
    }

    public function countAll(int $tenantId, ?string $keyword = null): int
    {
        return $this->withTable(function () use ($tenantId, $keyword): int {
            $sql    = "SELECT COUNT(*) FROM `members` WHERE `tenant_id` = ?";
            $params = [$tenantId];
            if ($keyword !== null && $keyword !== '') {
                $sql .= " AND (`member_code` LIKE ? OR `name` LIKE ?)";
                $like = '%' . $keyword . '%';
                $params[] = $like;
                $params[] = $like;
            }
            $stmt = $this->pdo->prepare($sql);
            $stmt->execute($params);
            return (int)$stmt->fetchColumn();
        });
    }

    public function findById(int $id, int $tenantId): ?array
    {
        return $this->withTable(function () use ($id, $tenantId): ?array {
            $stmt = $this->pdo->prepare(
                "SELECT * FROM `members` WHERE `id` = ? AND `tenant_id` = ?"
            );
            $stmt->execute([$id, $tenantId]);
            $row = $stmt->fetch();
            return $row ?: null;
        });
    }

    /**
     * 会員番号で検索（台帳フォームの引用機能で使用）
     */
    public function findByCode(int $tenantId, string $code): ?array
    {
        return $this->withTable(function () use ($tenantId, $code): ?array {
            $stmt = $this->pdo->prepare(
                "SELECT * FROM `members` WHERE `tenant_id` = ? AND `member_code` = ?"
            );
            $stmt->execute([$tenantId, $code]);
            $row = $stmt->fetch();
            return $row ?: null;
        });
    }

    public function existsCode(int $tenantId, string $code, ?int $excludeId = null): bool
    {
        return $this->withTable(function () use ($tenantId, $code, $excludeId): bool {
            $sql    = "SELECT COUNT(*) FROM `members` WHERE `tenant_id` = ? AND `member_code` = ?";
            $params = [$tenantId, $code];
            if ($excludeId !== null) {
                $sql .= " AND `id` != ?";
                $params[] = $excludeId;
            }
            $stmt = $this->pdo->prepare($sql);
            $stmt->execute($params);
            return (int)$stmt->fetchColumn() > 0;
        });
    }

    /**
     * 未使用の会員番号を自動採番する（M-0001 形式）
     */
    public function generateCode(int $tenantId): string
    {
        return $this->withTable(function () use ($tenantId): string {
            // 既存の M-数字 形式のうち最大の連番を取得
            $stmt = $this->pdo->prepare(
                "SELECT `member_code` FROM `members`
                 WHERE `tenant_id` = ? AND `member_code` REGEXP '^M-[0-9]+$'
                 ORDER BY CAST(SUBSTRING(`member_code`, 3) AS UNSIGNED) DESC
                 LIMIT 1"
            );
            $stmt->execute([$tenantId]);
            $last = $stmt->fetchColumn();
            $next = $last ? ((int)substr((string)$last, 2) + 1) : 1;

            // 衝突回避（手動採番との競合に備えて空きが出るまで進める）
            do {
                $code = 'M-' . str_pad((string)$next, 4, '0', STR_PAD_LEFT);
                $next++;
            } while ($this->existsCode($tenantId, $code));

            return $code;
        });
    }

    public function create(int $tenantId, array $data): int
    {
        return $this->withTable(function () use ($tenantId, $data): int {
            $stmt = $this->pdo->prepare(
                "INSERT INTO `members`
                    (`tenant_id`, `member_code`, `counterpart_type`, `name`, `address`,
                     `occupation`, `age`, `phone`, `contact_name`, `account`,
                     `id_document_type`, `id_document_number`, `note`)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            );
            $stmt->execute([
                $tenantId,
                $data['member_code'],
                $data['counterpart_type'] ?? 'individual',
                $data['name'],
                $data['address'] ?: null,
                $data['occupation'] ?: null,
                ($data['age'] ?? '') !== '' ? (int)$data['age'] : null,
                $data['phone'] ?: null,
                $data['contact_name'] ?: null,
                $data['account'] ?: null,
                $data['id_document_type'] ?: null,
                $data['id_document_number'] ?: null,
                $data['note'] ?: null,
            ]);
            return (int)$this->pdo->lastInsertId();
        });
    }

    public function update(int $id, int $tenantId, array $data): bool
    {
        return $this->withTable(function () use ($id, $tenantId, $data): bool {
            $stmt = $this->pdo->prepare(
                "UPDATE `members` SET
                    `member_code` = ?, `counterpart_type` = ?, `name` = ?, `address` = ?,
                    `occupation` = ?, `age` = ?, `phone` = ?, `contact_name` = ?, `account` = ?,
                    `id_document_type` = ?, `id_document_number` = ?, `note` = ?, `updated_at` = NOW()
                 WHERE `id` = ? AND `tenant_id` = ?"
            );
            return $stmt->execute([
                $data['member_code'],
                $data['counterpart_type'] ?? 'individual',
                $data['name'],
                $data['address'] ?: null,
                $data['occupation'] ?: null,
                ($data['age'] ?? '') !== '' ? (int)$data['age'] : null,
                $data['phone'] ?: null,
                $data['contact_name'] ?: null,
                $data['account'] ?: null,
                $data['id_document_type'] ?: null,
                $data['id_document_number'] ?: null,
                $data['note'] ?: null,
                $id,
                $tenantId,
            ]);
        });
    }

    public function delete(int $id, int $tenantId): bool
    {
        return $this->withTable(function () use ($id, $tenantId): bool {
            $stmt = $this->pdo->prepare(
                "DELETE FROM `members` WHERE `id` = ? AND `tenant_id` = ?"
            );
            return $stmt->execute([$id, $tenantId]);
        });
    }
}
