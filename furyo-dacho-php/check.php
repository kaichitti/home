<?php
// 環境診断ファイル - 動作確認後に削除すること

// ============================================================
// BASE_PATH はアクセス制御ガードより「前」に確定させること（重要）。
// 分離構成（src/ config/ を public_html の外に置き、check.php だけを
// public_html に置く構成）では、ここをアプリ本体の実パスに書き換えること。
//   例: define('BASE_PATH', '/virtual/アカウント名/furyo-dacho');
// ※ ガードより後ろで BASE_PATH を定義すると、ガードが webroot 側を見て
//    config/.env を発見できず、認証を回避して診断情報が漏えいする。
// ============================================================
if (!defined('BASE_PATH')) {
    define('BASE_PATH', __DIR__);
}

// アクセス制御: 本番稼働中（config/.env が存在する）の環境では、
// 診断情報（DBホスト・テナント/ユーザー件数・サーバー実パス等）の
// 情報漏えいを防ぐため、システム管理者ログインを必須とする。
// 未設定（初回デプロイ）の場合のみ、パス確認・拡張チェック用に素通しする。
(function (): void {
    $base = BASE_PATH;
    if (!is_file($base . '/config/.env')) {
        return; // 未セットアップ → 機微情報はまだ無いので診断を許可
    }
    spl_autoload_register(function (string $class) use ($base): void {
        if (strpos($class, 'FuryoDacho\\') !== 0) {
            return;
        }
        $file = $base . '/src/' . str_replace('\\', '/', str_replace('FuryoDacho\\', '', $class)) . '.php';
        if (is_file($file)) {
            require_once $file;
        }
    });
    $loggedIn = false;
    try {
        $auth = new \FuryoDacho\Core\Auth();
        // 初期パスワードのままのセッションでは表示しない
        $loggedIn = $auth->isAdminLoggedIn() && !$auth->adminMustChangePassword();
    } catch (\Throwable $e) {
        $loggedIn = false;
    }
    if ($loggedIn) {
        return;
    }
    http_response_code(403);
    header('Content-Type: text/html; charset=UTF-8');
    echo 'このシステムは稼働中です。診断を表示するには /admin/ からシステム管理者としてログインしてください（初期パスワードのままの場合は先に変更が必要です）。'
        . ' なお、この check.php は確認後すぐに削除してください。';
    exit;
})();

echo '<pre>';
echo 'PHP Version: ' . PHP_VERSION . "\n";
echo 'PHP >= 7.4: ' . (version_compare(PHP_VERSION, '7.4.0', '>=') ? 'OK' : 'NG') . "\n";

// 必須拡張確認
$exts = ['pdo', 'pdo_mysql', 'openssl', 'fileinfo', 'mbstring', 'session'];
foreach ($exts as $ext) {
    echo "ext-{$ext}: " . (extension_loaded($ext) ? 'OK' : 'MISSING') . "\n";
}

// BASE_PATH はファイル先頭（アクセス制御ガードより前）で定義済み。
// 分離構成の場合は先頭の define('BASE_PATH', ...) を書き換えること。
echo 'BASE_PATH: ' . BASE_PATH . "\n";

// configロード
$configPath = BASE_PATH . '/config/config.php';
echo 'config.php: ' . (file_exists($configPath) ? 'EXISTS' : 'MISSING') . "\n";
if (file_exists($configPath)) {
    $config = require $configPath;
    $dbConfCheck = require BASE_PATH . '/config/database.php';
    echo 'DB_HOST: ' . ($dbConfCheck['host'] ?? 'N/A') . "\n";
}

// DBテスト
try {
    $dbConf = require BASE_PATH . '/config/database.php';
    $dsn = "mysql:host={$dbConf['host']};dbname={$dbConf['dbname']};charset={$dbConf['charset']}";
    $pdo = new PDO($dsn, $dbConf['username'], $dbConf['password'], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    echo "DB接続: OK\n";
    $row = $pdo->query("SELECT COUNT(*) FROM tenants")->fetchColumn();
    echo "テナント数: {$row}\n";
    $row2 = $pdo->query("SELECT COUNT(*) FROM users")->fetchColumn();
    echo "ユーザー数: {$row2}\n";
} catch (Exception $e) {
    echo "DB接続エラー: " . $e->getMessage() . "\n";
}

// オートローダーテスト
spl_autoload_register(function($class) {
    $relative = str_replace('FuryoDacho\\', '', $class);
    $file = BASE_PATH . '/src/' . str_replace('\\', '/', $relative) . '.php';
    if (file_exists($file)) require_once $file;
});
$testClasses = ['FuryoDacho\Core\Router', 'FuryoDacho\Core\Auth', 'FuryoDacho\Models\Ledger'];
foreach ($testClasses as $cls) {
    echo "class {$cls}: " . (class_exists($cls) ? 'OK' : 'LOAD_ERROR') . "\n";
}

// セッションテスト
session_start();
$_SESSION['_test'] = 'ok';
echo 'Session: ' . ($_SESSION['_test'] === 'ok' ? 'OK' : 'NG') . "\n";

// ストレージ書き込みテスト（config/.env の UPLOAD_DIR を確認する。
// 以前は常に storage/uploads を見ており、推奨どおり webroot 外に置いた場合に誤判定していた）
$uploadDir = isset($config['upload_dir']) ? (string)$config['upload_dir'] : BASE_PATH . '/storage/uploads';
echo 'UPLOAD_DIR (' . $uploadDir . '): ' . (is_dir($uploadDir) && is_writable($uploadDir) ? 'writable' : 'NOT writable') . "\n";

echo '</pre>';
echo '<b style="color:green">診断完了。このファイルは確認後すぐに削除してください。</b>';
