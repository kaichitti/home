<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\User;
use FuryoDacho\Models\AuditLog;
use FuryoDacho\Helpers\Validator;

/**
 * テナントユーザー認証コントローラー
 * ログインフォーム: テナントコード + メールアドレス + パスワード
 */
class AuthController extends BaseController
{
    /**
     * ログイン画面表示 / POST処理
     */
    public function showLoginForm(): void
    {
        if ($this->auth->isLoggedIn()) {
            $this->response->redirect('/index.php?page=dashboard');
            return;
        }

        $this->render('auth/login', [
            'csrf_token' => $this->generateCsrfToken(),
            'error'      => null,
        ]);
    }

    /**
     * 後方互換: login() は showLoginForm() + POST処理を統合
     */
    public function login(): void
    {
        if ($this->auth->isLoggedIn()) {
            $this->response->redirect('/index.php?page=dashboard');
            return;
        }

        if ($this->request->isPost()) {
            $this->handleLogin();
            return;
        }

        $this->render('auth/login', [
            'csrf_token' => $this->generateCsrfToken(),
            'error'      => null,
        ]);
    }

    /**
     * ログアウト処理
     */
    public function logout(): void
    {
        $this->auth->logout();
        $this->response->redirect('/index.php?page=login');
    }

    /**
     * パスワード変更画面表示 + POST処理
     * GET: フォーム表示 / POST: 変更処理
     */
    public function changePassword(): void
    {
        $this->auth->requireAuth();

        if (!$this->request->isPost()) {
            $this->render('auth/change_password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => null,
            ]);
            return;
        }

        $this->verifyCsrf();

        $data      = $this->request->all();
        $validator = new Validator($data, ['current_password' => '現在のパスワード', 'new_password' => '新しいパスワード', 'confirm_password' => '確認用パスワード']);

        if (!$validator->validate([
            'current_password' => 'required|min:1',
            'new_password'     => 'required|min:8',
            'confirm_password' => 'required|min:1',
        ])) {
            $this->render('auth/change_password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => '入力内容を確認してください。',
                'errors'     => $validator->firstErrors(),
            ]);
            return;
        }

        // htmlspecialchars によるサニタイズを避けるため $_POST から直接取得する
        $newPassword     = is_string($_POST['new_password'] ?? null) ? $_POST['new_password'] : '';
        $confirmPassword = is_string($_POST['confirm_password'] ?? null) ? $_POST['confirm_password'] : '';
        $currentPassword = is_string($_POST['current_password'] ?? null) ? $_POST['current_password'] : '';

        // NUL文字を含むと password_hash() が例外（500エラー）になるため事前に弾く
        if (strpos($newPassword, "\0") !== false) {
            $this->render('auth/change_password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => 'パスワードに使用できない文字が含まれています。',
            ]);
            return;
        }

        // 現在と同じパスワードへの「変更」は認めない（初回変更の強制を実質的に回避できないように）
        if ($newPassword !== '' && hash_equals($currentPassword, $newPassword)) {
            $this->render('auth/change_password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => '現在と同じパスワードは設定できません。',
            ]);
            return;
        }

        // 新パスワード確認一致チェック
        if ($newPassword !== $confirmPassword) {
            $this->render('auth/change_password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => '新しいパスワードと確認用パスワードが一致しません。',
            ]);
            return;
        }

        // パスワードポリシー検証（8文字以上・英字と数字を含む）
        if (!$this->isValidPasswordPolicy($newPassword)) {
            $this->render('auth/change_password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => 'パスワードは8文字以上で、英字・数字をそれぞれ1文字以上含めてください。',
            ]);
            return;
        }

        // 公開されている初期パスワード（Admin7777）への再設定は禁止
        // （ポリシー上は条件を満たしてしまうため個別に拒否する）
        if (hash_equals(\FuryoDacho\Core\Auth::DEFAULT_PASSWORD, $newPassword)) {
            $this->render('auth/change_password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => '初期パスワードは使用できません。別のパスワードを設定してください。',
            ]);
            return;
        }

        $userId   = $this->auth->getUserId();
        $tenantId = $this->auth->getTenantId();

        $userModel = new User($this->pdo);
        $user      = $userModel->findById($userId, $tenantId);

        if ($user === null) {
            $this->response->redirect('/index.php?page=login');
            return;
        }

        // 現在のパスワード照合（htmlspecialchars を避けるため $_POST から直接取得）
        if (!password_verify($currentPassword, $user['password_hash'])) {
            $this->render('auth/change_password', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => '現在のパスワードが正しくありません。',
            ]);
            return;
        }

        // bcryptでパスワード更新
        $userModel->changePassword($userId, $tenantId, $newPassword);

        // セッション上の強制変更フラグをクリア（DBは changePassword() 内で更新済み）
        $this->auth->setMustChangePassword(false);

        // 監査ログ記録
        $auditLog = new AuditLog($this->pdo);
        $auditLog->log(
            $tenantId,
            $userId,
            $user['display_name'],
            null,
            'edit',
            $userId,
            null,
            ['action' => 'password_changed'],
            $this->request->ip()
        );

        // 変更が完了したことを利用者に伝える（以前は何も表示されずダッシュボードへ移動していた）
        (new \FuryoDacho\Core\Session())->setFlash('success', 'パスワードを変更しました。次回から新しいパスワードでログインしてください。');
        $this->response->redirect('/index.php?page=dashboard');
    }

    /**
     * アカウント設定（メールアドレス変更）
     * GET: フォーム表示 / POST: 変更処理
     *
     * メールアドレスはログインIDのため、現在のパスワード再確認を必須とする。
     */
    public function account(): void
    {
        $this->auth->requireAuth();

        $userId    = $this->auth->getUserId();
        $tenantId  = $this->auth->getTenantId();
        $userModel = new User($this->pdo);
        $user      = $userModel->findById($userId, $tenantId);

        if ($user === null) {
            $this->response->redirect('/index.php?page=login');
            return;
        }

        if (!$this->request->isPost()) {
            $this->render('auth/account', [
                'currentEmail' => $user['email'],
                'error'        => null,
            ]);
            return;
        }

        $this->verifyCsrf();

        $newEmail = $this->request->post('new_email', '');
        $newEmail = is_string($newEmail) ? trim($newEmail) : '';
        // パスワードはエスケープを避けるため $_POST から直接取得
        $password = is_string($_POST['current_password'] ?? null) ? $_POST['current_password'] : '';

        $renderError = function (string $message) use ($user): void {
            $this->render('auth/account', [
                'currentEmail' => $user['email'],
                'error'        => $message,
            ]);
        };

        if ($newEmail === '' || !filter_var($newEmail, FILTER_VALIDATE_EMAIL)) {
            $renderError('正しいメールアドレス形式で入力してください。');
            return;
        }
        if (mb_strlen($newEmail) > 255) {
            $renderError('メールアドレスは255文字以内で入力してください。');
            return;
        }
        if ($newEmail === $user['email']) {
            $renderError('現在のメールアドレスと同じです。');
            return;
        }
        if (!password_verify($password, $user['password_hash'])) {
            $renderError('現在のパスワードが正しくありません。');
            return;
        }

        // テナント内での重複チェック（自分自身を除外）
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) FROM `users` WHERE `tenant_id` = ? AND `email` = ? AND `id` != ?"
        );
        $stmt->execute([$tenantId, $newEmail, $userId]);
        if ((int)$stmt->fetchColumn() > 0) {
            $renderError('このメールアドレスはすでに使用されています。');
            return;
        }

        $userModel->changeEmail($userId, $tenantId, $newEmail);

        // 監査ログ（変更前後のアドレスを記録）
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $userId,
            $user['display_name'],
            null,
            'edit',
            $userId,
            ['email' => $user['email']],
            ['email' => $newEmail, 'action' => 'email_changed'],
            $this->request->ip()
        );

        $session = new \FuryoDacho\Core\Session();
        $session->setFlash('success', 'メールアドレスを変更しました。次回から新しいアドレスでログインしてください。');
        $this->response->redirect('/index.php?page=account');
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

        $data      = $this->request->all();
        $validator = new Validator($data, ['tenant_code' => 'テナントコード', 'email' => 'メールアドレス', 'password' => 'パスワード']);

        if (!$validator->validate([
            'tenant_code' => 'required|min:1|max:50',
            'email'       => 'required|email',
            'password'    => 'required|min:1',
        ])) {
            $this->render('auth/login', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => '入力内容を確認してください。',
                'errors'     => $validator->firstErrors(),
            ]);
            return;
        }

        $tenantCode = trim((string)$data['tenant_code']);
        $email      = trim((string)$data['email']);
        // htmlspecialchars によるサニタイズを避けるため $_POST から直接取得する
        // （配列が送られた場合は空文字として扱い、型エラーで500にしない）
        $password   = is_string($_POST['password'] ?? null) ? $_POST['password'] : '';

        $success = $this->auth->login($tenantCode, $email, $password);

        if (!$success) {
            $this->render('auth/login', [
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => 'テナントコード、メールアドレス、またはパスワードが正しくありません。',
            ]);
            return;
        }

        // パスワード変更強制チェック
        if ($this->auth->mustChangePassword()) {
            $this->response->redirect('/index.php?page=change_password');
            return;
        }

        $this->response->redirect('/index.php?page=dashboard');
    }

    /**
     * パスワードポリシー検証
     * 8文字以上・英字1文字以上・数字1文字以上
     */
    private function isValidPasswordPolicy(string $password): bool
    {
        if (mb_strlen($password) < 8) {
            return false;
        }
        if (!preg_match('/[A-Za-z]/', $password)) {
            return false;
        }
        if (!preg_match('/[0-9]/', $password)) {
            return false;
        }
        return true;
    }
}
