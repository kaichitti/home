<?php

/**
 * アプリケーション全体設定
 * 機密情報はすべて環境変数から取得する。
 */

require_once __DIR__ . '/env.php';

return [
    // アプリケーション
    'app_name'        => '古物台帳管理システム',
    'app_url'         => furyo_env('APP_URL', 'http://localhost'),
    'app_env'         => furyo_env('APP_ENV', 'production'),
    'debug'           => furyo_env('APP_DEBUG', 'false') === 'true',

    // セッション
    'session_timeout' => (int)furyo_env('SESSION_TIMEOUT', '900'),  // 15分（秒）
    'session_name'    => 'FURYO_SESS',
    'admin_session_name' => 'FURYO_ADMIN_SESS',

    // ファイルアップロード
    'upload_dir'      => furyo_env('UPLOAD_DIR', defined('BASE_PATH') ? BASE_PATH . '/storage/uploads' : dirname(__DIR__) . '/storage/uploads'),
    'max_file_size'   => (int)furyo_env('MAX_FILE_SIZE', '52428800'),  // 50MB
    'allowed_mime_types' => [
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'application/pdf',
    ],

    // 暗号化
    // 環境変数 ENCRYPTION_KEY に 64 文字以上のランダム文字列を設定すること。
    // 例: php -r "echo bin2hex(random_bytes(32));" で生成可能。
    // 空のままでは Crypto クラスが RuntimeException をスローする。
    'encryption_key'  => furyo_env('ENCRYPTION_KEY', ''),

    // タイムゾーン
    'timezone'        => 'Asia/Tokyo',
];
