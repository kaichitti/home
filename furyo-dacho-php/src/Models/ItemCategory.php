<?php

namespace FuryoDacho\Models;

/**
 * ItemCategory モデル
 * 古物区分の管理を担当する。
 *
 * 区分は3種類:
 *   1. 法定13区分（古物営業法施行規則 別表第1）: 英語コードで ledgers に保存
 *   2. その他（'other'）: item_category_note に自由記述を保存
 *   3. テナント独自区分: 区分名の文字列をそのまま ledgers に保存
 *      （スナップショット方式 — 区分を後から削除しても過去帳簿の表記は不変）
 */
class ItemCategory extends BaseModel
{
    protected string $table = 'item_categories';

    /** その他を表すコード */
    public const OTHER = 'other';

    /** @var array<string,string> 法定13区分の日本語ラベル */
    public const STATUTORY = [
        'art'               => '美術品類',
        'clothing'          => '衣類',
        'watch_jewelry'     => '時計・宝飾品類',
        'automobile'        => '自動車',
        'motorcycle'        => '自動二輪車及び原動機付自転車',
        'bicycle'           => '自転車類',
        'camera'            => '写真機類',
        'office_equipment'  => '事務機器類',
        'machinery'         => '機械工具類',
        'tools'             => '道具類',
        'leather_rubber'    => '皮革・ゴム製品類',
        'books'             => '書籍',
        'gift_certificates' => '金券類',
    ];

    /**
     * 保存値を表示ラベルに変換する
     *
     * @param string|null $value ledgers.item_category の値
     * @param string|null $note  ledgers.item_category_note の値
     * @return string
     */
    public static function label(?string $value, ?string $note = null): string
    {
        if ($value === null || $value === '') {
            return '';
        }
        if (isset(self::STATUTORY[$value])) {
            return self::STATUTORY[$value];
        }
        if ($value === self::OTHER) {
            return ($note !== null && $note !== '') ? 'その他（' . $note . '）' : 'その他';
        }
        // テナント独自区分は名前がそのまま保存されている
        return $value;
    }

    /**
     * item_categories テーブルが存在しない場合に自動作成する
     *
     * マイグレーション未適用の環境で台帳画面全体が
     * 「Base table or view not found」で落ちるのを防ぐ。
     * CREATE TABLE IF NOT EXISTS のため既存環境には無害。
     */
    private function ensureTable(): void
    {
        $this->pdo->exec(
            "CREATE TABLE IF NOT EXISTS `item_categories` (
                `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
                `tenant_id`  INT UNSIGNED NOT NULL,
                `name`       VARCHAR(100) NOT NULL COMMENT '区分名',
                `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                UNIQUE INDEX `uq_item_categories_tenant_name` (`tenant_id`, `name`),
                INDEX `idx_item_categories_tenant_id` (`tenant_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
              COMMENT='テナント独自の古物区分'"
        );
    }

    /**
     * テーブル未作成（SQLSTATE 42S02）の場合は作成してリトライする
     *
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
     * テナントの独自区分一覧を取得
     *
     * @param int $tenantId
     * @return array
     */
    public function findAllByTenant(int $tenantId): array
    {
        return $this->withTable(function () use ($tenantId): array {
            $stmt = $this->pdo->prepare(
                "SELECT * FROM `item_categories` WHERE `tenant_id` = ? ORDER BY `name` ASC"
            );
            $stmt->execute([$tenantId]);
            return $stmt->fetchAll();
        });
    }

    /**
     * ID とテナントIDで独自区分を取得
     */
    public function findById(int $id, int $tenantId): ?array
    {
        return $this->withTable(function () use ($id, $tenantId): ?array {
            $stmt = $this->pdo->prepare(
                "SELECT * FROM `item_categories` WHERE `id` = ? AND `tenant_id` = ?"
            );
            $stmt->execute([$id, $tenantId]);
            $row = $stmt->fetch();
            return $row ?: null;
        });
    }

    /**
     * 独自区分を作成
     *
     * @return int 生成されたID
     * @throws \RuntimeException 法定区分・その他と重複する名前や既存名の場合
     */
    public function create(int $tenantId, string $name): int
    {
        $name = trim($name);

        if ($name === '') {
            throw new \RuntimeException('区分名を入力してください。');
        }
        if (mb_strlen($name) > 100) {
            throw new \RuntimeException('区分名は100文字以内で入力してください。');
        }
        // 法定区分の名称・コード、'other' との衝突を防ぐ
        if (
            in_array($name, self::STATUTORY, true)
            || isset(self::STATUTORY[$name])
            || $name === self::OTHER
            || $name === 'その他'
        ) {
            throw new \RuntimeException('この区分名は既定の区分と重複しているため使用できません。');
        }
        if ($this->existsName($tenantId, $name)) {
            throw new \RuntimeException('この区分名はすでに登録されています。');
        }

        return $this->withTable(function () use ($tenantId, $name): int {
            $stmt = $this->pdo->prepare(
                "INSERT INTO `item_categories` (`tenant_id`, `name`) VALUES (?, ?)"
            );
            $stmt->execute([$tenantId, $name]);
            return (int)$this->pdo->lastInsertId();
        });
    }

    /**
     * 独自区分を削除
     * 過去の台帳レコードには区分名がそのまま保存されているため、
     * 削除しても既存データの表示・検索には影響しない。
     */
    public function delete(int $id, int $tenantId): bool
    {
        $stmt = $this->pdo->prepare(
            "DELETE FROM `item_categories` WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([$id, $tenantId]);
    }

    /**
     * 同名の独自区分が存在するか
     */
    public function existsName(int $tenantId, string $name): bool
    {
        return $this->withTable(function () use ($tenantId, $name): bool {
            $stmt = $this->pdo->prepare(
                "SELECT COUNT(*) FROM `item_categories` WHERE `tenant_id` = ? AND `name` = ?"
            );
            $stmt->execute([$tenantId, $name]);
            return (int)$stmt->fetchColumn() > 0;
        });
    }

    /**
     * 台帳フォーム・検索用の選択肢一覧を組み立てる
     * 法定13区分 + テナント独自区分 + その他（自由記述）
     *
     * @param int $tenantId
     * @return array<string,string> value => label
     */
    public function buildOptions(int $tenantId): array
    {
        $options = self::STATUTORY;

        foreach ($this->findAllByTenant($tenantId) as $row) {
            // 独自区分は名前そのものが保存値
            $options[$row['name']] = $row['name'];
        }

        $options[self::OTHER] = 'その他（自由記述）';

        return $options;
    }

    /**
     * 入力された区分値がこのテナントで有効か検証する
     */
    public function isValidValue(int $tenantId, string $value): bool
    {
        if (isset(self::STATUTORY[$value]) || $value === self::OTHER) {
            return true;
        }
        return $this->existsName($tenantId, $value);
    }
}
