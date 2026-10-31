<?php

/**
 * テナント側エントリポイント
 * 全リクエストをここで受け取り Router に渡す。
 */

declare(strict_types=1);

// ============================================================
// BASE_PATH: アプリケーション本体（src/ config/ views/ を含む
// ディレクトリ）の絶対パス。
//
// XREA へデプロイして public/ の中身だけを public_html/ に
// 配置する場合は、ここをサーバー上の実パスに書き換えること。
//   例: define('BASE_PATH', '/virtual/アカウント名/furyo-dacho');
//
// 開発環境やアプリ一式をそのまま配置する構成では変更不要。
// ============================================================
if (!defined('BASE_PATH')) {
    define('BASE_PATH', dirname(__DIR__));
}

// タイムゾーン設定
date_default_timezone_set('Asia/Tokyo');

// オートローダー（Composerがある場合は vendor/autoload.php に差し替える）
spl_autoload_register(function (string $class): void {
    $base      = BASE_PATH . '/src/';
    $relative  = str_replace('FuryoDacho\\', '', $class);
    $file      = $base . str_replace('\\', '/', $relative) . '.php';
    if (file_exists($file)) {
        require_once $file;
    }
});

// 本番環境ではエラー表示を抑制（APP_ENV または APP_DEBUG 環境変数で切り替え）
$config = require BASE_PATH . '/config/config.php';
if (($_ENV['APP_ENV'] ?? 'production') !== 'development' && !($config['debug'] ?? false)) {
    ini_set('display_errors', '0');
    error_reporting(0);
} else {
    ini_set('display_errors', '1');
    error_reporting(E_ALL);
}

// 未捕捉の例外・致命的エラーは、真っ白な画面ではなくアプリのデザインのエラー画面で返す（詳細はエラーログへ）
\FuryoDacho\Core\ErrorHandler::register(($_ENV['APP_ENV'] ?? 'production') === 'development' || !empty($config['debug']));

// セッションをリクエスト開始時に必ず起動（CSRFトークン等のため）
$sessionName = $config['session_name'] ?? 'FURYO_SESS';
session_name($sessionName);
session_set_cookie_params([
    'lifetime' => 0,
    'path'     => '/',
    'secure'   => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off',
    'httponly' => true,
    'samesite' => 'Lax',
]);
if (session_status() === PHP_SESSION_NONE) {
    session_start(['use_strict_mode' => 1]);
}
if (!isset($_SESSION['_last_activity'])) {
    $_SESSION['_last_activity'] = time();
}

// ルーターを起動
$router = new \FuryoDacho\Core\Router();
$router->dispatchTenant();
