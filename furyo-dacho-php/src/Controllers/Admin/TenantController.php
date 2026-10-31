<?php

namespace FuryoDacho\Controllers\Admin;

use FuryoDacho\Controllers\BaseController;
use FuryoDacho\Core\Session;
use FuryoDacho\Helpers\LoginThrottle;
use FuryoDacho\Helpers\Validator;
use FuryoDacho\Models\AuditLog;
use FuryoDacho\Models\Tenant;
use FuryoDacho\Models\User;

/**
 * テナント管理コントローラー（システム管理者専用）
 * テナントのCRUD・停止・再開・削除と、テナント利用者のパスワード再設定・ロック解除を担当する。
 * テナント作成時は主拠点と初期管理者（オーナー）を自動生成する。
 */
class TenantController extends BaseController
{
    /** テナント利用者のパスワードの最小文字数（ログイン後の変更画面と同じ） */
    private const USER_PASSWORD_MIN_LENGTH = 8;

    /** 入力エラーの表示に使う項目名 */
    private const FIELD_LABELS = [
        'code'        => 'テナントコード',
        'name'        => 'テナント名',
        'type'        => '種別',
        'status'      => '状態',
        'admin_email' => 'メールアドレス',
        'admin_name'  => '表示名',
    ];

    /**
     * 管理者ダッシュボード
     */
    public function dashboard(): void
    {
        $this->auth->requireAdminAuth();

        $tenants    = (new Tenant($this->pdo))->findAllWithStats();
        $totalCount = count($tenants);

        $this->render('admin/dashboard', compact('tenants', 'totalCount'), 'admin');
    }

    /**
     * テナント一覧（?deleted=1 で削除済みも表示）
     */
    public function index(): void
    {
        $this->auth->requireAdminAuth();

        $showDeleted = $this->request->get('deleted') === '1';
        $tenants     = (new Tenant($this->pdo))->findAllWithStats($showDeleted);

        $this->render('admin/tenant/index', compact('tenants', 'showDeleted'), 'admin');
    }

    /**
     * 新規テナント作成フォーム表示
     */
    public function create(): void
    {
        $this->auth->requireAdminAuth();

        $this->render('admin/tenant/form', [
            'tenant'     => null,
            'csrf_token' => $this->generateCsrfToken(),
            'error'      => null,
            'errors'     => [],
        ], 'admin');
    }

    /**
     * テナント作成処理
     * コード重複チェック後、テナントを作成し主拠点と初期管理者ユーザー（オーナー）を自動生成する。
     */
    public function store(): void
    {
        $this->auth->requireAdminAuth();
        $this->verifyCsrf();

        $data      = $this->request->all();
        $validator = new Validator($data, self::FIELD_LABELS);

        $renderForm = function (string $error, array $errors) use ($data): void {
            unset($data['admin_password'], $data['admin_password_confirm']);
            $this->render('admin/tenant/form', [
                'tenant'     => null,
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => $error,
                'errors'     => $errors,
                'old'        => $data,
            ], 'admin');
        };

        $valid  = $validator->validate([
            'code'        => 'required|min:1|max:50|regex:/^[a-z0-9_\-]+$/i',
            'name'        => 'required|min:1|max:255',
            'type'        => 'required|in:own,client',
            'admin_email' => 'required|email|max:255',
            'admin_name'  => 'required|min:1|max:255',
        ]);
        $errors = $validator->firstErrors();

        // 初期パスワード（加工を避けるため $_POST から直接取得）。
        // 以前は8文字以上のみの確認で、英字・数字の条件や公開されている初期パスワードの禁止が無かった
        $password = is_string($_POST['admin_password'] ?? null) ? $_POST['admin_password'] : '';
        $confirm  = is_string($_POST['admin_password_confirm'] ?? null) ? $_POST['admin_password_confirm'] : null;
        $pwError  = Validator::passwordPolicyError($password, self::USER_PASSWORD_MIN_LENGTH);
        if ($pwError !== null) {
            $errors['admin_password'] = $pwError;
        } elseif ($confirm !== null && !hash_equals($password, $confirm)) {
            $errors['admin_password_confirm'] = 'パスワードと確認用パスワードが一致しません。';
        }

        if (!$valid || !empty($errors)) {
            $renderForm('入力内容を確認してください。', $errors);
            return;
        }

        $tenantModel = new Tenant($this->pdo);
        $code        = trim((string)$data['code']);

        // コード重複チェック（他テナントのコード、および各テナントの拠点ログインコードと
        // 衝突しないこと。ログイン時はテナントコードが優先されるため、拠点ログインコードと
        // 同じ値だと、その拠点のユーザーが別テナントへ誘導されてしまう）
        if ($tenantModel->isCodeTaken($code) || $this->branchLoginCodeExists($code)) {
            $renderForm('このテナントコードはすでに使用されています。', [
                'code' => 'このテナントコードはすでに使用されています（拠点ログインコードを含む）。',
            ]);
            return;
        }

        try {
            $this->pdo->beginTransaction();

            $tenantId = $tenantModel->create([
                'code'   => $code,
                'name'   => trim((string)$data['name']),
                'type'   => $data['type'],
                'status' => 'active',
            ]);

            // デフォルト拠点（主拠点）を自動生成
            // （拠点ゼロのテナントは台帳登録が拠点必須チェックで一切できないため）
            $this->pdo->prepare(
                "INSERT INTO `branches` (`tenant_id`, `name`, `is_main`) VALUES (?, '本社', 1)"
            )->execute([$tenantId]);
            $branchId = (int)$this->pdo->lastInsertId();

            // 初期管理者ユーザー（オーナー）を自動生成
            $ownerId = (new User($this->pdo))->create([
                'tenant_id'            => $tenantId,
                'branch_id'            => $branchId,
                'display_name'         => trim((string)$data['admin_name']),
                'email'                => trim((string)$data['admin_email']),
                'password'             => $password,
                'role'                 => 'admin',
                'is_active'            => 1,
                'must_change_password' => 1,
            ]);
            // 初期管理者をオーナーにする（削除・無効化・降格不可）
            $this->pdo->prepare("UPDATE `users` SET `is_owner` = 1 WHERE `id` = ? AND `tenant_id` = ?")
                ->execute([$ownerId, $tenantId]);

            $this->pdo->commit();
        } catch (\Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            error_log('[furyo-dacho] tenant create failed: ' . $e->getMessage());
            $renderForm('テナントの作成中にエラーが発生しました。入力内容を確認して、もう一度お試しください。', []);
            return;
        }

        $this->adminAudit('create', $tenantId, null, [
            'kind' => 'tenant', 'code' => $code, 'name' => trim((string)$data['name']),
            'owner_email' => trim((string)$data['admin_email']),
        ]);

        (new Session())->setFlash(
            'success',
            'テナント「' . trim((string)$data['name']) . '」を作成しました。テナントコード「' . $code
            . '」・管理者のメールアドレス・設定した初期パスワードを先方に伝えてください（初回ログイン時にパスワードの変更が求められます）。'
        );
        $this->response->redirect('/admin/index.php?page=tenant.show&id=' . $tenantId);
    }

    /**
     * テナント詳細（利用者一覧・パスワード再設定・ロック解除）
     */
    public function show(): void
    {
        $this->auth->requireAdminAuth();

        $id     = (int)$this->request->get('id');
        $tenant = (new Tenant($this->pdo))->findById($id);

        if ($tenant === null) {
            $this->response->notFound('テナントが見つかりません。');
            return;
        }

        $users = (new User($this->pdo))->getByTenant($id);

        $stats = ['ledger_count' => 0, 'branch_count' => 0, 'member_count' => 0];
        foreach ([
            'ledger_count' => "SELECT COUNT(*) FROM `ledgers` WHERE `tenant_id` = ? AND `deleted_at` IS NULL",
            'branch_count' => "SELECT COUNT(*) FROM `branches` WHERE `tenant_id` = ?",
            'member_count' => "SELECT COUNT(*) FROM `members` WHERE `tenant_id` = ?",
        ] as $key => $sql) {
            try {
                $stmt = $this->pdo->prepare($sql);
                $stmt->execute([$id]);
                $stats[$key] = (int)$stmt->fetchColumn();
            } catch (\Throwable $e) {
                $stats[$key] = 0;
            }
        }

        $this->render('admin/tenant/show', [
            'tenant'     => $tenant,
            'users'      => $users,
            'stats'      => $stats,
            'csrf_token' => $this->generateCsrfToken(),
        ], 'admin');
    }

    /**
     * テナント編集フォーム表示
     */
    public function edit(): void
    {
        $this->auth->requireAdminAuth();

        $id     = (int)$this->request->get('id');
        $tenant = (new Tenant($this->pdo))->findById($id);

        if ($tenant === null) {
            $this->response->notFound('テナントが見つかりません。');
            return;
        }
        if ($tenant['status'] === 'deleted') {
            (new Session())->setFlash('error', '削除済みのテナントは編集できません。');
            $this->response->redirect('/admin/index.php?page=tenant.show&id=' . $id);
            return;
        }

        $this->render('admin/tenant/form', [
            'tenant'     => $tenant,
            'csrf_token' => $this->generateCsrfToken(),
            'error'      => null,
            'errors'     => [],
        ], 'admin');
    }

    /**
     * テナント更新処理
     */
    public function update(): void
    {
        $this->auth->requireAdminAuth();
        $this->verifyCsrf();

        $id   = (int)$this->request->post('id');
        $data = $this->request->all();

        $tenantModel = new Tenant($this->pdo);
        $tenant      = $tenantModel->findById($id);

        if ($tenant === null) {
            $this->response->notFound('テナントが見つかりません。');
            return;
        }
        // 削除済みテナントは利用者が全員無効化されているため、編集（状態の変更）で
        // 中途半端に「有効」へ戻さない
        if ($tenant['status'] === 'deleted') {
            (new Session())->setFlash('error', '削除済みのテナントは編集できません。');
            $this->response->redirect('/admin/index.php?page=tenant.show&id=' . $id);
            return;
        }

        $validator = new Validator($data, self::FIELD_LABELS);
        if (!$validator->validate([
            'code'   => 'required|min:1|max:50|regex:/^[a-z0-9_\-]+$/i',
            'name'   => 'required|min:1|max:255',
            'type'   => 'required|in:own,client',
            'status' => 'required|in:active,suspended',
        ])) {
            $this->render('admin/tenant/form', [
                'tenant'     => $tenant,
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => '入力内容を確認してください。',
                'errors'     => $validator->firstErrors(),
                'old'        => $data,
            ], 'admin');
            return;
        }

        // コード重複チェック（自分自身を除外）。拠点ログインコードとの衝突確認は
        // コードを変更する場合のみ行う（旧バージョンのデータで既存コードが拠点コードと
        // 重なっていても、停止中テナントの再開や名称変更はできるようにするため）
        $newCode     = trim((string)$data['code']);
        $codeChanged = strcasecmp($newCode, (string)$tenant['code']) !== 0;
        if ($tenantModel->isCodeTaken($newCode, $id)
            || ($codeChanged && $this->branchLoginCodeExists($newCode))) {
            $this->render('admin/tenant/form', [
                'tenant'     => $tenant,
                'csrf_token' => $this->generateCsrfToken(),
                'error'      => 'このテナントコードはすでに使用されています。',
                'errors'     => ['code' => 'このテナントコードはすでに使用されています（拠点ログインコードを含む）。'],
                'old'        => $data,
            ], 'admin');
            return;
        }

        $after = [
            'code'   => $newCode,
            'name'   => trim((string)$data['name']),
            'type'   => $data['type'],
            'status' => $data['status'],
        ];
        $tenantModel->update($id, $after);

        $this->adminAudit('edit', $id,
            ['kind' => 'tenant', 'code' => $tenant['code'], 'name' => $tenant['name'], 'type' => $tenant['type'], 'status' => $tenant['status']],
            ['kind' => 'tenant'] + $after
        );

        $msg = 'テナント「' . $after['name'] . '」を更新しました。';
        if ($codeChanged) {
            $msg .= 'テナントコードを変更したため、利用者には新しいコード「' . $newCode . '」でログインするよう伝えてください。';
        }
        (new Session())->setFlash('success', $msg);
        $this->response->redirect('/admin/index.php?page=tenant.show&id=' . $id);
    }

    /**
     * テナント停止処理（利用者はログインできなくなる。データは保持）
     */
    public function suspend(): void
    {
        $this->auth->requireAdminAuth();
        $this->verifyCsrf();

        $id          = (int)$this->request->post('id');
        $tenantModel = new Tenant($this->pdo);
        $tenant      = $tenantModel->findById($id);

        if ($tenant === null) {
            $this->response->notFound('テナントが見つかりません。');
            return;
        }
        if ($tenant['status'] !== 'active') {
            (new Session())->setFlash('error', 'このテナントは有効ではないため停止できません。');
            $this->response->redirect($this->backUrl($id));
            return;
        }

        $tenantModel->suspend($id);
        $this->adminAudit('edit', $id, ['kind' => 'tenant', 'status' => 'active'], ['kind' => 'tenant', 'status' => 'suspended', 'action' => 'tenant_suspended']);

        (new Session())->setFlash('success', 'テナント「' . $tenant['name'] . '」を停止しました（利用者はログインできなくなります。データは保持されます）。');
        $this->response->redirect($this->backUrl($id));
    }

    /**
     * 停止中のテナントを再開する
     * （以前は一覧に「再開」が無く、編集画面で状態を変える必要があった）
     */
    public function resume(): void
    {
        $this->auth->requireAdminAuth();
        $this->verifyCsrf();

        $id          = (int)$this->request->post('id');
        $tenantModel = new Tenant($this->pdo);
        $tenant      = $tenantModel->findById($id);

        if ($tenant === null) {
            $this->response->notFound('テナントが見つかりません。');
            return;
        }
        if (!$tenantModel->resume($id)) {
            (new Session())->setFlash('error', '停止中のテナントのみ再開できます。');
            $this->response->redirect($this->backUrl($id));
            return;
        }

        $this->adminAudit('edit', $id, ['kind' => 'tenant', 'status' => 'suspended'], ['kind' => 'tenant', 'status' => 'active', 'action' => 'tenant_resumed']);

        (new Session())->setFlash('success', 'テナント「' . $tenant['name'] . '」を再開しました。');
        $this->response->redirect($this->backUrl($id));
    }

    /**
     * テナント削除処理（論理削除・全ユーザー無効化）
     */
    public function delete(): void
    {
        $this->auth->requireAdminAuth();
        $this->verifyCsrf();

        $id          = (int)$this->request->post('id');
        $tenantModel = new Tenant($this->pdo);
        $tenant      = $tenantModel->findById($id);

        if ($tenant === null) {
            $this->response->notFound('テナントが見つかりません。');
            return;
        }

        // 誤操作防止: 確認欄にテナントコードを入力した場合のみ削除する
        $confirmCode = $this->request->post('confirm_code', '');
        if (!is_string($confirmCode) || $confirmCode !== (string)$tenant['code']) {
            (new Session())->setFlash('error', '削除するには、確認欄にテナントコード「' . $tenant['code'] . '」を正確に入力してください。');
            $this->response->redirect('/admin/index.php?page=tenant.show&id=' . $id);
            return;
        }

        try {
            $this->pdo->beginTransaction();
            (new User($this->pdo))->deactivateAllByTenant($id);
            $tenantModel->delete($id);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            error_log('[furyo-dacho] tenant delete failed: ' . $e->getMessage());
            // 以前は失敗しても何も表示せず一覧へ戻っていた
            (new Session())->setFlash('error', 'テナントの削除に失敗しました。もう一度お試しください。');
            $this->response->redirect('/admin/index.php?page=tenant.show&id=' . $id);
            return;
        }

        $this->adminAudit('delete', $id, ['kind' => 'tenant', 'code' => $tenant['code'], 'name' => $tenant['name'], 'status' => $tenant['status']], null);

        (new Session())->setFlash('success', 'テナント「' . $tenant['name'] . '」を削除しました（全利用者を無効化しました。台帳データはDBに保持されています）。');
        $this->response->redirect('/admin/index.php?page=tenant');
    }

    /**
     * テナント利用者のパスワード再設定（ロック解除を含む）
     * オーナーがパスワードを忘れた場合など、テナント内では解決できないときに使う。
     * 以前はシステム管理者にもパスワードを再設定する手段が無く、DBを直接操作するしかなかった。
     */
    public function userPassword(): void
    {
        $this->auth->requireAdminAuth();
        $this->verifyCsrf();

        $tenantId = (int)$this->request->post('tenant_id');
        $userId   = (int)$this->request->post('user_id');
        $back     = '/admin/index.php?page=tenant.show&id=' . $tenantId;
        $session  = new Session();

        $userModel = new User($this->pdo);
        $target    = $userModel->findById($userId, $tenantId);
        if ($target === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }

        $password = is_string($_POST['new_password'] ?? null) ? $_POST['new_password'] : '';
        $confirm  = is_string($_POST['new_password_confirm'] ?? null) ? $_POST['new_password_confirm'] : '';
        $pwError  = Validator::passwordPolicyError($password, self::USER_PASSWORD_MIN_LENGTH);
        if ($pwError === null && !hash_equals($password, $confirm)) {
            $pwError = '新しいパスワードと確認用パスワードが一致しません。';
        }
        if ($pwError !== null) {
            $session->setFlash('error', '「' . $target['display_name'] . '」のパスワードを再設定できませんでした: ' . $pwError);
            $this->response->redirect($back);
            return;
        }

        $userModel->resetPassword($userId, $tenantId, $password);
        (new LoginThrottle($this->pdo))->clearFailures(LoginThrottle::accountKey('tenant', 'uid:' . $userId));

        $this->adminAudit('edit', $userId, ['kind' => 'user', 'display_name' => $target['display_name']],
            ['action' => 'password_reset_by_system_admin', 'unlocked' => true], $tenantId);

        $session->setFlash('success', '「' . $target['display_name'] . '」のパスワードを再設定しました（ロックも解除しました）。設定したパスワードを本人に伝えてください。次回ログイン時に本人のパスワードへの変更が求められます。');
        $this->response->redirect($back);
    }

    /**
     * テナント利用者のログインロック解除
     */
    public function userUnlock(): void
    {
        $this->auth->requireAdminAuth();
        $this->verifyCsrf();

        $tenantId = (int)$this->request->post('tenant_id');
        $userId   = (int)$this->request->post('user_id');

        $userModel = new User($this->pdo);
        $target    = $userModel->findById($userId, $tenantId);
        if ($target === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }

        $userModel->unlock($userId, $tenantId);
        (new LoginThrottle($this->pdo))->clearFailures(LoginThrottle::accountKey('tenant', 'uid:' . $userId));
        $this->adminAudit('edit', $userId, ['kind' => 'user', 'display_name' => $target['display_name']], ['action' => 'account_unlocked_by_system_admin'], $tenantId);

        (new Session())->setFlash('success', '「' . $target['display_name'] . '」のログインロックを解除しました。');
        $this->response->redirect('/admin/index.php?page=tenant.show&id=' . $tenantId);
    }

    // ----------------------------------------------------------------
    // 内部ユーティリティ
    // ----------------------------------------------------------------

    /**
     * 操作後の戻り先（詳細画面から操作した場合は詳細へ、それ以外は一覧へ）
     */
    private function backUrl(int $tenantId): string
    {
        return $this->request->post('back') === 'show'
            ? '/admin/index.php?page=tenant.show&id=' . $tenantId
            : '/admin/index.php?page=tenant';
    }

    /**
     * システム管理者の操作を監査ログに記録する
     * （以前はテナントの作成・変更・停止・削除が記録されていなかった）
     *
     * @param int|null $tenantId 対象テナント（利用者の操作では、その利用者のテナント。テナント操作では NULL）
     */
    private function adminAudit(string $action, ?int $targetId, ?array $before, ?array $after, ?int $tenantId = null): void
    {
        try {
            $admin = $this->auth->adminUser();
            (new AuditLog($this->pdo))->log(
                $tenantId,
                null,
                '[システム管理者] ' . (string)($admin['username'] ?? 'system_admin'),
                null,
                $action,
                $targetId,
                $before,
                $after,
                $this->request->ip()
            );
        } catch (\Throwable $e) {
            error_log('[furyo-dacho] admin audit log failed: ' . $e->getMessage());
        }
    }

    /**
     * いずれかのテナントの拠点ログインコードとして使用されているか
     * （login_code 列が未追加の環境では常に false）
     */
    private function branchLoginCodeExists(string $code): bool
    {
        try {
            $stmt = $this->pdo->prepare("SELECT COUNT(*) FROM `branches` WHERE `login_code` = ?");
            $stmt->execute([$code]);
            return (int)$stmt->fetchColumn() > 0;
        } catch (\PDOException $e) {
            return false;
        }
    }
}
