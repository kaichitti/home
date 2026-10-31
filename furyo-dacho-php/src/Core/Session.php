<?php

namespace FuryoDacho\Core;

/**
 * セッション管理クラス
 * - HTTPOnly / SameSite=Lax Cookie
 * - 15分無操作で自動タイムアウト
 * - テナント側とシステム管理者側で独立したセッションを管理
 */
class Session
{
    private int $timeout;
    private string $sessionName;

    public function __construct(string $sessionName = 'FURYO_SESS', int $timeout = 900)
    {
        $this->sessionName = $sessionName;
        $this->timeout     = $timeout;
    }

    /**
     * セッションを開始する
     */
    public function start(): void
    {
        if (session_status() === PHP_SESSION_ACTIVE) {
            return;
        }

        session_name($this->sessionName);

        session_set_cookie_params([
            'lifetime' => 0,           // ブラウザ閉じたら消える
            'path'     => '/',
            'domain'   => '',
            // isset では HTTPS='off' でも true になり判定がぶれるため、実際に
            // HTTPS 接続のときのみ Secure を付与する（他のエントリポイントと統一）
            'secure'   => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off',
            'httponly' => true,
            'samesite' => 'Lax',
        ]);

        session_start([
            'cookie_httponly' => true,
            'cookie_samesite' => 'Lax',
            'use_strict_mode' => 1,
        ]);
    }

    /**
     * セッションが有効かチェックし、タイムアウトしていれば破棄する
     */
    public function isValid(): bool
    {
        $this->start();

        if (!isset($_SESSION['_last_activity'])) {
            return false;
        }

        if ((time() - $_SESSION['_last_activity']) > $this->timeout) {
            $this->destroy();
            return false;
        }

        // アクティビティ時刻を更新
        $_SESSION['_last_activity'] = time();
        return true;
    }

    /**
     * セッションを初期化（ログイン時に呼ぶ）
     */
    public function regenerate(): void
    {
        $this->start();
        session_regenerate_id(true);
        $_SESSION['_last_activity'] = time();
    }

    /**
     * セッション変数を設定
     */
    public function set(string $key, $value): void
    {
        $this->start();
        $_SESSION[$key] = $value;
    }

    /**
     * セッション変数を取得
     */
    public function get(string $key, $default = null)
    {
        $this->start();
        return $_SESSION[$key] ?? $default;
    }

    /**
     * セッション変数を削除
     */
    public function remove(string $key): void
    {
        $this->start();
        unset($_SESSION[$key]);
    }

    /**
     * フラッシュメッセージをセットする（次リクエストで一度だけ表示）
     *
     * @param string $key   メッセージキー（例: 'success', 'error'）
     * @param string $value メッセージ本文
     */
    public function setFlash(string $key, string $value): void
    {
        $this->start();
        $_SESSION['_flash_' . $key] = $value;
    }

    /**
     * フラッシュメッセージを取得して削除する
     *
     * @param string $key メッセージキー
     * @return string|null 存在しない場合は null
     */
    public function getFlash(string $key): ?string
    {
        $this->start();
        $flashKey = '_flash_' . $key;
        if (!isset($_SESSION[$flashKey])) {
            return null;
        }
        $value = $_SESSION[$flashKey];
        unset($_SESSION[$flashKey]);
        return (string)$value;
    }

    /**
     * セッションを完全に破棄（ログアウト時に呼ぶ）
     */
    public function destroy(): void
    {
        $this->start();
        $_SESSION = [];

        if (ini_get('session.use_cookies')) {
            $params = session_get_cookie_params();
            setcookie(
                session_name(),
                '',
                time() - 42000,
                $params['path'],
                $params['domain'],
                $params['secure'],
                $params['httponly']
            );
        }

        session_destroy();
    }
}
