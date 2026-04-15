<?php
/**
 * lib/db.php
 *
 * SQLite データベースの初期化とアクセスを提供する。
 * Composer を使わず PDO(SQLite) のみで動作させる。
 *
 * スキーマ:
 *   - links:    管理者が登録する「決済リンク」。
 *   - payments: checkout.php で作成される「決済試行」。
 *               webhook により paid に更新され、success.php で redeem される。
 */

declare(strict_types=1);

require_once __DIR__ . '/../config.php';

/**
 * PDO インスタンスを返す（プロセス内シングルトン）。
 * 初回呼び出し時にスキーマを自動作成する。
 */
function pgw_db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }

    $cfg = pgw_config();
    $path = $cfg['db_path'];
    $dir  = dirname($path);

    if (!is_dir($dir)) {
        // Xrea 等では 0700 だと Web から書けない場合があるため 0755 を採用。
        if (!@mkdir($dir, 0755, true) && !is_dir($dir)) {
            throw new RuntimeException('データディレクトリを作成できません: ' . $dir);
        }
    }

    $pdo = new PDO('sqlite:' . $path, null, null, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
    ]);
    $pdo->exec('PRAGMA foreign_keys = ON');
    // WAL は共有ホストで効かない場合もあるので失敗しても続行。
    try { $pdo->exec('PRAGMA journal_mode = WAL'); } catch (Throwable $e) { /* ignore */ }

    pgw_db_init($pdo);
    return $pdo;
}

/**
 * スキーマを作成する（存在すれば何もしない）。
 */
function pgw_db_init(PDO $pdo): void
{
    $pdo->exec("
        CREATE TABLE IF NOT EXISTS links (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            slug        TEXT    UNIQUE NOT NULL,
            name        TEXT    NOT NULL,
            price       INTEGER NOT NULL,          -- Stripe unit_amount（最小通貨単位）
            currency    TEXT    NOT NULL DEFAULT 'jpy',
            target_url  TEXT    NOT NULL,           -- 決済後に遷移させる秘密URL
            active      INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    ");

    $pdo->exec("
        CREATE TABLE IF NOT EXISTS payments (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id            INTEGER NOT NULL,
            stripe_session_id  TEXT    UNIQUE NOT NULL,
            success_token      TEXT    UNIQUE NOT NULL,
            status             TEXT    NOT NULL DEFAULT 'pending',  -- pending|paid|redeemed|failed
            amount             INTEGER NOT NULL,
            currency           TEXT    NOT NULL,
            customer_email     TEXT,
            created_at         TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            paid_at            TEXT,
            redeemed_at        TEXT,
            expires_at         TEXT,
            FOREIGN KEY(link_id) REFERENCES links(id)
        )
    ");

    $pdo->exec("CREATE INDEX IF NOT EXISTS idx_payments_token   ON payments(success_token)");
    $pdo->exec("CREATE INDEX IF NOT EXISTS idx_payments_session ON payments(stripe_session_id)");
}

/**
 * slug から active なリンクを取得する。
 */
function pgw_find_active_link(string $slug): ?array
{
    $stmt = pgw_db()->prepare('SELECT * FROM links WHERE slug = :s AND active = 1 LIMIT 1');
    $stmt->execute([':s' => $slug]);
    $row = $stmt->fetch();
    return $row ?: null;
}
