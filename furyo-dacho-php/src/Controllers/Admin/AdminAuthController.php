<?php

namespace FuryoDacho\Controllers\Admin;

use FuryoDacho\Controllers\BaseController;

/**
 * システム管理者認証コントローラー
 * テナント側と完全に分離した別URLで動作する。
 * system_admins テーブルを使用し、テナントとは別セッションで管理。
 */
class AdminAuthController extends BaseController
{
    /**
     * システム管理者ログイン画面表示
     */
    public function showLoginForm(): void
    {
        if ($this->auth->isAdminLoggedIn()) {
            $this->response->redirect('/admin/index.php?page=dashboard');
            return;
        }

        $this->render('admin/login', [
            'csrf_token' => $this->generateCsrfToken(),
            'error'      => null,
        ], 'admin');
    }

    /**
     * ログイン画面表示 + POST処理（後方互換）
     */
    public function login(): void
    {
        if ($this->auth->isAdminLoggedIn()) {
            $this->response->redirect('/admin/index.php?page=dashboard');
            return;
        }

        if ($this->request->isPost()) {
            $this->handleLogin();
            return;
        }

        $this->render('admin/login', [
            'csrf_token' => $this->generateCsrfToken(),
            'error'      => null,
        ], 'admin');
    }

    /**
     * ログアウト処理
     */
    public function logout(): void
    {
        $this->auth->adminLogout();
        $this->response->redirect('/admin/index.php?page=login');
    }

    /** システム管理者パスワードの最小文字数（全テナントを管理できる最上位権限のため強めに設定） */
    private const ADMIN_PASSWORD_MIN_LENGTH = 12;

    /**
     * システム管理者のパスワード変更（GET: フォーム表示 / POST: 変更処理）
     *
     * 以前はシステム管理者のパスワードを変更する画面が存在せず、
     * DEPLOY.md・setup.php に公開されている初期パスワード（Admin7777）のまま
     * 運用されうる状態だった。初期パスワードでログインした場合は Router で
     * この画面へ強制的に誘導する。
     */
    public function changePassword(): void
    {
        $this->auth->requireAdminAuth();

        $admin  = $this->auth->adminUser();
        $forced = $this->auth->adminMustChangePassword();

        $renderForm = function (?string $error, bool $done = false) use ($forced): void {
            $this->render('admin/password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => $error,
                'forced'     => $forced,
                'done'       => $done,
                'minLength'  => self::ADMIN_PASSWORD_MIN_LENGTH,
            ], 'admin');
        };

        if (!$this->request->isPost()) {
            $renderForm(null, $this->request->get('done') === '1');
            return;
        }

        $this->verifyCsrf();

        // パスワードはエスケープ等の加工を避けるため $_POST から直接取得
        $current = is_string($_POST['current_password'] ?? null) ? $_POST['current_password'] : '';
        $new     = is_string($_POST['new_password'] ?? null) ? $_POST['new_password'] : '';
        $confirm = is_string($_POST['confirm_password'] ?? null) ? $_POST['confirm_password'] : '';

        // NUL文字を含むと password_hash() が例外（500エラー）になるため事前に弾く
        if (strpos($new, "\0") !== false) {
            $renderForm('パスワードに使用できない文字が含まれています。');
            return;
        }

        $stmt = $this->pdo->prepare("SELECT `password_hash` FROM `system_admins` WHERE `id` = ?");
        $stmt->execute([(int)($admin['id'] ?? 0)]);
        $row = $stmt->fetch();

        if ($row === false || !password_verify($current, $row['password_hash'])) {
            $renderForm('現在のパスワードが正しくありません。');
            return;
        }
        if ($new !== $confirm) {
            $renderForm('新しいパスワードと確認用パスワードが一致しません。');
            return;
        }
        // bcrypt は72バイトを超える部分を無視するため、長すぎるパスワードは受け付けない
        if (strlen($new) > 72) {
            $renderForm('パスワードは72バイト（半角72文字）以内で入力してください。');
            return;
        }
        if (mb_strlen($new) < self::ADMIN_PASSWORD_MIN_LENGTH
            || !preg_match('/[A-Za-z]/', $new)
            || !preg_match('/[0-9]/', $new)) {
            $renderForm('パスワードは' . self::ADMIN_PASSWORD_MIN_LENGTH . '文字以上で、英字・数字をそれぞれ1文字以上含めてください。');
            return;
        }
        if (hash_equals(\FuryoDacho\Core\Auth::DEFAULT_PASSWORD, $new)) {
            $renderForm('初期パスワードは使用できません。別のパスワードを設定してください。');
            return;
        }
        if (hash_equals($current, $new)) {
            $renderForm('現在と同じパスワードは設定できません。');
            return;
        }

        $upd = $this->pdo->prepare("UPDATE `system_admins` SET `password_hash` = ? WHERE `id` = ?");
        $upd->execute([password_hash($new, PASSWORD_BCRYPT), (int)$admin['id']]);

        $this->auth->setAdminMustChangePassword(false);

        // 監査ログ（システム管理者操作のため tenant_id / user_id は NULL）
        try {
            (new \FuryoDacho\Models\AuditLog($this->pdo))->log(
                null,
                null,
                (string)($admin['username'] ?? 'system_admin'),
                null,
                'edit',
                (int)$admin['id'],
                null,
                ['action' => 'system_admin_password_changed'],
                $this->request->ip()
            );
        } catch (\Throwable $e) {
            // 監査ログ失敗でパスワード変更自体は取り消さない
        }

        $this->response->redirect('/admin/index.php?page=password&done=1');
    }

    // ----------------------------------------------------------------
    // 内部処理
    // ----------------------------------------------------------------

    /**
     * ログインPOST処理
     */
    private function handleLogin(): void
    {
        $this->verifyCsrf();

        // 配列が送られた場合は空として扱う（以前は文字列 "Array" として照合していた）
        $username = $this->request->post('username');
        $username = is_string($username) ? trim($username) : '';
        $password = is_string($_POST['password'] ?? null) ? $_POST['password'] : ''; // htmlspecialchars を回避

        if (empty($username) || empty($password)) {
            $this->render('admin/login', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => 'ユーザー名とパスワードを入力してください。',
            ], 'admin');
            return;
        }

        $success = $this->auth->adminLogin($username, $password);

        if (!$success) {
            $this->render('admin/login', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => 'ユーザー名またはパスワードが正しくありません。',
            ], 'admin');
            return;
        }

        $this->response->redirect('/admin/index.php?page=dashboard');
    }
}
