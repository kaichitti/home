<?php
/**
 * 古物台帳管理ツール - 初回セットアップウィザード
 *
 * !!! 警告 !!!
 * セットアップ完了後は必ずこのファイルをサーバーから削除してください。
 * このファイルが残っていると再初期化・DB上書きが可能な状態になります。
 *
 * !!! WARNING !!!
 * DELETE THIS FILE IMMEDIATELY AFTER SETUP IS COMPLETE.
 */

declare(strict_types=1);
session_start();

// ============================================================
// アプリ本体（src/ config/ database/ を含むディレクトリ）の絶対パス。
// setup.php を public_html/ に単体で置く分離構成の場合は、
// ここをアプリ本体のパスに書き換えること。
//   例: define('SETUP_BASE', '/virtual/アカウント名/furyo-dacho');
// setup.php をアプリ一式と同じ場所に置く場合は変更不要。
// ============================================================
if (!defined('SETUP_BASE')) {
    define('SETUP_BASE', __DIR__);
}
define('SCHEMA_FILE', SETUP_BASE . '/database/schema.sql');
define('ENV_FILE', SETUP_BASE . '/config/.env');

// ====================================================================
// ユーティリティ関数
// ====================================================================

function h(string $str): string
{
    return htmlspecialchars($str, ENT_QUOTES, 'UTF-8');
}

function stepLink(int $step): string
{
    return '?step=' . $step;
}

function sessionSet(string $key, mixed $value): void
{
    $_SESSION['setup'][$key] = $value;
}

function sessionGet(string $key, mixed $default = null): mixed
{
    return $_SESSION['setup'][$key] ?? $default;
}

// ====================================================================
// インストールロック
// ====================================================================
// config/.env が既に存在する（＝セットアップ済み）場合は、インストーラを
// 一切動作させない。これがないと、消し忘れた setup.php に第三者がアクセス
// することで、暗号化キーの再生成（既存の暗号化データが復号不能になる）や
// DB接続情報・設定の上書きが可能になってしまう。
//
// 再セットアップが必要な場合は、まず config/.env を削除してから実行すること。
//
// 例外: 「このブラウザセッションで今まさにセットアップを完了した」場合に限り、
// 完了画面（Step 5: 初回ログイン情報と削除の注意）の表示と、そこへの遷移だけを
// 完了から30分間許可する。完了フラグは config/.env が存在しない状態で
// Step 4 の生成に成功したセッションにしか付与されないため、第三者は取得できない。
// また例外経路では POST 処理（DB初期化・設定生成）を一切実行しない。
if (is_file(ENV_FILE)) {
    $reqStep       = (int)($_GET['step'] ?? 1);
    $completedAt   = (int)sessionGet('install_completed_at', 0);
    $justCompleted = sessionGet('install_completed') === true
        && $completedAt > 0
        && (time() - $completedAt) < 1800;

    if ($justCompleted && $_SERVER['REQUEST_METHOD'] === 'POST'
        && $reqStep === 4 && isset($_POST['next_to_step5'])) {
        header('Location: ' . stepLink(5));
        exit;
    }

    if (!($justCompleted && $_SERVER['REQUEST_METHOD'] === 'GET' && $reqStep === 5)) {
        http_response_code(403);
        header('Content-Type: text/html; charset=UTF-8');
        echo '<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">'
            . '<meta name="viewport" content="width=device-width, initial-scale=1">'
            . '<title>セットアップ済み</title></head><body style="font-family:sans-serif;'
            . 'background:#f4f5f7;color:#333;display:flex;min-height:100vh;align-items:center;'
            . 'justify-content:center;padding:24px;">'
            . '<div style="background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);'
            . 'max-width:520px;padding:28px 24px;">'
            . '<h1 style="font-size:1.1rem;color:#1e3a5f;margin:0 0 12px;">このシステムはセットアップ済みです</h1>'
            . '<p style="font-size:.9rem;line-height:1.8;color:#555;margin:0 0 12px;">'
            . '設定ファイル（config/.env）が既に存在するため、セキュリティのためインストーラは'
            . '停止しました。セットアップ済みの環境で再実行すると、暗号化キーの再生成により'
            . '既存の暗号化データが復号できなくなる恐れがあります。</p>'
            . '<p style="font-size:.9rem;line-height:1.8;color:#c0392b;margin:0;">'
            . '<strong>この setup.php は直ちにサーバーから削除してください。</strong><br>'
            . 'どうしても再セットアップが必要な場合のみ、先に config/.env を削除してください。'
            . '（初回ログイン情報は DEPLOY.md に記載しています）</p>'
            . '</div></body></html>';
        exit;
    }
}

// ====================================================================
// Step 判定
// ====================================================================

$step = (int)($_GET['step'] ?? 1);
$errors = [];
$success = [];

// ====================================================================
// POST 処理
// ====================================================================

if ($_SERVER['REQUEST_METHOD'] === 'POST') {

    // --- Step 2: DB接続テスト ---
    if ($step === 2 && isset($_POST['test_connection'])) {
        $host = trim($_POST['db_host'] ?? '');
        $name = trim($_POST['db_name'] ?? '');
        $user = trim($_POST['db_user'] ?? '');
        $pass = $_POST['db_pass'] ?? '';

        if ($host === '' || $name === '' || $user === '') {
            $errors[] = 'ホスト・データベース名・ユーザー名は必須です。';
        } else {
            try {
                $dsn = "mysql:host={$host};dbname={$name};charset=utf8mb4";
                $pdo = new PDO($dsn, $user, $pass, [
                    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                    PDO::ATTR_TIMEOUT => 5,
                ]);
                $pdo->query('SELECT 1');
                sessionSet('db_host', $host);
                sessionSet('db_name', $name);
                sessionSet('db_user', $user);
                sessionSet('db_pass', $pass);
                sessionSet('db_ok', true);
                $success[] = 'データベース接続に成功しました。';
            } catch (PDOException $e) {
                $errors[] = 'DB接続エラー: ' . $e->getMessage();
                sessionSet('db_ok', false);
            }
        }
    }

    // --- Step 2: 次へ（Step3へ進む） ---
    if ($step === 2 && isset($_POST['next_to_step3'])) {
        if (!sessionGet('db_ok')) {
            $errors[] = '先にDB接続テストを成功させてください。';
        } else {
            header('Location: ' . stepLink(3));
            exit;
        }
    }

    // --- Step 3: DB初期化実行 ---
    if ($step === 3 && isset($_POST['run_init'])) {
        if (!sessionGet('db_ok')) {
            $errors[] = 'DB設定が未確認です。Step 2からやり直してください。';
        } elseif (!file_exists(SCHEMA_FILE)) {
            $errors[] = 'schema.sql が見つかりません: ' . SCHEMA_FILE;
        } else {
            try {
                $host = sessionGet('db_host');
                $name = sessionGet('db_name');
                $user = sessionGet('db_user');
                $pass = sessionGet('db_pass');

                $dsn = "mysql:host={$host};dbname={$name};charset=utf8mb4";
                $pdo = new PDO($dsn, $user, $pass, [
                    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                ]);

                // schema.sql を読み込み、文単位に分割して実行
                $sql = file_get_contents(SCHEMA_FILE);

                // デリミタ分割（コメント行を除去してから実行）
                // セミコロンで分割して各文を実行
                $statements = array_filter(
                    array_map('trim', explode(';', $sql)),
                    fn($s) => $s !== ''
                );

                $executed = 0;
                foreach ($statements as $statement) {
                    // コメントのみの行はスキップ
                    $stripped = preg_replace('/--[^\n]*\n?/', '', $statement);
                    $stripped = trim($stripped);
                    if ($stripped === '') {
                        continue;
                    }
                    $pdo->exec($statement);
                    $executed++;
                }

                // 暗号化キー生成
                $encKey = bin2hex(random_bytes(32));
                sessionSet('encryption_key', $encKey);
                sessionSet('db_init_ok', true);

                $success[] = "DBの初期化が完了しました（{$executed} ステートメントを実行）。";
                $success[] = "暗号化キーを自動生成しました。";

            } catch (PDOException $e) {
                $errors[] = 'DB初期化エラー: ' . $e->getMessage();
                sessionSet('db_init_ok', false);
            }
        }
    }

    // --- Step 3: 次へ（Step4へ進む） ---
    if ($step === 3 && isset($_POST['next_to_step4'])) {
        if (!sessionGet('db_init_ok')) {
            $errors[] = '先にDB初期化を実行してください。';
        } else {
            header('Location: ' . stepLink(4));
            exit;
        }
    }

    // --- Step 4: 設定ファイル生成 ---
    if ($step === 4 && isset($_POST['generate_env'])) {
        if (!sessionGet('db_init_ok')) {
            $errors[] = 'DB初期化が完了していません。';
        } else {
            $appUrl   = rtrim(trim($_POST['app_url'] ?? ''), '/');
            $appEnv   = trim($_POST['app_env'] ?? 'production');
            $appDebug = isset($_POST['app_debug']) ? 'true' : 'false';
            $uploadDir = trim($_POST['upload_dir'] ?? '');

            if ($appUrl === '') {
                $errors[] = 'アプリケーションURLは必須です。';
            } elseif (preg_match('/[\x00-\x1F\x7F]/', $appUrl)
                || !filter_var($appUrl, FILTER_VALIDATE_URL)
                || !preg_match('#^https?://#i', $appUrl)) {
                // 改行等を含む値は .env への設定行の注入につながるため受け付けない
                $errors[] = 'アプリケーションURLは http:// または https:// から始まる正しいURLで入力してください。';
            } elseif ($uploadDir === '') {
                $errors[] = 'アップロードディレクトリは必須です。';
            } elseif (preg_match('/[\x00-\x1F\x7F]/', $uploadDir)) {
                $errors[] = 'アップロードディレクトリに使用できない文字が含まれています。';
            } elseif (!is_dir($uploadDir) && !@mkdir($uploadDir, 0700, true)) {
                // 存在しないディレクトリを設定すると、後でファイル添付が必ず失敗していた
                $errors[] = 'アップロードディレクトリを作成できませんでした。パスと書き込み権限を確認してください: ' . $uploadDir;
            } elseif (!is_writable($uploadDir)) {
                $errors[] = 'アップロードディレクトリに書き込めません。権限を確認してください: ' . $uploadDir;
            } else {
                $host = sessionGet('db_host');
                $name = sessionGet('db_name');
                $user = sessionGet('db_user');
                $pass = sessionGet('db_pass');
                $encKey = sessionGet('encryption_key');

                // .env は1行1設定のため、値に改行が含まれると任意の設定行を
                // 注入できてしまう（例: APP_DEBUG=true）。改行・制御文字を除去する。
                $envSafe = static fn ($v): string => (string)preg_replace('/[\x00-\x1F\x7F]/', '', (string)$v);
                $appEnv    = in_array($appEnv, ['production', 'development'], true) ? $appEnv : 'production';
                $appUrl    = $envSafe($appUrl);
                $uploadDir = $envSafe($uploadDir);
                $host      = $envSafe($host);
                $name      = $envSafe($name);
                $user      = $envSafe($user);
                $pass      = $envSafe($pass);

                $envContent = <<<ENV
# アプリケーション設定
APP_ENV={$appEnv}
APP_URL={$appUrl}
APP_DEBUG={$appDebug}

# 暗号化キー（自動生成 - 絶対に外部に漏洩させないこと）
ENCRYPTION_KEY={$encKey}

# データベース設定
DB_HOST={$host}
DB_NAME={$name}
DB_USER={$user}
DB_PASS={$pass}

# アップロードディレクトリ（絶対パス・webroot外）
UPLOAD_DIR={$uploadDir}
ENV;

                $configDir = SETUP_BASE . '/config';
                if (!is_dir($configDir)) {
                    mkdir($configDir, 0755, true);
                }

                if (file_put_contents(ENV_FILE, $envContent) !== false) {
                    // パーミッションを制限（オーナーのみ読み書き）
                    chmod(ENV_FILE, 0600);
                    sessionSet('env_ok', true);
                    // 完了画面のリンク用（以前は保存しておらず、リンク先が常に "/" になっていた）
                    sessionSet('app_url', $appUrl);
                    // このセッションでセットアップを完了した印（完了画面の表示のみ許可するため）
                    session_regenerate_id(true);
                    sessionSet('install_completed', true);
                    sessionSet('install_completed_at', time());
                    // .env へ書き込んだ機密情報はセッションに残さない
                    unset($_SESSION['setup']['db_pass'], $_SESSION['setup']['encryption_key']);
                    $success[] = 'config/.env を生成しました。';
                    $success[] = 'ファイルパーミッションを 0600 に設定しました。';
                } else {
                    $errors[] = 'config/.env の書き込みに失敗しました。config/ ディレクトリの書き込み権限を確認してください。';
                }
            }
        }
    }

    // --- Step 4: 次へ（Step5へ進む） ---
    if ($step === 4 && isset($_POST['next_to_step5'])) {
        if (!sessionGet('env_ok')) {
            $errors[] = '先に設定ファイルを生成してください。';
        } else {
            header('Location: ' . stepLink(5));
            exit;
        }
    }
}

// ====================================================================
// HTML出力
// ====================================================================

$stepTitles = [
    1 => '環境チェック',
    2 => 'DB接続テスト',
    3 => 'DB初期化',
    4 => '設定ファイル生成',
    5 => '完了',
];
$currentTitle = $stepTitles[$step] ?? '不明';

// Step 1: 環境チェック実行
$envChecks = [];
if ($step === 1) {
    // PHP バージョン
    $phpOk = version_compare(PHP_VERSION, '7.4.0', '>=');
    $envChecks[] = [
        'label' => 'PHP バージョン (' . PHP_VERSION . ')',
        'ok' => $phpOk,
        'note' => $phpOk ? '' : 'PHP 7.4 以上が必要です',
    ];

    // 必須拡張
    $requiredExts = ['pdo', 'pdo_mysql', 'openssl', 'fileinfo', 'mbstring'];
    foreach ($requiredExts as $ext) {
        $loaded = extension_loaded($ext);
        $envChecks[] = [
            'label' => "拡張モジュール: {$ext}",
            'ok' => $loaded,
            'note' => $loaded ? '' : "{$ext} が有効になっていません",
        ];
    }

    // storage/uploads/ 書き込み権限
    // 配布ZIPには storage/ が含まれないため、以前はここが必ず NG になり先へ進めなかった。
    // 無ければ作成し（外部から読めないよう .htaccess も置く）、そのうえで書き込み可否を確認する。
    $uploadsDir = SETUP_BASE . '/storage/uploads';
    if (!is_dir($uploadsDir)) {
        @mkdir($uploadsDir, 0700, true);
    }
    if (is_dir($uploadsDir) && !is_file($uploadsDir . '/.htaccess')) {
        @file_put_contents($uploadsDir . '/.htaccess', "Require all denied\n");
    }
    $writable = is_dir($uploadsDir) && is_writable($uploadsDir);
    $envChecks[] = [
        'label' => 'storage/uploads/ 書き込み権限',
        'ok' => $writable,
        'note' => $writable ? '' : 'ディレクトリが存在しないか、書き込み不可です',
    ];

    // config/ 書き込み権限
    $configDir = SETUP_BASE . '/config';
    $configWritable = is_dir($configDir) && is_writable($configDir);
    $envChecks[] = [
        'label' => 'config/ 書き込み権限',
        'ok' => $configWritable,
        'note' => $configWritable ? '' : 'config/ ディレクトリへの書き込みが必要です',
    ];

    $allOk = array_reduce($envChecks, fn($carry, $c) => $carry && $c['ok'], true);
}

?>
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>セットアップ - 古物台帳管理システム</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    background: #f4f5f7;
    color: #333;
    font-size: 15px;
    line-height: 1.6;
}
.wrapper {
    max-width: 720px;
    margin: 40px auto;
    padding: 0 16px;
}
.header {
    background: #1a1a2e;
    color: #fff;
    padding: 20px 28px;
    border-radius: 8px 8px 0 0;
}
.header h1 { font-size: 20px; font-weight: 700; }
.header p { font-size: 13px; color: #aaa; margin-top: 4px; }
.steps {
    display: flex;
    background: #16213e;
    padding: 12px 28px;
}
.step-item {
    flex: 1;
    text-align: center;
    font-size: 12px;
    color: #666;
    position: relative;
}
.step-item.active { color: #4fc3f7; font-weight: 700; }
.step-item.done { color: #81c784; }
.step-num {
    display: inline-block;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: #333;
    line-height: 24px;
    margin-bottom: 4px;
    font-weight: 700;
}
.step-item.active .step-num { background: #4fc3f7; color: #000; }
.step-item.done .step-num { background: #81c784; color: #000; }
.card {
    background: #fff;
    padding: 32px 28px;
    border-radius: 0 0 8px 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
h2 { font-size: 18px; font-weight: 700; margin-bottom: 20px; color: #1a1a2e; }
.alert {
    padding: 12px 16px;
    border-radius: 6px;
    margin-bottom: 16px;
    font-size: 14px;
}
.alert-danger { background: #fff3f3; border-left: 4px solid #e53935; color: #c62828; }
.alert-success { background: #f1f8e9; border-left: 4px solid #43a047; color: #2e7d32; }
.alert-warning {
    background: #fff8e1;
    border-left: 4px solid #ffb300;
    color: #6d4c00;
    font-size: 14px;
}
.alert-warning strong { display: block; font-size: 16px; margin-bottom: 6px; }
.check-table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
.check-table th {
    background: #f4f5f7;
    text-align: left;
    padding: 10px 12px;
    font-size: 13px;
    color: #555;
    border-bottom: 2px solid #e0e0e0;
}
.check-table td {
    padding: 10px 12px;
    border-bottom: 1px solid #eee;
    font-size: 14px;
}
.ok { color: #43a047; font-weight: 700; }
.ng { color: #e53935; font-weight: 700; }
.note-ng { color: #e53935; font-size: 12px; margin-top: 2px; }
.form-group { margin-bottom: 18px; }
label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 6px; color: #444; }
label .required { color: #e53935; margin-left: 4px; }
input[type="text"], input[type="password"], input[type="url"], select {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid #ccc;
    border-radius: 6px;
    font-size: 14px;
    transition: border-color 0.2s;
}
input:focus, select:focus {
    outline: none;
    border-color: #4fc3f7;
    box-shadow: 0 0 0 3px rgba(79,195,247,0.15);
}
.hint { font-size: 12px; color: #888; margin-top: 4px; }
.btn {
    display: inline-block;
    padding: 10px 24px;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    border: none;
    transition: opacity 0.2s;
    text-decoration: none;
}
.btn:hover { opacity: 0.85; }
.btn-primary { background: #1976d2; color: #fff; }
.btn-success { background: #43a047; color: #fff; }
.btn-secondary { background: #78909c; color: #fff; }
.btn-danger { background: #e53935; color: #fff; }
.btn-row { display: flex; gap: 12px; align-items: center; margin-top: 24px; }
.key-display {
    background: #1a1a2e;
    color: #4fc3f7;
    font-family: monospace;
    font-size: 13px;
    padding: 12px 16px;
    border-radius: 6px;
    word-break: break-all;
    margin-bottom: 12px;
}
.final-warning {
    background: #ffebee;
    border: 2px solid #e53935;
    border-radius: 8px;
    padding: 20px 24px;
    margin-bottom: 24px;
}
.final-warning h3 { color: #b71c1c; font-size: 18px; margin-bottom: 12px; }
.final-warning p, .final-warning li { font-size: 14px; color: #b71c1c; }
.final-warning ul { padding-left: 20px; margin-top: 8px; }
.login-info {
    background: #e8f5e9;
    border: 1px solid #a5d6a7;
    border-radius: 8px;
    padding: 20px 24px;
    margin-bottom: 24px;
}
.login-info h3 { color: #2e7d32; margin-bottom: 12px; }
.login-info table { width: 100%; border-collapse: collapse; }
.login-info td { padding: 6px 8px; font-size: 14px; }
.login-info td:first-child { font-weight: 600; width: 200px; color: #555; }
.section-divider { border: none; border-top: 1px solid #eee; margin: 24px 0; }
</style>
</head>
<body>
<div class="wrapper">

<div class="header">
    <h1>古物台帳管理システム - セットアップウィザード</h1>
    <p>初回のみ実行。完了後は必ず setup.php を削除してください。</p>
</div>

<div class="steps">
<?php foreach ($stepTitles as $n => $title): ?>
    <?php
    $cls = 'step-item';
    if ($n === $step) $cls .= ' active';
    elseif ($n < $step) $cls .= ' done';
    ?>
    <div class="<?= $cls ?>">
        <div class="step-num"><?= $n ?></div>
        <div><?= h($title) ?></div>
    </div>
<?php endforeach; ?>
</div>

<div class="card">

<?php if ($errors): ?>
    <div class="alert alert-danger">
        <?php foreach ($errors as $e): ?>
            <div><?= h($e) ?></div>
        <?php endforeach; ?>
    </div>
<?php endif; ?>

<?php if ($success): ?>
    <div class="alert alert-success">
        <?php foreach ($success as $s): ?>
            <div><?= h($s) ?></div>
        <?php endforeach; ?>
    </div>
<?php endif; ?>

<!-- ================================================================
     Step 1: 環境チェック
     ================================================================ -->
<?php if ($step === 1): ?>
<h2>Step 1: 環境チェック</h2>

<table class="check-table">
    <thead>
        <tr>
            <th>チェック項目</th>
            <th>結果</th>
        </tr>
    </thead>
    <tbody>
    <?php foreach ($envChecks as $check): ?>
        <tr>
            <td><?= h($check['label']) ?></td>
            <td>
                <?php if ($check['ok']): ?>
                    <span class="ok">OK</span>
                <?php else: ?>
                    <span class="ng">NG</span>
                    <?php if ($check['note']): ?>
                        <div class="note-ng"><?= h($check['note']) ?></div>
                    <?php endif; ?>
                <?php endif; ?>
            </td>
        </tr>
    <?php endforeach; ?>
    </tbody>
</table>

<?php if ($allOk): ?>
    <div class="alert alert-success">全てのチェックが通過しました。次のステップへ進めます。</div>
    <div class="btn-row">
        <a href="<?= stepLink(2) ?>" class="btn btn-primary">次へ: DB接続テスト</a>
    </div>
<?php else: ?>
    <div class="alert alert-danger">チェックに失敗した項目があります。サーバー設定を確認してから再度アクセスしてください。</div>
    <div class="btn-row">
        <a href="<?= stepLink(1) ?>" class="btn btn-secondary">再チェック</a>
    </div>
<?php endif; ?>

<!-- ================================================================
     Step 2: DB接続テスト
     ================================================================ -->
<?php elseif ($step === 2): ?>
<h2>Step 2: DB接続テスト</h2>
<p style="margin-bottom:20px;color:#555;font-size:14px;">XREAのコントロールパネルで作成したMySQLのデータベース情報を入力してください。</p>

<form method="POST" action="<?= stepLink(2) ?>">
    <div class="form-group">
        <label>DBホスト <span class="required">*</span></label>
        <input type="text" name="db_host" value="<?= h(sessionGet('db_host', 'localhost')) ?>" placeholder="localhost">
        <div class="hint">XREAでは通常 localhost</div>
    </div>
    <div class="form-group">
        <label>データベース名 <span class="required">*</span></label>
        <input type="text" name="db_name" value="<?= h(sessionGet('db_name', '')) ?>" placeholder="例: your_dbname">
    </div>
    <div class="form-group">
        <label>DBユーザー名 <span class="required">*</span></label>
        <input type="text" name="db_user" value="<?= h(sessionGet('db_user', '')) ?>" placeholder="例: your_dbuser">
    </div>
    <div class="form-group">
        <label>DBパスワード</label>
        <input type="password" name="db_pass" placeholder="DBパスワード">
    </div>
    <div class="btn-row">
        <button type="submit" name="test_connection" value="1" class="btn btn-primary">接続テスト</button>
    </div>
</form>

<?php if (sessionGet('db_ok')): ?>
<hr class="section-divider">
<form method="POST" action="<?= stepLink(2) ?>">
    <div class="btn-row">
        <button type="submit" name="next_to_step3" value="1" class="btn btn-success">次へ: DB初期化</button>
    </div>
</form>
<?php endif; ?>

<!-- ================================================================
     Step 3: DB初期化
     ================================================================ -->
<?php elseif ($step === 3): ?>
<h2>Step 3: DB初期化</h2>

<div class="alert alert-warning">
    <strong>注意</strong>
    database/schema.sql を実行してテーブルを作成します。<br>
    既にテーブルが存在する場合は CREATE TABLE IF NOT EXISTS のため上書きされませんが、
    初期データ（INSERT IGNORE）は重複しない場合のみ挿入されます。
</div>

<p style="margin-bottom:20px;color:#555;font-size:14px;">
    接続先: <strong><?= h(sessionGet('db_host', '')) ?></strong> /
    データベース: <strong><?= h(sessionGet('db_name', '')) ?></strong>
</p>

<form method="POST" action="<?= stepLink(3) ?>">
    <div class="btn-row">
        <button type="submit" name="run_init" value="1" class="btn btn-danger">DBを初期化する</button>
    </div>
</form>

<?php if (sessionGet('db_init_ok')): ?>
<hr class="section-divider">
<p style="font-size:14px;color:#555;margin-bottom:16px;">
    生成された暗号化キー（config/.env に自動書き込みされます）:
</p>
<div class="key-display"><?= h(sessionGet('encryption_key', '')) ?></div>
<form method="POST" action="<?= stepLink(3) ?>">
    <div class="btn-row">
        <button type="submit" name="next_to_step4" value="1" class="btn btn-success">次へ: 設定ファイル生成</button>
    </div>
</form>
<?php endif; ?>

<!-- ================================================================
     Step 4: 設定ファイル生成
     ================================================================ -->
<?php elseif ($step === 4): ?>
<h2>Step 4: 設定ファイル生成</h2>
<p style="margin-bottom:20px;color:#555;font-size:14px;">config/.env を生成します。</p>

<form method="POST" action="<?= stepLink(4) ?>">
    <div class="form-group">
        <label>アプリケーションURL <span class="required">*</span></label>
        <input type="url" name="app_url" value="<?= h(sessionGet('app_url', 'https://')) ?>" placeholder="https://yourdomain.com">
        <div class="hint">末尾スラッシュ不要。例: https://example.com</div>
    </div>
    <div class="form-group">
        <label>環境</label>
        <select name="app_env">
            <option value="production" <?= sessionGet('app_env', 'production') === 'production' ? 'selected' : '' ?>>production（本番）</option>
            <option value="development" <?= sessionGet('app_env') === 'development' ? 'selected' : '' ?>>development（開発）</option>
        </select>
    </div>
    <div class="form-group">
        <label>
            <input type="checkbox" name="app_debug" value="1" <?= sessionGet('app_debug') ? 'checked' : '' ?>>
            デバッグモード有効（本番環境では OFF を推奨）
        </label>
    </div>
    <div class="form-group">
        <label>アップロードディレクトリ（絶対パス） <span class="required">*</span></label>
        <input type="text" name="upload_dir" value="<?= h(sessionGet('upload_dir', __DIR__ . '/storage/uploads')) ?>" placeholder="/home/アカウント名/furyo-dacho-uploads">
        <div class="hint">Webルート（public_html/）の外に配置してください。</div>
    </div>
    <div class="btn-row">
        <button type="submit" name="generate_env" value="1" class="btn btn-primary">config/.env を生成</button>
    </div>
</form>

<?php if (sessionGet('env_ok')): ?>
<hr class="section-divider">
<form method="POST" action="<?= stepLink(4) ?>">
    <div class="btn-row">
        <button type="submit" name="next_to_step5" value="1" class="btn btn-success">完了画面へ</button>
    </div>
</form>
<?php endif; ?>

<!-- ================================================================
     Step 5: 完了
     ================================================================ -->
<?php elseif ($step === 5): ?>
<h2>Step 5: セットアップ完了</h2>

<div class="final-warning">
    <h3>!!! 重要 !!! setup.php を今すぐ削除してください</h3>
    <p>このファイルが残っていると、誰でもDBを再初期化・設定を上書きできる状態になります。</p>
    <ul>
        <li>FTPクライアントで <strong>setup.php</strong> を今すぐ削除してください</li>
        <li>削除確認後、ログインページへ進んでください</li>
    </ul>
</div>

<div class="login-info">
    <h3>初回ログイン情報</h3>
    <table>
        <tr>
            <td>テナント側URL</td>
            <td><a href="<?= h(sessionGet('app_url', '/')) ?>/" target="_blank"><?= h(sessionGet('app_url', '/')) ?>/</a></td>
        </tr>
        <tr>
            <td>テナントコード</td>
            <td><code>honsha</code></td>
        </tr>
        <tr>
            <td>メールアドレス</td>
            <td><code>admin@example.com</code></td>
        </tr>
        <tr>
            <td>パスワード</td>
            <td><code>Admin7777</code>（初回ログイン時に変更必須）</td>
        </tr>
    </table>
    <hr style="margin:12px 0;border:none;border-top:1px solid #c8e6c9;">
    <table>
        <tr>
            <td>システム管理者URL</td>
            <td><a href="<?= h(sessionGet('app_url', '/')) ?>/admin/" target="_blank"><?= h(sessionGet('app_url', '/')) ?>/admin/</a></td>
        </tr>
        <tr>
            <td>ユーザー名</td>
            <td><code>admin</code></td>
        </tr>
        <tr>
            <td>パスワード</td>
            <td><code>Admin7777</code>（初回ログイン時に変更必須）</td>
        </tr>
    </table>
</div>

<div class="btn-row">
    <a href="<?= h(sessionGet('app_url', '/')) ?>/index.php?page=login" class="btn btn-primary" target="_blank">ログインページへ</a>
</div>

<?php endif; ?>

</div><!-- /.card -->
</div><!-- /.wrapper -->
</body>
</html>
