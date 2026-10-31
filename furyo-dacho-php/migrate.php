<?php
/**
 * 古物台帳管理ツール - DBマイグレーション実行スクリプト
 *
 * アプリを新バージョンに更新した際、DBに不足しているテーブル・カラムを
 * 検出して適用する。冪等（何度実行しても安全）。
 *
 * 使い方:
 *   1. このファイルを index.php と同じ場所にアップロード
 *      （分離構成の場合は public_html/ に置き、下の MIGRATE_BASE を
 *        アプリ本体のパスに書き換える）
 *   2. ブラウザで https://ドメイン/migrate.php にアクセスし「実行」を押す
 *   3. !!! 完了後は必ずこのファイルを削除すること !!!
 */

declare(strict_types=1);

// ============================================================
// アプリ本体（config/ を含むディレクトリ）の絶対パス。
// 分離構成の場合は書き換えること:
//   例: define('MIGRATE_BASE', '/virtual/アカウント名/furyo-dacho');
// ============================================================
if (!defined('MIGRATE_BASE')) {
    define('MIGRATE_BASE', __DIR__);
}

require_once MIGRATE_BASE . '/config/env.php';

function h(string $s): string
{
    return htmlspecialchars($s, ENT_QUOTES, 'UTF-8');
}

// ------------------------------------------------------------
// アクセス制御: システム管理者（/admin/ でログイン済み）のみ実行可
// ------------------------------------------------------------
// 無認証のままだと、消し忘れた migrate.php に第三者がアクセスして
// 任意に ALTER TABLE 等のスキーマ変更を実行できてしまう。
// システム管理者セッション（FURYO_ADMIN_SESS）を要求する。
// ※ マイグレーションは既存環境の更新用であり、その時点で管理者アカウントは
//    必ず存在する。先に https://ドメイン/admin/ でログインしてから実行すること。
(function (): void {
    $autoload = function (string $class): void {
        if (strpos($class, 'FuryoDacho\\') !== 0) {
            return;
        }
        $relative = str_replace('FuryoDacho\\', '', $class);
        $file     = MIGRATE_BASE . '/src/' . str_replace('\\', '/', $relative) . '.php';
        if (is_file($file)) {
            require_once $file;
        }
    };
    spl_autoload_register($autoload);

    $loggedIn = false;
    $mustChangePassword = false;
    try {
        $auth = new \FuryoDacho\Core\Auth();
        $loggedIn = $auth->isAdminLoggedIn();
        // 公開されている初期パスワードのままのセッションでは実行させない
        $mustChangePassword = $loggedIn && $auth->adminMustChangePassword();
    } catch (\Throwable $e) {
        $loggedIn = false;
    }

    if ($loggedIn && !$mustChangePassword) {
        return;
    }

    if ($mustChangePassword) {
        http_response_code(403);
        header('Content-Type: text/html; charset=UTF-8');
        echo '<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><title>パスワード変更が必要です</title></head>'
            . '<body style="font-family:sans-serif;padding:24px;"><p>システム管理者のパスワードが初期値のままです。'
            . '先に <a href="/admin/index.php?page=password">パスワード変更</a> を行ってから実行してください。</p></body></html>';
        exit;
    }

    http_response_code(403);
    header('Content-Type: text/html; charset=UTF-8');
    echo '<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">'
        . '<meta name="viewport" content="width=device-width, initial-scale=1">'
        . '<title>認証が必要です</title></head><body style="font-family:sans-serif;'
        . 'background:#f4f5f7;color:#333;display:flex;min-height:100vh;align-items:center;'
        . 'justify-content:center;padding:24px;">'
        . '<div style="background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);'
        . 'max-width:520px;padding:28px 24px;">'
        . '<h1 style="font-size:1.1rem;color:#1e3a5f;margin:0 0 12px;">システム管理者のログインが必要です</h1>'
        . '<p style="font-size:.9rem;line-height:1.8;color:#555;margin:0 0 12px;">'
        . 'このマイグレーションスクリプトはスキーマを変更します。実行するには、先に'
        . ' <code>/admin/</code> からシステム管理者としてログインしてください。</p>'
        . '<p style="font-size:.9rem;line-height:1.8;color:#c0392b;margin:0;">'
        . '<strong>適用完了後は、この migrate.php を直ちにサーバーから削除してください。</strong></p>'
        . '</div></body></html>';
    exit;
})();

$results = [];
$errors  = [];
$pending = [];
$pdo     = null;

// CSRF 対策: 実行ボタンのフォームにセッションのトークンを埋め込み、POST 時に照合する
// （以前はトークンが無く、ログイン中の管理者が細工されたページを開くと実行され得た）
if (session_status() !== PHP_SESSION_ACTIVE) {
    session_start();
}
if (empty($_SESSION['_csrf_token'])) {
    $_SESSION['_csrf_token'] = bin2hex(random_bytes(32));
}
$csrfToken = (string)$_SESSION['_csrf_token'];

// ------------------------------------------------------------
// DB接続
// ------------------------------------------------------------
try {
    $dbConf = require MIGRATE_BASE . '/config/database.php';
    $dsn = "mysql:host={$dbConf['host']};dbname={$dbConf['dbname']};charset={$dbConf['charset']}";
    $pdo = new PDO($dsn, $dbConf['username'], $dbConf['password'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    ]);
    $dbName = $dbConf['dbname'];
} catch (Throwable $e) {
    $errors[] = 'DB接続に失敗しました: ' . $e->getMessage();
}

// ------------------------------------------------------------
// マイグレーション定義（check: 適用が必要なら true を返す / apply: 適用SQL）
// ------------------------------------------------------------
$migrations = [];

if ($pdo !== null) {
    $migrations = [
        [
            'label' => 'ledgers.item_category を ENUM から VARCHAR(100) に変更（その他・独自区分対応）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT DATA_TYPE FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = 'item_category'"
                );
                $stmt->execute([$dbName]);
                $type = $stmt->fetchColumn();
                return $type !== false && strtolower((string)$type) !== 'varchar';
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "ALTER TABLE `ledgers`
                     MODIFY `item_category` VARCHAR(100) NOT NULL
                     COMMENT '古物の区分（法定13区分コード / other / テナント独自区分名）'"
                );
            },
        ],
        [
            'label' => 'ledgers.item_category_note カラムを追加（その他の自由記述）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = 'item_category_note'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "ALTER TABLE `ledgers`
                     ADD COLUMN `item_category_note` VARCHAR(255) NULL DEFAULT NULL
                     COMMENT 'item_category=other の場合の自由記述'
                     AFTER `item_category`"
                );
            },
        ],
        [
            'label' => 'item_categories テーブルを作成（テナント独自の古物区分）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'item_categories'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
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
            },
        ],
        [
            'label' => 'ledgers に会員番号・シリアル番号・相手方区分等のカラムを追加（2026-07-09）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers'
                       AND COLUMN_NAME IN ('member_code','serial_number','counterpart_type','counterpart_contact_name','counterpart_account','counterpart_note')"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() < 6;
            },
            'apply' => function () use ($pdo, $dbName): void {
                $cols = [
                    'serial_number'            => "ADD COLUMN `serial_number` VARCHAR(100) NULL DEFAULT NULL COMMENT 'シリアル番号・製造番号（任意）' AFTER `item_name`",
                    'member_code'              => "ADD COLUMN `member_code` VARCHAR(50) NULL DEFAULT NULL COMMENT '会員番号（任意）' AFTER `transaction_amount`",
                    'counterpart_type'         => "ADD COLUMN `counterpart_type` ENUM('individual','corporate') NOT NULL DEFAULT 'individual' COMMENT '相手方区分' AFTER `member_code`",
                    'counterpart_contact_name' => "ADD COLUMN `counterpart_contact_name` VARCHAR(255) NULL DEFAULT NULL COMMENT '担当者名（法人の場合は必須）' AFTER `counterpart_phone`",
                    'counterpart_account'      => "ADD COLUMN `counterpart_account` VARCHAR(255) NULL DEFAULT NULL COMMENT '取引アカウント（任意）' AFTER `counterpart_contact_name`",
                    'counterpart_note'         => "ADD COLUMN `counterpart_note` TEXT NULL DEFAULT NULL COMMENT '相手方に関する備考（任意）' AFTER `counterpart_account`",
                ];
                foreach ($cols as $name => $ddl) {
                    $stmt = $pdo->prepare(
                        "SELECT COUNT(*) FROM information_schema.COLUMNS
                         WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = ?"
                    );
                    $stmt->execute([$dbName, $name]);
                    if ((int)$stmt->fetchColumn() === 0) {
                        $pdo->exec("ALTER TABLE `ledgers` " . $ddl);
                    }
                }
                // シリアル番号検索用インデックス
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.STATISTICS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND INDEX_NAME = 'idx_ledgers_serial_number'"
                );
                $stmt->execute([$dbName]);
                if ((int)$stmt->fetchColumn() === 0) {
                    $pdo->exec("ALTER TABLE `ledgers` ADD INDEX `idx_ledgers_serial_number` (`serial_number`)");
                }
            },
        ],
        [
            // 旧バージョンから更新した DB では会員番号の索引が作られていなかった（新規導入の schema.sql にはある）
            'label' => 'ledgers に会員番号の索引を追加（会員の取引履歴の表示を速くする・2026-10-29）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = 'member_code'"
                );
                $stmt->execute([$dbName]);
                if ((int)$stmt->fetchColumn() === 0) {
                    return false;
                }
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.STATISTICS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND INDEX_NAME = 'idx_ledgers_member_code'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec("ALTER TABLE `ledgers` ADD INDEX `idx_ledgers_member_code` (`member_code`)");
            },
        ],
        [
            'label' => 'ledgers.id_document_type を任意（NULL許可）に変更（マイナンバー等の記載省略対応）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT IS_NULLABLE FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = 'id_document_type'"
                );
                $stmt->execute([$dbName]);
                return strtoupper((string)$stmt->fetchColumn()) === 'NO';
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "ALTER TABLE `ledgers`
                     MODIFY `id_document_type` ENUM('driver_license','my_number','passport','health_insurance','residence_card','residence_status','special_permanent','other')
                     NULL DEFAULT NULL COMMENT '本人確認書類種別（未登録可・未登録時はアラート表示）'"
                );
            },
        ],
        [
            'label' => 'members テーブルを作成（会員番号による相手方情報の紐付け・引用）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'members'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
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
            },
        ],
        [
            'label' => 'branches に主拠点フラグを追加し、各テナントの最初の拠点を主拠点に設定（2026-07-09）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'branches' AND COLUMN_NAME = 'is_main'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "ALTER TABLE `branches`
                     ADD COLUMN `is_main` TINYINT(1) NOT NULL DEFAULT 0
                     COMMENT '主拠点フラグ（1=主拠点・削除不可、名称変更のみ）' AFTER `name`"
                );
                // 各テナントの最初の拠点（最小ID）を主拠点に
                $pdo->exec(
                    "UPDATE `branches` b
                     JOIN (SELECT `tenant_id`, MIN(`id`) AS min_id FROM `branches` GROUP BY `tenant_id`) t
                       ON b.`tenant_id` = t.`tenant_id` AND b.`id` = t.min_id
                     SET b.`is_main` = 1"
                );
            },
        ],
        [
            'label' => 'users にオーナーフラグを追加し、各テナントの有効な管理者（いなければ最初の管理者）をオーナーに設定',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'users' AND COLUMN_NAME = 'is_owner'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "ALTER TABLE `users`
                     ADD COLUMN `is_owner` TINYINT(1) NOT NULL DEFAULT 0
                     COMMENT 'オーナーフラグ（1=テナント作成時の初期管理者・削除/無効化不可）' AFTER `role`"
                );
                // 各テナントの管理者のうち、有効な管理者を優先して最小IDをオーナーにする
                // （有効な管理者がいなければ最初の管理者。一般ユーザーはオーナーにしない）
                $pdo->exec(
                    "UPDATE `users` u
                     JOIN (SELECT `tenant_id`,
                                  COALESCE(MIN(CASE WHEN `is_active` = 1 THEN `id` END), MIN(`id`)) AS min_id
                           FROM `users` WHERE `role` = 'admin' GROUP BY `tenant_id`) t
                       ON u.`tenant_id` = t.`tenant_id` AND u.`id` = t.min_id
                     SET u.`is_owner` = 1"
                );
            },
        ],
        [
            'label' => 'ledger_files.file_type に商品画像（item_photo）を追加',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledger_files' AND COLUMN_NAME = 'file_type'"
                );
                $stmt->execute([$dbName]);
                return strpos((string)$stmt->fetchColumn(), 'item_photo') === false;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "ALTER TABLE `ledger_files`
                     MODIFY `file_type` ENUM('id_document','purchase_receipt','item_photo') NOT NULL
                     COMMENT 'id_document=本人確認書類, purchase_receipt=購入証明, item_photo=商品画像'"
                );
            },
        ],
        [
            'label' => 'ledgers に承認状態カラムを追加（本人確認スキップ+未認証相手の管理者承認フロー）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = 'approval_status'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "ALTER TABLE `ledgers`
                     ADD COLUMN `approval_status` ENUM('none','pending','approved') NOT NULL DEFAULT 'none'
                       COMMENT '承認状態（pending=本人確認スキップ+未認証相手のため管理者確認待ち）' AFTER `id_document_number`,
                     ADD COLUMN `approved_by` INT UNSIGNED NULL DEFAULT NULL COMMENT '承認者 users.id' AFTER `approval_status`,
                     ADD COLUMN `approved_at` DATETIME NULL DEFAULT NULL COMMENT '承認日時' AFTER `approved_by`"
                );
            },
        ],
        [
            'label' => 'sales テーブルを作成（在庫管理・販売記録・POS連携）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'sales'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "CREATE TABLE IF NOT EXISTS `sales` (
                        `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        `tenant_id`   INT UNSIGNED    NOT NULL,
                        `ledger_id`   BIGINT UNSIGNED NOT NULL COMMENT '対象の台帳（仕入記録）',
                        `member_code` VARCHAR(50)     NULL DEFAULT NULL COMMENT '販売先の会員番号（任意）',
                        `quantity`    INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '販売個数',
                        `sale_amount` DECIMAL(12,0)   NULL DEFAULT NULL COMMENT '販売金額（この販売の合計・円）',
                        `sold_at`     DATETIME        NOT NULL COMMENT '販売日時',
                        `note`        VARCHAR(512)    NULL DEFAULT NULL COMMENT '備考（販売先・チャネル等）',
                        `created_by`  INT UNSIGNED    NULL DEFAULT NULL COMMENT '記録者 users.id',
                        `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (`id`),
                        INDEX `idx_sales_tenant_sold` (`tenant_id`, `sold_at`),
                        INDEX `idx_sales_ledger_id`   (`ledger_id`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                      COMMENT='販売記録（在庫管理）'"
                );
            },
        ],
        [
            'label' => 'sales に販売先の会員番号カラムを追加（2026-07-10）',
            'check' => function () use ($pdo, $dbName): bool {
                // sales テーブル自体が無い場合は前ステップで作成される（member_code入り）ため対象外
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'sales'"
                );
                $stmt->execute([$dbName]);
                if ((int)$stmt->fetchColumn() === 0) {
                    return false;
                }
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'sales' AND COLUMN_NAME = 'member_code'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "ALTER TABLE `sales`
                     ADD COLUMN `member_code` VARCHAR(50) NULL DEFAULT NULL
                     COMMENT '販売先の会員番号（任意）' AFTER `ledger_id`"
                );
            },
        ],
        [
            'label' => 'branches に拠点ログインコードを追加（拠点別ログイン対応・2026-07-10）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'branches' AND COLUMN_NAME = 'login_code'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo, $dbName): void {
                $pdo->exec(
                    "ALTER TABLE `branches`
                     ADD COLUMN `login_code` VARCHAR(50) NULL DEFAULT NULL
                     COMMENT '拠点ログインコード（テナント内一意）' AFTER `is_main`"
                );
                // 一意インデックス（NULL は重複可）
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.STATISTICS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'branches' AND INDEX_NAME = 'uq_branches_login_code'"
                );
                $stmt->execute([$dbName]);
                if ((int)$stmt->fetchColumn() === 0) {
                    $pdo->exec("ALTER TABLE `branches` ADD UNIQUE INDEX `uq_branches_login_code` (`tenant_id`, `login_code`)");
                }
            },
        ],
        [
            'label' => 'login_attempts テーブルを作成（ログイン試行制限・アカウントロックDoS対策・2026-10）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'login_attempts'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(
                    "CREATE TABLE IF NOT EXISTS `login_attempts` (
                        `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        `ip`           VARCHAR(45)     NOT NULL COMMENT '試行元IPアドレス',
                        `account_hash` CHAR(64)        NOT NULL COMMENT 'アカウント識別子のSHA-256（平文は保存しない）',
                        `success`      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '0=失敗, 1=成功（信頼済みIPの判定に使用）, 2=照合せず拒否（ロック中・組合せ単位の制限。IP単位の制限のみに数える）',
                        `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (`id`),
                        INDEX `idx_login_attempts_ip`      (`ip`, `success`, `created_at`),
                        INDEX `idx_login_attempts_account` (`account_hash`, `ip`, `success`, `created_at`),
                        INDEX `idx_login_attempts_created` (`created_at`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                      COMMENT='ログイン試行履歴（ブルートフォース・アカウントロックDoS対策）'"
                );
            },
        ],
        [
            'label' => '主拠点・オーナーが未設定のテナントを補正（初期データでフラグが立っていなかった不具合の修復・2026-10）',
            'check' => function () use ($pdo, $dbName): bool {
                // 列自体が無い場合は前段のマイグレーションで追加・設定されるため対象外
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ?
                       AND ((TABLE_NAME = 'branches' AND COLUMN_NAME = 'is_main')
                         OR (TABLE_NAME = 'users'    AND COLUMN_NAME = 'is_owner'))"
                );
                $stmt->execute([$dbName]);
                if ((int)$stmt->fetchColumn() < 2) {
                    return false;
                }
                $noMain = (int)$pdo->query(
                    "SELECT COUNT(DISTINCT b.`tenant_id`) FROM `branches` b
                     WHERE NOT EXISTS (SELECT 1 FROM `branches` m WHERE m.`tenant_id` = b.`tenant_id` AND m.`is_main` = 1)"
                )->fetchColumn();
                // 管理者が居るのにオーナーが1人も居ないテナント（補正対象は管理者のみ）
                $noOwner = (int)$pdo->query(
                    "SELECT COUNT(DISTINCT u.`tenant_id`) FROM `users` u
                     WHERE u.`role` = 'admin'
                       AND NOT EXISTS (SELECT 1 FROM `users` o WHERE o.`tenant_id` = u.`tenant_id` AND o.`is_owner` = 1)"
                )->fetchColumn();
                return $noMain > 0 || $noOwner > 0;
            },
            'apply' => function () use ($pdo): void {
                // 主拠点が1件も無いテナント → 最初の拠点（最小ID）を主拠点に
                $pdo->exec(
                    "UPDATE `branches` b
                     JOIN (SELECT `tenant_id`, MIN(`id`) AS min_id FROM `branches` GROUP BY `tenant_id`) t
                       ON b.`tenant_id` = t.`tenant_id` AND b.`id` = t.min_id
                     SET b.`is_main` = 1
                     WHERE b.`tenant_id` NOT IN (
                         SELECT tid FROM (SELECT DISTINCT `tenant_id` AS tid FROM `branches` WHERE `is_main` = 1) x
                     )"
                );
                // オーナーが1人も居ないテナント → 有効な管理者のうち最初の1人（いなければ最初の管理者）をオーナーに
                $pdo->exec(
                    "UPDATE `users` u
                     JOIN (SELECT `tenant_id`,
                                  COALESCE(MIN(CASE WHEN `is_active` = 1 THEN `id` END), MIN(`id`)) AS min_id
                           FROM `users` WHERE `role` = 'admin' GROUP BY `tenant_id`) t
                       ON u.`tenant_id` = t.`tenant_id` AND u.`id` = t.min_id
                     SET u.`is_owner` = 1
                     WHERE u.`tenant_id` NOT IN (
                         SELECT tid FROM (SELECT DISTINCT `tenant_id` AS tid FROM `users` WHERE `is_owner` = 1) x
                     )"
                );
            },
        ],
        [
            'label' => 'POSレジのテーブルを作成（会計・明細・設定・レシート番号・レジ精算・2026-10-22）',
            'check' => function () use ($pdo, $dbName): bool {
                $tables = \FuryoDacho\Models\PosSchema::TABLES;
                $ph = implode(',', array_fill(0, count($tables), '?'));
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME IN ($ph)"
                );
                $stmt->execute(array_merge([$dbName], $tables));
                return (int)$stmt->fetchColumn() < count($tables);
            },
            'apply' => function () use ($pdo): void {
                foreach (\FuryoDacho\Models\PosSchema::TABLES as $table) {
                    $pdo->exec(\FuryoDacho\Models\PosSchema::ddl($table));
                }
            },
        ],
        [
            'label' => 'sales に会計（POS取引）との紐付け列 transaction_id を追加（2026-10-22）',
            'check' => function () use ($pdo, $dbName): bool {
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'sales'"
                );
                $stmt->execute([$dbName]);
                if ((int)$stmt->fetchColumn() === 0) {
                    return false;
                }
                $stmt = $pdo->prepare(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'sales' AND COLUMN_NAME = 'transaction_id'"
                );
                $stmt->execute([$dbName]);
                return (int)$stmt->fetchColumn() === 0;
            },
            'apply' => function () use ($pdo): void {
                $pdo->exec(\FuryoDacho\Models\PosSchema::salesTransactionColumnDdl());
            },
        ],
        [
            'label' => 'POSレジにレジ番号・会員の紐付け列を追加し、過去の会計に会員IDを補完（2026-10-23）',
            'check' => function () use ($pdo): bool {
                return \FuryoDacho\Models\PosSchema::pendingColumnUpgrades($pdo) !== [];
            },
            'apply' => function () use ($pdo): void {
                \FuryoDacho\Models\PosSchema::applyColumnUpgrades($pdo);
            },
        ],
        [
            'label' => 'ledgers に本人確認書類「その他」の内容（id_document_type_note）と販売予定価格（sale_price）の列を追加（2026-10-26）',
            'check' => function () use ($pdo): bool {
                return \FuryoDacho\Models\LedgerSchema::missingColumns($pdo) !== [];
            },
            'apply' => function () use ($pdo): void {
                \FuryoDacho\Models\LedgerSchema::apply($pdo);
            },
        ],
    ];

    // 未適用の項目を列挙
    foreach ($migrations as $m) {
        try {
            if ($m['check']()) {
                $pending[] = $m['label'];
            }
        } catch (Throwable $e) {
            $errors[] = 'チェック失敗（' . $m['label'] . '）: ' . $e->getMessage();
        }
    }
}

// ------------------------------------------------------------
// POST: 実行
// ------------------------------------------------------------
$done = false;
$csrfOk = is_string($_POST['_csrf_token'] ?? null) && hash_equals($csrfToken, $_POST['_csrf_token']);
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['run']) && !$csrfOk) {
    $errors[] = 'セッションの有効期限が切れたか、不正なリクエストです。ページを再読み込みしてもう一度実行してください。';
}
if ($pdo !== null && $_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['run']) && $csrfOk) {
    foreach ($migrations as $m) {
        try {
            if ($m['check']()) {
                $m['apply']();
                $results[] = '適用: ' . $m['label'];
            } else {
                $results[] = 'スキップ（適用済み）: ' . $m['label'];
            }
        } catch (Throwable $e) {
            $errors[] = '適用失敗（' . $m['label'] . '）: ' . $e->getMessage();
        }
    }
    $done = empty($errors);
    // 再チェック
    $pending = [];
    foreach ($migrations as $m) {
        try {
            if ($m['check']()) {
                $pending[] = $m['label'];
            }
        } catch (Throwable $e) {
        }
    }
}

// ------------------------------------------------------------
// 点検: 拠点ログインコードの重複（旧バージョンのデータ）
// ------------------------------------------------------------
// 2026-10版から拠点ログインコードは全テナント横断で一意とし、複数のテナントで
// 同じコード（またはテナントコードと同じ値）が登録されている場合、そのコードでは
// ログインできない（別テナントへ誤って誘導しないため）。該当があれば一覧表示する。
$codeWarnings = [];
if ($pdo !== null) {
    try {
        $rows = $pdo->query(
            "SELECT b.`login_code`, GROUP_CONCAT(CONCAT(t.`code`, ':', b.`name`) ORDER BY b.`id` SEPARATOR ' / ') AS owners
             FROM `branches` b JOIN `tenants` t ON t.`id` = b.`tenant_id`
             WHERE b.`login_code` IS NOT NULL AND b.`login_code` <> ''
             GROUP BY b.`login_code`
             HAVING COUNT(*) > 1"
        )->fetchAll(PDO::FETCH_ASSOC);
        foreach ($rows as $r) {
            $codeWarnings[] = '拠点ログインコード「' . $r['login_code'] . '」が複数の拠点で重複しています（このコードではログインできません）: ' . $r['owners'];
        }
        $rows = $pdo->query(
            "SELECT b.`login_code`, CONCAT(bt.`code`, ':', b.`name`) AS owner
             FROM `branches` b
             JOIN `tenants` t  ON t.`code` = b.`login_code`
             JOIN `tenants` bt ON bt.`id` = b.`tenant_id`"
        )->fetchAll(PDO::FETCH_ASSOC);
        foreach ($rows as $r) {
            $codeWarnings[] = '拠点ログインコード「' . $r['login_code'] . '」（' . $r['owner'] . '）がテナントコードと同じです（テナントコードが優先され、この拠点コードでは拠点を特定できません）';
        }
    } catch (Throwable $e) {
        // login_code 列が未追加の環境では点検不要
    }
}
?>
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DBマイグレーション - 古物台帳管理システム</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", "Hiragino Kaku Gothic ProN", Meiryo, sans-serif;
       background: #f4f5f7; color: #333; padding: 24px; }
.wrap { max-width: 640px; margin: 0 auto; background: #fff; border-radius: 8px;
        box-shadow: 0 1px 4px rgba(0,0,0,.12); padding: 24px; }
h1 { font-size: 1.2rem; color: #1e3a5f; margin-bottom: 16px; }
ul { margin: 8px 0 16px 20px; }
li { margin-bottom: 6px; font-size: .9rem; }
.ok    { color: #27ae60; }
.err   { color: #c0392b; }
.warn  { background: #fdf3e7; border: 1px solid #e67e22; color: #9a5b13;
         padding: 10px 12px; border-radius: 6px; font-size: .85rem; margin-bottom: 16px; }
button { background: #1e3a5f; color: #fff; border: none; border-radius: 6px;
         padding: 10px 24px; font-size: .95rem; cursor: pointer; }
button:hover { background: #2a4e7f; }
.note { font-size: .8rem; color: #777; margin-top: 16px; }
</style>
</head>
<body>
<div class="wrap">
    <h1>DBマイグレーション</h1>

    <?php if (!empty($errors)): ?>
        <ul><?php foreach ($errors as $e): ?><li class="err"><?= h($e) ?></li><?php endforeach; ?></ul>
    <?php endif; ?>

    <?php if (!empty($codeWarnings)): ?>
        <div class="warn">
            <b>拠点ログインコードの重複・衝突があります</b>
            <ul><?php foreach ($codeWarnings as $w): ?><li><?= h($w) ?></li><?php endforeach; ?></ul>
            各テナントの管理者が「拠点管理」で、重複しない新しいコードに変更してください。
        </div>
    <?php endif; ?>

    <?php if (!empty($results)): ?>
        <ul><?php foreach ($results as $r): ?><li class="ok"><?= h($r) ?></li><?php endforeach; ?></ul>
    <?php endif; ?>

    <?php if ($pdo !== null): ?>
        <?php if (empty($pending)): ?>
            <p class="ok" style="margin-bottom:16px;">&#10004; データベースは最新の状態です。適用が必要な変更はありません。</p>
            <div class="warn"><b>このファイル（migrate.php）を今すぐサーバーから削除してください。</b></div>
        <?php else: ?>
            <p style="font-size:.9rem; margin-bottom:8px;">以下の変更が未適用です:</p>
            <ul><?php foreach ($pending as $p): ?><li><?= h($p) ?></li><?php endforeach; ?></ul>
            <div class="warn">実行前にXREAコントロールパネル等でDBのバックアップを取得することを推奨します。</div>
            <form method="POST">
                <input type="hidden" name="_csrf_token" value="<?= h($csrfToken) ?>">
                <button type="submit" name="run" value="1">マイグレーションを実行</button>
            </form>
        <?php endif; ?>
    <?php endif; ?>

    <p class="note">実行が完了し「最新の状態です」と表示されたら、このファイルは必ず削除してください。</p>
</div>
</body>
</html>
