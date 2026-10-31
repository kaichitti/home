-- ============================================================
-- 既存環境用マイグレーション（2026-07-09）
-- 会員管理・シリアル番号・個人法人切替・本人確認任意化
--
-- ブラウザから migrate.php を実行する場合、このファイルは不要。
-- 実行前にバックアップを取得すること。
-- ============================================================

ALTER TABLE `ledgers`
    ADD COLUMN `serial_number` VARCHAR(100) NULL DEFAULT NULL COMMENT 'シリアル番号・製造番号（任意）' AFTER `item_name`,
    ADD COLUMN `member_code` VARCHAR(50) NULL DEFAULT NULL COMMENT '会員番号（任意）' AFTER `transaction_amount`,
    ADD COLUMN `counterpart_type` ENUM('individual','corporate') NOT NULL DEFAULT 'individual' COMMENT '相手方区分' AFTER `member_code`,
    ADD COLUMN `counterpart_contact_name` VARCHAR(255) NULL DEFAULT NULL COMMENT '担当者名（法人の場合は必須）' AFTER `counterpart_phone`,
    ADD COLUMN `counterpart_account` VARCHAR(255) NULL DEFAULT NULL COMMENT '取引アカウント（任意）' AFTER `counterpart_contact_name`,
    ADD COLUMN `counterpart_note` TEXT NULL DEFAULT NULL COMMENT '相手方に関する備考（任意）' AFTER `counterpart_account`,
    ADD INDEX `idx_ledgers_serial_number` (`serial_number`);

ALTER TABLE `ledgers`
    MODIFY `id_document_type` ENUM('driver_license','my_number','passport','health_insurance','residence_card','residence_status','special_permanent','other')
    NULL DEFAULT NULL COMMENT '本人確認書類種別（未登録可・未登録時はアラート表示）';

CREATE TABLE IF NOT EXISTS `members` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会員（相手方情報の引用元）';
