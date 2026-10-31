-- ============================================================
-- 既存環境用マイグレーション（2026-07-09 第2弾）
-- 主拠点保護・オーナー・商品画像・承認フロー・在庫管理/POS
-- ブラウザから migrate.php を実行する場合、このファイルは不要。
-- ============================================================

-- 主拠点フラグ + 各テナントの最初の拠点を主拠点に
ALTER TABLE `branches`
    ADD COLUMN `is_main` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '主拠点フラグ（1=主拠点・削除不可、名称変更のみ）' AFTER `name`;
UPDATE `branches` b
JOIN (SELECT `tenant_id`, MIN(`id`) AS min_id FROM `branches` GROUP BY `tenant_id`) t
  ON b.`tenant_id` = t.`tenant_id` AND b.`id` = t.min_id
SET b.`is_main` = 1;

-- オーナーフラグ + 各テナントの有効な管理者（いなければ最初の管理者）をオーナーに
-- （一般ユーザーはオーナーにしない。migrate.php と同じ選び方）
ALTER TABLE `users`
    ADD COLUMN `is_owner` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'オーナーフラグ（削除/無効化不可）' AFTER `role`;
UPDATE `users` u
JOIN (SELECT `tenant_id`,
             COALESCE(MIN(CASE WHEN `is_active` = 1 THEN `id` END), MIN(`id`)) AS min_id
      FROM `users` WHERE `role` = 'admin' GROUP BY `tenant_id`) t
  ON u.`tenant_id` = t.`tenant_id` AND u.`id` = t.min_id
SET u.`is_owner` = 1;

-- 商品画像
ALTER TABLE `ledger_files`
    MODIFY `file_type` ENUM('id_document','purchase_receipt','item_photo') NOT NULL
    COMMENT 'id_document=本人確認書類, purchase_receipt=購入証明, item_photo=商品画像';

-- 承認フロー
ALTER TABLE `ledgers`
    ADD COLUMN `approval_status` ENUM('none','pending','approved') NOT NULL DEFAULT 'none'
      COMMENT '承認状態（pending=本人確認スキップ+未認証相手のため管理者確認待ち）' AFTER `id_document_number`,
    ADD COLUMN `approved_by` INT UNSIGNED NULL DEFAULT NULL AFTER `approval_status`,
    ADD COLUMN `approved_at` DATETIME NULL DEFAULT NULL AFTER `approved_by`;

-- 販売記録（在庫管理・POS）
CREATE TABLE IF NOT EXISTS `sales` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`   INT UNSIGNED    NOT NULL,
    `ledger_id`   BIGINT UNSIGNED NOT NULL COMMENT '対象の台帳（仕入記録）',
    `quantity`    INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '販売個数',
    `sale_amount` DECIMAL(12,0)   NULL DEFAULT NULL COMMENT '販売金額（この販売の合計・円）',
    `sold_at`     DATETIME        NOT NULL COMMENT '販売日時',
    `note`        VARCHAR(512)    NULL DEFAULT NULL COMMENT '備考',
    `created_by`  INT UNSIGNED    NULL DEFAULT NULL,
    `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_sales_tenant_sold` (`tenant_id`, `sold_at`),
    INDEX `idx_sales_ledger_id`   (`ledger_id`),
    CONSTRAINT `fk_sales_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
    CONSTRAINT `fk_sales_ledger_id` FOREIGN KEY (`ledger_id`) REFERENCES `ledgers` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='販売記録（在庫管理）';
