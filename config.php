<?php
/**
 * config.php
 *
 * Stripe決済リンク・ゲートウェイの設定ファイル。
 *
 * Xrea（PHP 8.x / SQLite）で動作させるための構成値をまとめて定義します。
 * 秘密情報（Stripe Secret Key / Webhook Secret / 管理パスワードハッシュ）は
 * 可能であれば .htaccess 等で環境変数として設定し、ソースコードへ直接書き込まない
 * ことを推奨します。直接書き込む場合でも、本ファイルはWebから読めないよう
 * ルート .htaccess で deny from all しています。
 *
 * 使い方:
 *   1. Stripe ダッシュボード（テストモード）で Secret Key / Publishable Key を取得
 *   2. Webhook エンドポイント https://<your-host>/webhook.php を登録し Signing Secret を取得
 *   3. 下記 pgw_config() の値を書き換える、または対応する環境変数を設定
 *   4. 管理画面パスワードは以下のコマンドでハッシュを生成して貼り付け:
 *        php -r "echo password_hash('your-password', PASSWORD_DEFAULT), PHP_EOL;"
 */

declare(strict_types=1);

/**
 * 設定値を返す（シングルトン的キャッシュ）。
 *
 * @return array<string,mixed>
 */
function pgw_config(): array
{
    static $cfg = null;
    if ($cfg !== null) {
        return $cfg;
    }

    $cfg = [
        // ---- Stripe API ----
        // テスト用キー（sk_test_... / pk_test_...）を推奨。
        'stripe_publishable_key' => getenv('STRIPE_PUBLISHABLE_KEY') ?: 'pk_test_REPLACE_ME',
        'stripe_secret_key'      => getenv('STRIPE_SECRET_KEY')      ?: 'sk_test_REPLACE_ME',
        // Webhook 署名検証用シークレット（whsec_...）。
        'stripe_webhook_secret'  => getenv('STRIPE_WEBHOOK_SECRET')  ?: 'whsec_REPLACE_ME',

        // ---- 管理画面 ----
        // password_hash() で生成したハッシュ文字列を入れる。
        // 例: php -r "echo password_hash('changeme', PASSWORD_DEFAULT);"
        'admin_password_hash'    => getenv('PGW_ADMIN_PASSWORD_HASH') ?: '',

        // ---- セッション／Cookie ----
        'session_cookie_name'    => 'PGWSID',
        // HTTPS 環境下であれば true のままで良い（XreaのSSLでもOK）。
        'cookie_secure'          => !in_array(getenv('PGW_COOKIE_SECURE'), ['0', 'false'], true),

        // ---- データベース（SQLite） ----
        // 絶対パスではなく、このファイルからの相対位置で解決する。
        'db_path'                => __DIR__ . '/data/db.sqlite',

        // ---- 決済デフォルト ----
        // Stripe の unit_amount は「最小通貨単位」。JPY は小数なし（1 = 1円）。
        'default_currency'       => 'jpy',

        // ---- URL ----
        // 空文字の場合は $_SERVER から自動検出（推奨）。
        // リバースプロキシ配下などで固定したい場合のみ記入する。
        'base_url'               => getenv('PGW_BASE_URL') ?: '',

        // ---- トークン有効期限 ----
        // 決済成功後、success.php で秘密URLへリダイレクト可能な時間（秒）。
        // 期限内であれば、同一トークンで再アクセス（ブックマーク等）も許容する。
        'success_token_ttl'      => 60 * 60 * 24, // 24時間
    ];

    return $cfg;
}

/**
 * HTMLエスケープ（ショートハンド）。
 */
function pgw_h(?string $s): string
{
    return htmlspecialchars((string)$s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

/**
 * このツールのベースURLを自動検出して返す。
 * 設定で base_url が指定されていればそれを優先する。
 * 末尾にスラッシュを付けない文字列を返す。
 */
function pgw_base_url(): string
{
    $cfg = pgw_config();
    if (!empty($cfg['base_url'])) {
        return rtrim($cfg['base_url'], '/');
    }

    $https  = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
           || (($_SERVER['SERVER_PORT'] ?? null) == 443)
           || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
    $scheme = $https ? 'https' : 'http';
    $host   = $_SERVER['HTTP_HOST'] ?? 'localhost';
    $script = $_SERVER['SCRIPT_NAME'] ?? '/index.php';
    $dir    = rtrim(str_replace('\\', '/', dirname($script)), '/');

    return $scheme . '://' . $host . $dir;
}

/**
 * 同ディレクトリ内の相対URLを生成する（例: "checkout.php?slug=abc"）。
 */
function pgw_url(string $path): string
{
    return pgw_base_url() . '/' . ltrim($path, '/');
}

/**
 * 安全なリダイレクト。
 */
function pgw_redirect(string $url, int $status = 302): void
{
    header('Location: ' . $url, true, $status);
    exit;
}
