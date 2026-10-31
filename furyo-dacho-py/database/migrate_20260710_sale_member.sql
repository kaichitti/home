-- 2026-07-10: 販売記録に販売先会員番号を追加
-- （migrate.php を使う場合はこのファイルの実行は不要）
ALTER TABLE `sales`
  ADD COLUMN `member_code` VARCHAR(50) NULL DEFAULT NULL
  COMMENT '販売先の会員番号（任意）' AFTER `ledger_id`;
