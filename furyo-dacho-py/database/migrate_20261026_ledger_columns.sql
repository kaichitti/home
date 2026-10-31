-- ============================================================
-- 既存環境用マイグレーション（2026-10-26）台帳の列追加
--   - id_document_type_note : 本人確認書類「その他」の内容
--       （以前は入力欄だけがあり保存先が無かったため、入力しても保存されていなかった）
--   - sale_price            : 販売予定価格（売価・任意。POSレジの単価の初期値）
--   ブラウザから migrate.php を実行する場合、このファイルは不要。
--   （migrate.php を使わない場合も、台帳を扱う画面を開いた時点で不足分は自動で追加される）
--   ※ 既に列がある場合は「列が既に存在」エラーになるので、その行は実行不要。
-- ============================================================

ALTER TABLE `ledgers`
    ADD COLUMN `id_document_type_note` VARCHAR(255) NULL DEFAULT NULL
    COMMENT '本人確認書類の種別が「その他」の場合の内容' AFTER `id_document_type`;

ALTER TABLE `ledgers`
    ADD COLUMN `sale_price` DECIMAL(12,0) NULL DEFAULT NULL
    COMMENT '販売予定価格（売価・任意。POSレジの単価の初期値）' AFTER `transaction_amount`;
