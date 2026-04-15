<?php
/**
 * lib/auth.php
 *
 * 管理画面（index.php）向けの簡易パスワード認証。
 * PHP の組み込みセッションと password_hash() / password_verify() を利用。
 *
 * CSRF トークンもここで発行する（POST フォーム保護用）。
 */

declare(strict_types=1);

require_once __DIR__ . '/../config.php';

/**
 * セッションを安全な設定で開始する（多重起動しても無害）。
 */
function pgw_session_start(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) {
        return;
    }
    $cfg = pgw_config();
    session_name($cfg['session_cookie_name']);
    session_set_cookie_params([
        'lifetime' => 0,
        'path'     => '/',
        'secure'   => (bool)$cfg['cookie_secure'],
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
    @session_start();
}

function pgw_is_logged_in(): bool
{
    pgw_session_start();
    return !empty($_SESSION['pgw_admin']);
}

/**
 * パスワードでログインを試みる。成功時 true。
 */
function pgw_login(string $password): bool
{
    $cfg  = pgw_config();
    $hash = (string)$cfg['admin_password_hash'];

    // パスワードハッシュが未設定のままログインできてしまうと危険なので明示的に拒否する。
    if ($hash === '' || !password_verify($password, $hash)) {
        // タイミング攻撃緩和のため、ハッシュ未設定時もダミー検証を行う。
        if ($hash === '') {
            password_verify($password, '$2y$10$abcdefghijklmnopqrstuuMOCKHASHMOCKHASHMOCKHASHMOCKHAS');
        }
        return false;
    }

    pgw_session_start();
    session_regenerate_id(true);
    $_SESSION['pgw_admin'] = true;
    $_SESSION['pgw_csrf']  = bin2hex(random_bytes(16));
    return true;
}

function pgw_logout(): void
{
    pgw_session_start();
    $_SESSION = [];
    if (ini_get('session.use_cookies')) {
        $p = session_get_cookie_params();
        setcookie(session_name(), '', [
            'expires'  => time() - 42000,
            'path'     => $p['path'],
            'domain'   => $p['domain'],
            'secure'   => $p['secure'],
            'httponly' => $p['httponly'],
            'samesite' => $p['samesite'] ?? 'Lax',
        ]);
    }
    session_destroy();
}

/**
 * 未ログインなら同一ディレクトリのログイン画面へリダイレクト。
 */
function pgw_require_login(): void
{
    if (!pgw_is_logged_in()) {
        pgw_redirect(pgw_url('index.php'));
    }
}

function pgw_csrf_token(): string
{
    pgw_session_start();
    if (empty($_SESSION['pgw_csrf'])) {
        $_SESSION['pgw_csrf'] = bin2hex(random_bytes(16));
    }
    return (string)$_SESSION['pgw_csrf'];
}

function pgw_csrf_check(?string $token): bool
{
    pgw_session_start();
    $expected = $_SESSION['pgw_csrf'] ?? '';
    return is_string($token) && $expected !== '' && hash_equals($expected, $token);
}
