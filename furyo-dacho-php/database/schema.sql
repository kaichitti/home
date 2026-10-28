-- ============================================================
-- 古物台帳管理ツール (furyo-dacho) データベーススキーマ
-- 文字コード: UTF8MB4
-- 古物営業法第16条準拠
-- ============================================================

SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;
SET time_zone = '+09:00';
SET foreign_key_checks = 0;

-- ============================================================
-- 1. tenants - テナント管理
-- ============================================================
CREATE TABLE IF NOT EXISTS `tenants` (
    `id`         INT UNSIGNED     NOT NULL AUTO_INCREMENT,
    `code`       VARCHAR(50)      NOT NULL COMMENT 'テナントコード（英数字・ログイン時に使用）',
    `name`       VARCHAR(255)     NOT NULL COMMENT 'テナント名（事業者名）',
    `type`       ENUM('own','client') NOT NULL DEFAULT 'client' COMMENT 'own=自社, client=顧客',
    `status`     ENUM('active','suspended','deleted') NOT NULL DEFAULT 'active',
    `created_at` DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `uq_tenants_code` (`code`),
    INDEX `idx_tenants_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='テナント管理';

-- ============================================================
-- 2. system_admins - システム管理者（テナントと完全分離）
-- ============================================================
CREATE TABLE IF NOT EXISTS `system_admins` (
    `id`            INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `username`      VARCHAR(64)  NOT NULL UNIQUE,
    `password_hash` VARCHAR(255) NOT NULL COMMENT 'bcrypt ハッシュ',
    `last_login_at` DATETIME     NULL DEFAULT NULL,
    `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `uq_system_admins_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='システム管理者（テナント横断）';

-- ============================================================
-- 3. branches - 拠点
-- ============================================================
CREATE TABLE IF NOT EXISTS `branches` (
    `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`  INT UNSIGNED NOT NULL,
    `name`       VARCHAR(255) NOT NULL COMMENT '拠点名',
    `is_main`    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '主拠点フラグ（1=主拠点・削除不可、名称変更のみ）',
    `login_code` VARCHAR(50)  NULL DEFAULT NULL COMMENT '拠点ログインコード（この拠点のユーザーがログイン時に使用・テナント内一意）',
    `address`    VARCHAR(512) NULL DEFAULT NULL COMMENT '所在地',
    `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_branches_tenant_id` (`tenant_id`),
    UNIQUE INDEX `uq_branches_login_code` (`tenant_id`, `login_code`),
    CONSTRAINT `fk_branches_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='拠点';

-- ============================================================
-- 4. users - テナントユーザー
-- ============================================================
CREATE TABLE IF NOT EXISTS `users` (
    `id`                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`           INT UNSIGNED NOT NULL,
    `branch_id`           INT UNSIGNED NULL DEFAULT NULL COMMENT 'NULLの場合は全拠点参照可',
    `display_name`        VARCHAR(255) NOT NULL COMMENT '表示名',
    `email`               VARCHAR(255) NOT NULL COMMENT 'ログインID兼メール',
    `password_hash`       VARCHAR(255) NOT NULL COMMENT 'bcrypt ハッシュ',
    `role`                ENUM('admin','user') NOT NULL DEFAULT 'user' COMMENT 'admin=テナント管理者, user=一般',
    `is_owner`           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT 'オーナーフラグ（1=テナント作成時の初期管理者・削除/無効化不可）',
    `is_active`           TINYINT(1)   NOT NULL DEFAULT 1,
    `must_change_password` TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '次回ログイン時にパスワード変更を強制',
    `failed_login_attempts` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'ログイン失敗回数',
    `locked_until`        DATETIME     NULL DEFAULT NULL COMMENT 'アカウントロック解除日時',
    `last_login_at`       DATETIME     NULL DEFAULT NULL,
    `created_at`          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `uq_users_tenant_email` (`tenant_id`, `email`),
    INDEX `idx_users_tenant_id` (`tenant_id`),
    INDEX `idx_users_branch_id` (`branch_id`),
    CONSTRAINT `fk_users_tenant_id`  FOREIGN KEY (`tenant_id`)  REFERENCES `tenants`  (`id`),
    CONSTRAINT `fk_users_branch_id`  FOREIGN KEY (`branch_id`)  REFERENCES `branches` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='テナントユーザー';

-- ============================================================
-- 5. ledgers - 古物台帳メイン（古物営業法第16条準拠）
-- ============================================================
CREATE TABLE IF NOT EXISTS `ledgers` (
    `id`                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`             INT UNSIGNED    NOT NULL,
    `branch_id`             INT UNSIGNED    NOT NULL,

    -- 取引情報
    `transaction_date`      DATE            NOT NULL COMMENT '取引年月日',
    `transaction_type`      ENUM('buy','exchange','consignment','other') NOT NULL COMMENT 'buy=買取, exchange=交換, consignment=委託, other=その他',
    `transaction_type_note` VARCHAR(255)    NULL DEFAULT NULL COMMENT 'transaction_type=other の場合の補足',
    `item_category`         VARCHAR(100)    NOT NULL COMMENT '古物の区分（法定13区分コード / other / テナント独自区分名）',
    `item_category_note`    VARCHAR(255)    NULL DEFAULT NULL COMMENT 'item_category=other の場合の自由記述',
    `item_name`             VARCHAR(255)    NOT NULL COMMENT '品名',
    `serial_number`         VARCHAR(100)    NULL DEFAULT NULL COMMENT 'シリアル番号・製造番号（任意）',
    `item_description`      TEXT            NULL DEFAULT NULL COMMENT '品目・数量・特徴等',
    `quantity`              INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '数量',
    `transaction_amount`    DECIMAL(12,0)   NULL DEFAULT NULL COMMENT '取引金額（円）',
    `sale_price`            DECIMAL(12,0)   NULL DEFAULT NULL COMMENT '販売予定価格（売価・任意。POSレジの単価の初期値）',

    -- 相手方情報
    `member_code`           VARCHAR(50)     NULL DEFAULT NULL COMMENT '会員番号（任意・members.member_code のスナップショット）',
    `counterpart_type`      ENUM('individual','corporate') NOT NULL DEFAULT 'individual' COMMENT '相手方区分（individual=個人, corporate=法人）',
    `counterpart_name`      VARCHAR(255)    NOT NULL COMMENT '相手方氏名（法人の場合は名称）',
    `counterpart_address`   VARCHAR(512)    NOT NULL COMMENT '相手方住所',
    `counterpart_occupation` VARCHAR(255)   NULL DEFAULT NULL COMMENT '相手方職業',
    `counterpart_age`       TINYINT UNSIGNED NULL DEFAULT NULL COMMENT '相手方年齢',
    `counterpart_phone`     VARCHAR(20)     NULL DEFAULT NULL COMMENT '相手方電話番号',
    `counterpart_contact_name` VARCHAR(255) NULL DEFAULT NULL COMMENT '担当者名（法人の場合は必須）',
    `counterpart_account`   VARCHAR(255)    NULL DEFAULT NULL COMMENT '取引アカウント（オンライン買付時のID等・任意）',
    `counterpart_note`      TEXT            NULL DEFAULT NULL COMMENT '相手方に関する備考（任意）',

    -- 本人確認書類
    `id_document_type`      ENUM(
        'driver_license',
        'my_number',
        'passport',
        'health_insurance',
        'residence_card',
        'residence_status',
        'special_permanent',
        'other'
    ) NULL DEFAULT NULL COMMENT '本人確認書類種別（未登録可・未登録時はアラート表示）',
    `id_document_type_note` VARCHAR(255)    NULL DEFAULT NULL COMMENT '本人確認書類の種別が「その他」の場合の内容',
    `id_document_number`    VARCHAR(64)     NULL DEFAULT NULL COMMENT '本人確認書類番号（暗号化推奨）',

    -- システム付与
    `registered_by`         INT UNSIGNED    NOT NULL COMMENT '登録者 users.id',
    `updated_by`            INT UNSIGNED    NULL DEFAULT NULL COMMENT '最終更新者 users.id',
    `fiscal_year`           SMALLINT UNSIGNED NOT NULL COMMENT '会計年度（西暦）',
    `created_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `approval_status`       ENUM('none','pending','approved') NOT NULL DEFAULT 'none' COMMENT '承認状態（pending=本人確認スキップ+未認証相手のため管理者確認待ち）',
    `approved_by`           INT UNSIGNED    NULL DEFAULT NULL COMMENT '承認者 users.id',
    `approved_at`           DATETIME        NULL DEFAULT NULL COMMENT '承認日時',
    `deleted_at`            DATETIME        NULL DEFAULT NULL COMMENT '論理削除日時',

    PRIMARY KEY (`id`),
    INDEX `idx_ledgers_tenant_id`         (`tenant_id`),
    INDEX `idx_ledgers_branch_id`         (`branch_id`),
    INDEX `idx_ledgers_transaction_date`  (`transaction_date`),
    INDEX `idx_ledgers_fiscal_year`       (`fiscal_year`),
    INDEX `idx_ledgers_item_name`         (`item_name`),
    INDEX `idx_ledgers_serial_number`     (`serial_number`),
    INDEX `idx_ledgers_member_code`       (`member_code`),
    INDEX `idx_ledgers_counterpart_name`  (`counterpart_name`),
    INDEX `idx_ledgers_deleted_at`        (`deleted_at`),
    CONSTRAINT `fk_ledgers_tenant_id`     FOREIGN KEY (`tenant_id`)    REFERENCES `tenants`  (`id`),
    CONSTRAINT `fk_ledgers_branch_id`     FOREIGN KEY (`branch_id`)    REFERENCES `branches` (`id`),
    CONSTRAINT `fk_ledgers_registered_by` FOREIGN KEY (`registered_by`) REFERENCES `users`   (`id`),
    CONSTRAINT `fk_ledgers_updated_by`    FOREIGN KEY (`updated_by`)    REFERENCES `users`   (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='古物台帳（古物営業法第16条）';

-- ============================================================
-- 6. ledger_files - 添付ファイル（暗号化保存）
-- ============================================================
CREATE TABLE IF NOT EXISTS `ledger_files` (
    `id`                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `ledger_id`           BIGINT UNSIGNED NOT NULL,
    `tenant_id`           INT UNSIGNED    NOT NULL,
    `file_type`           ENUM('id_document','purchase_receipt','item_photo') NOT NULL COMMENT 'id_document=本人確認書類, purchase_receipt=購入証明, item_photo=商品画像',
    `original_filename`   VARCHAR(255)    NOT NULL COMMENT 'アップロード時のファイル名',
    `stored_filename`     VARCHAR(255)    NOT NULL COMMENT 'ストレージ上のファイル名（UUIDベース）',
    `file_path`           VARCHAR(512)    NOT NULL COMMENT 'ストレージ上の相対パス',
    `iv`                  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'AES-256-CBC 暗号化に使用した IV（hex 文字列）',
    `file_size`           INT UNSIGNED    NOT NULL COMMENT 'ファイルサイズ（バイト）',
    `mime_type`           VARCHAR(127)    NOT NULL COMMENT 'MIMEタイプ',
    `created_at`          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_ledger_files_ledger_id`  (`ledger_id`),
    INDEX `idx_ledger_files_tenant_id`  (`tenant_id`),
    CONSTRAINT `fk_ledger_files_ledger_id` FOREIGN KEY (`ledger_id`) REFERENCES `ledgers`  (`id`),
    CONSTRAINT `fk_ledger_files_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants`  (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='添付ファイル（暗号化保存）';

-- ============================================================
-- 6.3. sales - 販売記録（在庫管理）
--   台帳（仕入）1件に対して複数回の販売を記録できる。
--   残在庫 = ledgers.quantity - SUM(sales.quantity)
--   ※ 法定帳簿の売却記録が必要な場合は別途台帳登録すること。
-- ============================================================
CREATE TABLE IF NOT EXISTS `sales` (
    `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`   INT UNSIGNED    NOT NULL,
    `ledger_id`   BIGINT UNSIGNED NOT NULL COMMENT '対象の台帳（仕入記録）',
    `transaction_id` BIGINT UNSIGNED NULL DEFAULT NULL COMMENT 'POS会計（pos_transactions.id）。台帳画面からの販売はNULL',
    `member_code` VARCHAR(50)     NULL DEFAULT NULL COMMENT '販売先の会員番号（任意）',
    `quantity`    INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '販売個数',
    `sale_amount` DECIMAL(12,0)   NULL DEFAULT NULL COMMENT '販売金額（この販売の合計・円）',
    `sold_at`     DATETIME        NOT NULL COMMENT '販売日時',
    `note`        VARCHAR(512)    NULL DEFAULT NULL COMMENT '備考（販売先・チャネル等）',
    `created_by`  INT UNSIGNED    NULL DEFAULT NULL COMMENT '記録者 users.id',
    `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_sales_tenant_sold` (`tenant_id`, `sold_at`),
    INDEX `idx_sales_ledger_id`   (`ledger_id`),
    INDEX `idx_sales_transaction_id` (`transaction_id`),
    CONSTRAINT `fk_sales_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`),
    CONSTRAINT `fk_sales_ledger_id` FOREIGN KEY (`ledger_id`) REFERENCES `ledgers` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='販売記録（在庫管理）';

-- ============================================================
-- 6.4. members - 会員（相手方情報・本人確認情報の台帳への引用元）
--   台帳登録時に会員番号で紐付け（任意）、本人確認情報を引用できる。
--   台帳側には値をコピーして保存するスナップショット方式のため、
--   会員情報を後から変更・削除しても過去の台帳記録は変わらない。
-- ============================================================
CREATE TABLE IF NOT EXISTS `members` (
    `id`                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`          INT UNSIGNED NOT NULL,
    `member_code`        VARCHAR(50)  NOT NULL COMMENT '会員番号（テナント内一意）',
    `counterpart_type`   ENUM('individual','corporate') NOT NULL DEFAULT 'individual',
    `name`               VARCHAR(255) NOT NULL COMMENT '氏名（法人の場合は名称）',
    `address`            VARCHAR(512) NULL DEFAULT NULL COMMENT '住所',
    `occupation`         VARCHAR(255) NULL DEFAULT NULL COMMENT '職業（個人）',
    `age`                TINYINT UNSIGNED NULL DEFAULT NULL COMMENT '年齢（個人）',
    `phone`              VARCHAR(20)  NULL DEFAULT NULL COMMENT '電話番号',
    `contact_name`       VARCHAR(255) NULL DEFAULT NULL COMMENT '担当者名（法人）',
    `account`            VARCHAR(255) NULL DEFAULT NULL COMMENT '取引アカウント（オンラインID等）',
    `id_document_type`   ENUM('driver_license','my_number','passport','health_insurance','residence_card','residence_status','special_permanent','other') NULL DEFAULT NULL COMMENT '本人確認書類種別',
    `id_document_number` VARCHAR(64)  NULL DEFAULT NULL COMMENT '本人確認書類番号（マイナンバーカードの場合は個人番号を控えないこと）',
    `note`               TEXT         NULL DEFAULT NULL COMMENT '備考',
    `created_at`         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE INDEX `uq_members_tenant_code` (`tenant_id`, `member_code`),
    INDEX `idx_members_tenant_id` (`tenant_id`),
    INDEX `idx_members_name` (`name`),
    CONSTRAINT `fk_members_tenant_id` FOREIGN KEY (`tenant_id`) REFERENCES `tenants` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会員（相手方情報の引用元）';

-- ============================================================
-- 6.5. item_categories - テナント独自の古物区分
--   法定13区分に加えてテナント管理者が追加できる区分。
--   台帳には区分名をそのまま保存するため、区分を削除しても
--   過去の台帳レコードの表記は変わらない（スナップショット方式）。
-- ============================================================
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

-- ============================================================
-- 7. alerts - 重複検知アラート
-- ============================================================
CREATE TABLE IF NOT EXISTS `alerts` (
    `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`     INT UNSIGNED    NOT NULL,
    `ledger_id_1`   BIGINT UNSIGNED NOT NULL COMMENT '重複検知対象 台帳ID 1',
    `ledger_id_2`   BIGINT UNSIGNED NOT NULL COMMENT '重複検知対象 台帳ID 2',
    `status`        ENUM('unconfirmed','confirmed') NOT NULL DEFAULT 'unconfirmed',
    `confirmed_by`  INT UNSIGNED    NULL DEFAULT NULL COMMENT '確認者 users.id',
    `confirmed_at`  DATETIME        NULL DEFAULT NULL,
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_alerts_tenant_id`        (`tenant_id`),
    INDEX `idx_alerts_tenant_status`    (`tenant_id`, `status`),
    INDEX `idx_alerts_ledger_id_1`      (`ledger_id_1`),
    INDEX `idx_alerts_ledger_id_2`      (`ledger_id_2`),
    CONSTRAINT `fk_alerts_tenant_id`    FOREIGN KEY (`tenant_id`)   REFERENCES `tenants` (`id`),
    CONSTRAINT `fk_alerts_ledger_id_1`  FOREIGN KEY (`ledger_id_1`) REFERENCES `ledgers` (`id`),
    CONSTRAINT `fk_alerts_ledger_id_2`  FOREIGN KEY (`ledger_id_2`) REFERENCES `ledgers` (`id`),
    CONSTRAINT `fk_alerts_confirmed_by` FOREIGN KEY (`confirmed_by`) REFERENCES `users`  (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='重複検知アラート';

-- ============================================================
-- 8. audit_logs - 監査ログ（編集・削除不可）
-- ============================================================
CREATE TABLE IF NOT EXISTS `audit_logs` (
    `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `tenant_id`         INT UNSIGNED    NULL DEFAULT NULL COMMENT 'システム管理者操作時はNULL',
    `user_id`           INT UNSIGNED    NULL DEFAULT NULL COMMENT 'ユーザーID（削除済みユーザー対応のためNULL許容）',
    `user_display_name` VARCHAR(255)    NOT NULL COMMENT '操作時点の表示名（スナップショット）',
    `branch_name`       VARCHAR(255)    NULL DEFAULT NULL COMMENT '操作時点の拠点名（スナップショット）',
    `action_type`       ENUM('login','create','edit','delete','export','alert_action') NOT NULL,
    `target_id`         BIGINT UNSIGNED NULL DEFAULT NULL COMMENT '操作対象レコードID',
    `before_value`      JSON            NULL DEFAULT NULL COMMENT '変更前の値',
    `after_value`       JSON            NULL DEFAULT NULL COMMENT '変更後の値',
    `ip_address`        VARCHAR(45)     NOT NULL COMMENT 'IPv4/IPv6',
    `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_audit_logs_tenant_id`         (`tenant_id`),
    INDEX `idx_audit_logs_tenant_created_at` (`tenant_id`, `created_at`),
    INDEX `idx_audit_logs_user_id`           (`user_id`),
    INDEX `idx_audit_logs_action_type`       (`action_type`)
    -- 外部キーは意図的に設定しない（ユーザー削除後もログを保持するため）
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='監査ログ（編集・削除禁止）';

-- ============================================================
-- 9. login_attempts - ログイン試行履歴（2026-10 追加）
--   ブルートフォース対策・アカウントロックDoS対策（LoginThrottle）。
--   アカウント識別子は SHA-256 で保存し、メールアドレス等の平文は残さない。
--   success=1 の行は「信頼済みIP」（過去にログイン成功したIP）の判定に使う。
-- ============================================================
CREATE TABLE IF NOT EXISTS `login_attempts` (
    `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `ip`           VARCHAR(45)     NOT NULL COMMENT '試行元IPアドレス',
    `account_hash` CHAR(64)        NOT NULL COMMENT 'アカウント識別子のSHA-256（平文は保存しない）',
    `success`      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '0=失敗, 1=成功（信頼済みIPの判定に使用）, 2=照合せず拒否（ロック中・組合せ単位の制限。IP単位の制限のみに数える）',
    `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    INDEX `idx_login_attempts_ip`      (`ip`, `success`, `created_at`),
    INDEX `idx_login_attempts_account` (`account_hash`, `ip`, `success`, `created_at`),
    INDEX `idx_login_attempts_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='ログイン試行履歴（ブルートフォース・アカウントロックDoS対策）';

-- ============================================================
-- 10. POSレジ（2026-10-22 追加）
--   pos_settings          : 店舗・レシート・消費税の設定（テナント単位）
--   pos_transactions      : 会計（レシート番号・値引・消費税・支払・お釣り・取消）
--   pos_transaction_items : 会計明細のスナップショット（レシート再発行用）
--   pos_counters          : レシート番号の日別連番
--   pos_closings          : レジ精算（日計・現金過不足）
--   ※ 定義は src/Models/PosSchema.php と同一（未作成の環境ではPOS画面を開いた時に自動作成）
-- ============================================================
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

SET foreign_key_checks = 1;

-- ============================================================
-- 初期データ
-- パスワード: Admin7777 (bcrypt)
-- ============================================================

-- システム管理者
INSERT IGNORE INTO `system_admins` (`username`, `password_hash`) VALUES
('admin', '$2y$12$BfMvXseqjMK3KL2Ig4ZYaeA27DCcSKu08wa4cGwwFGxsTg1pw7PJu');

-- 自社テナント
INSERT IGNORE INTO `tenants` (`id`, `code`, `name`, `type`, `status`) VALUES
(1, 'honsha', '自社', 'own', 'active');

-- デフォルト拠点（自社テナント）
-- 主拠点（is_main=1）として作成する。以前は is_main が設定されておらず、
-- 新規インストール環境では主拠点の削除禁止が機能していなかった。
INSERT IGNORE INTO `branches` (`id`, `tenant_id`, `name`, `is_main`, `address`) VALUES
(1, 1, '本社', 1, NULL);

-- 自社テナントの管理者ユーザー
-- password: Admin7777, must_change_password=1
-- オーナー（is_owner=1・削除/無効化/降格不可）として作成する。以前は is_owner が
-- 設定されておらず、新規インストール環境ではオーナー保護が機能していなかった。
INSERT IGNORE INTO `users` (`tenant_id`, `branch_id`, `display_name`, `email`, `password_hash`, `role`, `is_owner`, `is_active`, `must_change_password`) VALUES
(1, 1, '管理者', 'admin@example.com', '$2y$12$BfMvXseqjMK3KL2Ig4ZYaeA27DCcSKu08wa4cGwwFGxsTg1pw7PJu', 'admin', 1, 1, 1);
