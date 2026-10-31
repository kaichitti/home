<?php

/**
 * テナント側エントリポイント（XREA public_html 直置き対応版）
 * 全リクエストをここで受け取り Router に渡す。
 */

declare(strict_types=1);

// タイムゾーン設定
date_default_timezone_set('Asia/Tokyo');

// BASE_PATH = このファイルのディレクトリ（= public_html/ 相当）
define('BASE_PATH', __DIR__);

// オートローダー（Composerがある場合は vendor/autoload.php に差し替える）
spl_autoload_register(function (string $class): void {
    $relative = str_replace('FuryoDacho\\', '', $class);
    $file     = BASE_PATH . '/src/' . str_replace('\\', '/', $relative) . '.php';
    if (file_exists($file)) {
        require_once $file;
    }
});

// config を BASE_PATH 基準で読み込む
$config = require BASE_PATH . '/config/config.php';

// 本番環境ではエラー表示を抑制（APP_ENV または debug 設定で切り替え）
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
