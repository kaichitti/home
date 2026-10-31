<?php

/**
 * データベース接続設定
 * 値は環境変数から取得する。未設定時はローカル開発用デフォルト値を使用。
 */

require_once __DIR__ . '/env.php';

$appEnv = furyo_env('APP_ENV', 'production');
$isCli = PHP_SAPI === 'cli';
$allowLocalFallback = $isCli && $appEnv === 'development';

$dbHost = furyo_env('DB_HOST', $allowLocalFallback ? 'localhost' : null);
$dbName = furyo_env('DB_NAME', $allowLocalFallback ? 'furyo_dacho' : null);
$dbUser = furyo_env('DB_USER', $allowLocalFallback ? 'root' : null);
$dbPass = furyo_env('DB_PASS', $allowLocalFallback ? '' : null);
$dbCharset = furyo_env('DB_CHARSET', 'utf8mb4');

$missing = [];
foreach (['DB_HOST' => $dbHost, 'DB_NAME' => $dbName, 'DB_USER' => $dbUser] as $key => $value) {
    if ($value === null || $value === '') {
        $missing[] = $key;
    }
}

if (!$allowLocalFallback && $dbUser === 'root' && furyo_env('ALLOW_ROOT_DB', 'false') !== 'true') {
    throw new RuntimeException('DB_USER is set to root. Set the hosting MySQL user in config/.env, or set ALLOW_ROOT_DB=true only for local development.');
}

if (!empty($missing)) {
    throw new RuntimeException('Database config is incomplete. Missing: ' . implode(', ', $missing) . '. Create config/.env with DB_HOST, DB_NAME, DB_USER, and DB_PASS.');
}

return [
    'host'     => $dbHost,
    'dbname'   => $dbName,
    'username' => $dbUser,
    'password' => $dbPass ?? '',
    'charset'  => $dbCharset,
    'source'   => [
        'config_path' => __FILE__,
        'env_path'    => __DIR__ . '/.env',
        'env_exists'  => is_file(__DIR__ . '/.env'),
        'app_env'     => $appEnv,
    ],
];
