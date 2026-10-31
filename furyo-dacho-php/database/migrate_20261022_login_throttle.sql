-- ============================================================
-- 2026-10 セキュリティ強化: ログイン試行履歴テーブル
--   ブルートフォース対策・アカウントロックDoS対策（LoginThrottle）。
--   ※ 未作成でも初回ログイン時に自動作成されるが、事前に作成しておく場合に実行する。
--   ※ migrate.php からも適用できる（冪等）。
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
