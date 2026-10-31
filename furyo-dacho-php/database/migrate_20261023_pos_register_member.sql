-- ============================================================
-- 既存環境用マイグレーション（2026-10-23）POSレジ: レジ番号・会員の紐付け
--   2026-10-22版（POSレジ機能拡充）を適用済みの環境向け。
--   ブラウザから migrate.php を実行する場合、このファイルは不要。
--   （migrate.php を使わない場合も、POS画面を開いた時点で不足分は自動で追加される）
--   ※ 2026-10-22版を未適用の場合は先に migrate_20261022_pos.sql を実行すること
--     （その場合、下の ALTER は「列が既に存在」エラーになるので実行不要）。
-- ============================================================

ALTER TABLE `pos_transactions`
    ADD COLUMN `register_no` TINYINT UNSIGNED NULL DEFAULT NULL COMMENT 'レジ番号（会計した端末に設定した番号 1〜99）' AFTER `branch_id`,
    ADD INDEX `idx_pos_tx_register` (`tenant_id`, `register_no`, `created_at`);

ALTER TABLE `pos_transactions`
    ADD COLUMN `member_id` INT UNSIGNED NULL DEFAULT NULL COMMENT '会員（members.id）。会員番号を後から変更しても紐付けを保つ' AFTER `member_code`,
    ADD INDEX `idx_pos_tx_member` (`tenant_id`, `member_id`);

ALTER TABLE `pos_transactions`
    ADD COLUMN `member_name` VARCHAR(255) NULL DEFAULT NULL COMMENT '会計時点の会員名（スナップショット）' AFTER `member_id`;

ALTER TABLE `pos_closings`
    ADD COLUMN `register_no` TINYINT UNSIGNED NULL DEFAULT NULL COMMENT '対象レジ番号（NULL=全レジ）' AFTER `branch_id`;

-- 会員番号しか記録していない過去の会計に、会員ID・会員名を補う
UPDATE `pos_transactions` t
JOIN `members` m ON m.`tenant_id` = t.`tenant_id` AND m.`member_code` = t.`member_code`
SET t.`member_id` = m.`id`, t.`member_name` = COALESCE(t.`member_name`, m.`name`)
WHERE t.`member_id` IS NULL AND t.`member_code` IS NOT NULL AND t.`member_code` <> '';
