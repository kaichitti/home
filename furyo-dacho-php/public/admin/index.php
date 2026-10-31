<?php

/**
 * システム管理者側エントリポイント（別URL）
 * テナント側とは独立したルーティング・セッションで動作する。
 */

declare(strict_types=1);

// ============================================================
// BASE_PATH: アプリケーション本体の絶対パス。
// XREA デプロイ時は public/index.php と同じ値に書き換えること。
//   例: define('BASE_PATH', '/virtual/アカウント名/furyo-dacho');
// ============================================================
if (!defined('BASE_PATH')) {
    define('BASE_PATH', dirname(__DIR__, 2));
}

date_default_timezone_set('Asia/Tokyo');

spl_autoload_register(function (string $class): void {
    $base     = BASE_PATH . '/src/';
    $relative = str_replace('FuryoDacho\\', '', $class);
    $file     = $base . str_replace('\\', '/', $relative) . '.php';
    if (file_exists($file)) {
        require_once $file;
    }
});

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
// テナント側（FURYO_SESS）とは別名 Cookie を使い、完全に分離する
$sessionName = $config['admin_session_name'] ?? 'FURYO_ADMIN_SESS';
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

$router = new \FuryoDacho\Core\Router();
$router->dispatchAdmin();
