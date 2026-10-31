-- ============================================================
-- 既存環境用マイグレーション（2026-07-08）
-- 古物区分の「その他（自由記述）」対応 + テナント独自区分の追加
--
-- 新規インストール（schema.sql をこれから流す場合）は実行不要。
-- 実行前にバックアップを取得すること:
--   mysqldump -u USER -p DBNAME > backup.sql
-- ============================================================

-- 1. item_category を ENUM から VARCHAR に変更（既存の13区分コードはそのまま保持される）
ALTER TABLE `ledgers`
    MODIFY `item_category` VARCHAR(100) NOT NULL
        COMMENT '古物の区分（法定13区分コード / other / テナント独自区分名）';

-- 2. その他選択時の自由記述カラムを追加
ALTER TABLE `ledgers`
    ADD COLUMN `item_category_note` VARCHAR(255) NULL DEFAULT NULL
        COMMENT 'item_category=other の場合の自由記述'
        AFTER `item_category`;

-- 3. テナント独自区分テーブルを作成
CREATE TABLE IF NOT EXISTS `item_categories` (
    `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`  INT UNSIGNED NOT NULL,
    `name`       VARCHAR(100) NOT NULL COMMENT '区分名',
    `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `uq_item_categories_tenant_name` (`tenant_id`, `name`),
    INDEX `idx_item_categories_tenant_id` (`tenant_id`),
    CONSTRAINT `fk_item_categories_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='テナント独自の古物区分';
