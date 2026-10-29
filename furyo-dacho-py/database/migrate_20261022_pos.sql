-- ============================================================
-- 既存環境用マイグレーション（2026-10-22）POSレジ機能拡充
--   会計（取引）単位の管理・レシート番号・値引・消費税・支払方法・お釣り・
--   レシート/領収書の発行記録・取引取消・レジ精算
-- ブラウザから migrate.php を実行する場合、このファイルは不要。
-- （migrate.php を使わない場合も、POS画面を開いた時点で不足分は自動作成される）
-- ============================================================

-- 販売記録と会計の紐付け（既に列がある場合はこの文をスキップすること）
ALTER TABLE `sales`
    ADD COLUMN `transaction_id` BIGINT UNSIGNED NULL DEFAULT NULL
        COMMENT 'POS会計（pos_transactions.id）。台帳画面からの販売はNULL' AFTER `ledger_id`,
    ADD INDEX `idx_sales_transaction_id` (`transaction_id`);

CREATE TABLE IF NOT EXISTS `pos_settings` (
    `tenant_id`      INT UNSIGNED NOT NULL,
    `store_name`     VARCHAR(100) NULL DEFAULT NULL COMMENT 'レシートに印字する店舗名（空欄時はテナント名）',
    `store_address`  VARCHAR(255) NULL DEFAULT NULL COMMENT '店舗住所',
    `store_phone`    VARCHAR(30)  NULL DEFAULT NULL COMMENT '店舗電話番号',
    `invoice_number` VARCHAR(14)  NULL DEFAULT NULL COMMENT '適格請求書発行事業者の登録番号（T+13桁）',
    `tax_rate`       TINYINT UNSIGNED NOT NULL DEFAULT 10 COMMENT '消費税率（%）',
    `tax_mode`       ENUM('inclusive','exclusive') NOT NULL DEFAULT 'inclusive' COMMENT 'inclusive=内税（税込価格）, exclusive=外税（税抜価格）',
    `tax_rounding`   ENUM('floor','round','ceil') NOT NULL DEFAULT 'floor' COMMENT '消費税の端数処理',
    `receipt_header` VARCHAR(200) NULL DEFAULT NULL COMMENT 'レシート上部メッセージ',
    `receipt_footer` VARCHAR(200) NULL DEFAULT NULL COMMENT 'レシート下部メッセージ',
    `ryoshu_tadashi` VARCHAR(50)  NULL DEFAULT NULL COMMENT '領収書の但し書き（既定値）',
    `updated_by`     INT UNSIGNED NULL DEFAULT NULL,
    `updated_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='POS設定（店舗・レシート・消費税）';

CREATE TABLE IF NOT EXISTS `pos_transactions` (
    `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`       INT UNSIGNED    NOT NULL,
    `branch_id`       INT UNSIGNED    NULL DEFAULT NULL COMMENT '会計した拠点（担当者の所属拠点）',
    `register_no`     TINYINT UNSIGNED NULL DEFAULT NULL COMMENT 'レジ番号（会計した端末に設定した番号 1〜99）',
    `receipt_no`      VARCHAR(20)     NOT NULL COMMENT 'レシート番号（YYYYMMDD-連番）',
    `client_token`    VARCHAR(64)     NULL DEFAULT NULL COMMENT '二重送信防止キー（同じキーの再送は同じ会計を返す）',
    `status`          ENUM('completed','voided') NOT NULL DEFAULT 'completed',
    `member_code`     VARCHAR(50)     NULL DEFAULT NULL COMMENT '会員番号（任意・会計時点）',
    `member_id`       INT UNSIGNED    NULL DEFAULT NULL COMMENT '会員（members.id）。会員番号を後から変更しても紐付けを保つ',
    `member_name`     VARCHAR(255)    NULL DEFAULT NULL COMMENT '会計時点の会員名（スナップショット）',
    `item_count`      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '販売点数',
    `subtotal`        DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '小計（明細金額の合計）',
    `discount_type`   ENUM('none','amount','percent') NOT NULL DEFAULT 'none' COMMENT '小計値引の種類',
    `discount_value`  DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '小計値引の指定値（円または%）',
    `discount_amount` DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '小計値引額（円）',
    `tax_mode`        ENUM('inclusive','exclusive') NOT NULL DEFAULT 'inclusive',
    `tax_rate`        TINYINT UNSIGNED NOT NULL DEFAULT 10,
    `tax_amount`      DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '消費税額（内税の場合は内消費税額）',
    `total`           DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT 'お支払合計（税込）',
    `payment_method`  ENUM('cash','credit','emoney','qr','other') NOT NULL DEFAULT 'cash',
    `tendered`        DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT 'お預り金額',
    `change_amount`   DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT 'お釣り',
    `payment_ref`     VARCHAR(100)    NULL DEFAULT NULL COMMENT '承認番号・伝票番号等（任意）',
    `note`            VARCHAR(400)    NULL DEFAULT NULL,
    `store_info`      TEXT            NULL DEFAULT NULL COMMENT '会計時点の店舗情報（JSON・レシート再発行用）',
    `cashier_name`    VARCHAR(255)    NULL DEFAULT NULL COMMENT '会計時点の担当者名',
    `receipt_status`  ENUM('pending','printed','unprinted','print_failed') NOT NULL DEFAULT 'pending' COMMENT 'printed=印刷済, unprinted=プリンタ未接続で画面発行, print_failed=印刷失敗',
    `print_count`     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT 'レシート印刷回数（2回目以降は再発行と印字）',
    `ryoshu_count`    INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '領収書の発行回数',
    `last_printed_at` DATETIME        NULL DEFAULT NULL,
    `created_by`      INT UNSIGNED    NULL DEFAULT NULL,
    `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `voided_by`       INT UNSIGNED    NULL DEFAULT NULL,
    `voided_at`       DATETIME        NULL DEFAULT NULL,
    `void_reason`     VARCHAR(255)    NULL DEFAULT NULL,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `uq_pos_tx_receipt` (`tenant_id`, `receipt_no`),
    UNIQUE INDEX `uq_pos_tx_token` (`tenant_id`, `client_token`),
    INDEX `idx_pos_tx_tenant_created` (`tenant_id`, `created_at`),
    INDEX `idx_pos_tx_member` (`tenant_id`, `member_id`),
    INDEX `idx_pos_tx_register` (`tenant_id`, `register_no`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='POS会計（取引）';

CREATE TABLE IF NOT EXISTS `pos_transaction_items` (
    `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `transaction_id`   BIGINT UNSIGNED NOT NULL,
    `tenant_id`        INT UNSIGNED    NOT NULL,
    `ledger_id`        BIGINT UNSIGNED NOT NULL,
    `sale_id`          BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '対応する販売記録（取消後は削除済み）',
    `line_no`          SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    `item_name`        VARCHAR(255)    NOT NULL COMMENT '会計時点の品名',
    `serial_number`    VARCHAR(100)    NULL DEFAULT NULL,
    `quantity`         INT UNSIGNED    NOT NULL DEFAULT 1,
    `unit_price`       DECIMAL(12,0)   NOT NULL DEFAULT 0,
    `line_discount`    DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '単品値引（円）',
    `amount`           DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '明細金額（単価×数量−単品値引）',
    `allocated_amount` DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '小計値引・外税を按分した売上計上額（= sales.sale_amount）',
    PRIMARY KEY (`id`),
    INDEX `idx_pos_items_tx` (`transaction_id`),
    INDEX `idx_pos_items_tenant_ledger` (`tenant_id`, `ledger_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='POS会計明細（スナップショット）';

CREATE TABLE IF NOT EXISTS `pos_counters` (
    `tenant_id` INT UNSIGNED NOT NULL,
    `biz_date`  DATE         NOT NULL,
    `last_no`   INT UNSIGNED NOT NULL DEFAULT 0,
    PRIMARY KEY (`tenant_id`, `biz_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='POSレシート番号の日別連番';

CREATE TABLE IF NOT EXISTS `pos_closings` (
    `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`      INT UNSIGNED    NOT NULL,
    `branch_id`      INT UNSIGNED    NULL DEFAULT NULL COMMENT '対象拠点（NULL=全拠点）',
    `register_no`    TINYINT UNSIGNED NULL DEFAULT NULL COMMENT '対象レジ番号（NULL=全レジ）',
    `biz_date`       DATE            NOT NULL COMMENT '営業日',
    `tx_count`       INT UNSIGNED    NOT NULL DEFAULT 0,
    `sales_total`    DECIMAL(12,0)   NOT NULL DEFAULT 0,
    `cash_sales`     DECIMAL(12,0)   NOT NULL DEFAULT 0,
    `opening_float`  DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '釣銭準備金',
    `expected_cash`  DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '理論現金残高',
    `counted_cash`   DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '現金実査額',
    `difference`     DECIMAL(12,0)   NOT NULL DEFAULT 0 COMMENT '過不足（実査−理論）',
    `denominations`  TEXT            NULL DEFAULT NULL COMMENT '金種別枚数（JSON）',
    `summary`        TEXT            NULL DEFAULT NULL COMMENT '精算時点の集計（JSON）',
    `note`           VARCHAR(400)    NULL DEFAULT NULL,
    `closed_by`      INT UNSIGNED    NULL DEFAULT NULL,
    `closed_by_name` VARCHAR(255)    NULL DEFAULT NULL,
    `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_pos_closings_tenant_date` (`tenant_id`, `biz_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='レジ精算記録';
