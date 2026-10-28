<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\User;
use FuryoDacho\Models\Branch;
use FuryoDacho\Models\AuditLog;

/**
 * ユーザー管理コントローラー（テナント管理者専用）
 */
class UserController extends BaseController
{
    /** パスワードの最小文字数（ログイン後の変更画面と同じ） */
    private const PASSWORD_MIN_LENGTH = 8;

    /**
     * ユーザー一覧（管理者のみ）
     */
    public function index(): void
    {
        $this->auth->requireAdmin();

        $tenantId = $this->auth->getTenantId();
        $users    = (new User($this->pdo))->getByTenant($tenantId);

        $this->render('user/index', [
            'users' => $users,
        ]);
    }

    /**
     * 新規ユーザー作成フォーム（管理者のみ）
     */
    public function create(): void
    {
        $this->auth->requireAdmin();

        $tenantId = $this->auth->getTenantId();
        $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);

        $this->render('user/form', [
            'user'       => null,
            'branches'   => $branches,
            'csrf_token' => $this->generateCsrfToken(),
            'errors'     => [],
            'isEdit'     => false,
        ]);
    }

    /**
     * ユーザー登録処理（POST）
     * 初期パスワードはフォームで管理者が入力した値を使い、must_change_password = 1 をセットする
     * （利用者は初回ログイン時に自分のパスワードへ変更する）。
     * 以前はフォームの入力を無視して公開されている初期パスワード（Admin7777）を設定していたため、
     * 管理者が伝えたパスワードでは新しいユーザーがログインできなかった。
     * 拠点プルダウンは Branch::findAllByTenant() から取得する。
     */
    public function store(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $input    = $this->request->all();

        $errors = $this->validateUserInput($input, null, $tenantId);

        // 初期パスワード（加工を避けるため $_POST から直接取得）
        $password = is_string($_POST['password'] ?? null) ? $_POST['password'] : '';
        $confirm  = is_string($_POST['password_confirm'] ?? null) ? $_POST['password_confirm'] : '';
        $pwError  = \FuryoDacho\Helpers\Validator::passwordPolicyError($password, self::PASSWORD_MIN_LENGTH);
        if ($pwError !== null) {
            $errors['password'] = $pwError;
        } elseif (!hash_equals($password, $confirm)) {
            $errors['password_confirm'] = 'パスワードと確認用パスワードが一致しません。';
        }

        if (!empty($errors)) {
            unset($input['password'], $input['password_confirm']);
            $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);
            $this->render('user/form', [
                'user'       => null,
                'branches'   => $branches,
                'csrf_token' => $this->generateCsrfToken(),
                'errors'     => $errors,
                'input'      => $input,
                'isEdit'     => false,
            ]);
            return;
        }

        $userModel = new User($this->pdo);
        $newId     = $userModel->create([
            'tenant_id'            => $tenantId,
            'branch_id'            => ($input['branch_id'] ?? '') !== '' ? (int)$input['branch_id'] : null,
            'display_name'         => $input['display_name'],
            'email'                => $input['email'],
            'password'             => $password,
            'role'                 => $input['role'] ?? 'user',
            'is_active'            => 1,
            'must_change_password' => 1,
        ]);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'create',
            $newId,
            null,
            [
                'display_name' => $input['display_name'],
                'email'        => $input['email'],
                'role'         => $input['role'] ?? 'user',
                'branch_id'    => ($input['branch_id'] ?? '') ?: null,
            ],
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash(
            'success',
            'ユーザー「' . $input['display_name'] . '」を登録しました。設定したパスワードを本人に伝えてください（初回ログイン時に本人のパスワードへの変更が求められます）。'
        );
        $this->response->redirect('/index.php?page=user');
    }

    /**
     * ユーザー編集フォーム（管理者のみ）
     *
     * @param int $id
     */
    public function edit(int $id = 0): void
    {
        $this->auth->requireAdmin();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->get('id');
        $user     = (new User($this->pdo))->findById($id, $tenantId);

        if ($user === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }

        $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);

        $this->render('user/form', [
            'user'       => $user,
            'branches'   => $branches,
            'csrf_token' => $this->generateCsrfToken(),
            'errors'     => [],
            'isEdit'     => true,
        ]);
    }

    /**
     * ユーザー更新処理（POST）
     * 表示名・拠点・権限を変更可。パスワードはここでは変更不可。
     *
     * @param int $id
     */
    public function update(int $id = 0): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->post('id');
        $input    = $this->request->all();

        $userModel = new User($this->pdo);
        $before    = $userModel->findById($id, $tenantId);

        if ($before === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }

        $errors = $this->validateUserInput($input, $id, $tenantId);

        $newRole = $input['role'] ?? 'user';
        // 編集フォームには有効/無効の項目が無いため、未送信なら現在の値を維持する。
        // （以前は未送信を「有効」とみなしており、無効化したユーザーを編集・保存すると
        //   黙って再有効化され、退職者が再びログインできる状態になっていた）
        $beforeActive = (int)$before['is_active'] === 1 ? 1 : 0;
        $newActive    = array_key_exists('is_active', $input)
            ? ((int)$input['is_active'] === 1 ? 1 : 0)
            : $beforeActive;
        $isOwner = !empty($before['is_owner']);
        $isSelf  = $id === $this->auth->getUserId();

        // オーナー・自分自身の「有効→無効」と「管理者からの降格」を禁止する。
        // 一覧画面の「無効化」「削除」には同じ保護があったが、編集処理には無く、
        // 編集フォームへ is_active=0 や role=user を直接POSTすると回避できた。
        // （既に無効の状態を維持するだけの編集は妨げない）
        if (($isOwner || $isSelf)
            && (($beforeActive === 1 && $newActive === 0)
                || ($before['role'] === 'admin' && $newRole !== 'admin'))) {
            $errors['role'] = $isOwner
                ? 'オーナーアカウントは無効化・権限の変更ができません。'
                : '自分自身を無効化・降格することはできません。';
        }

        // オーナーのメールアドレス（ログインID）はオーナー本人しか変更できない。
        // パスワード再設定の仕組みが無いため、他の管理者に変更されるとオーナーが
        // ログインできなくなる（本人は「アカウント設定」から現在のパスワード確認付きで変更可）。
        if ($isOwner && !$isSelf
            && strcasecmp(trim((string)($input['email'] ?? '')), (string)$before['email']) !== 0) {
            $errors['email'] = 'オーナーのメールアドレスは、オーナー本人が「アカウント設定」から変更してください。';
        }

        if (!empty($errors)) {
            $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);
            $this->render('user/form', [
                'user'       => $before,
                'branches'   => $branches,
                'csrf_token' => $this->generateCsrfToken(),
                'errors'     => $errors,
                'input'      => $input,
                'isEdit'     => true,
            ]);
            return;
        }

        $userModel->update($id, $tenantId, [
            'display_name' => $input['display_name'],
            'email'        => $input['email'],
            'role'         => $newRole,
            // 未送信なら null（DB側で現在の値を維持し、読み取り後の無効化を書き戻さない）
            'is_active'    => array_key_exists('is_active', $input) ? $newActive : null,
            'branch_id'    => ($input['branch_id'] ?? '') !== '' ? (int)$input['branch_id'] : null,
        ]);

        // 監査ログ（有効/無効は変更を送信した場合のみ記録する。未送信時はDBの値を変えないため、
        //   読み取り時点の値を記録すると直前の別操作による変更と食い違う記録になる）
        $auditBefore = [
            'display_name' => $before['display_name'],
            'email'        => $before['email'],
            'role'         => $before['role'],
            'branch_id'    => $before['branch_id'],
        ];
        $auditAfter = [
            'display_name' => $input['display_name'],
            'email'        => $input['email'],
            'role'         => $newRole,
            'branch_id'    => ($input['branch_id'] ?? '') ?: null,
        ];
        if (array_key_exists('is_active', $input)) {
            $auditBefore['is_active'] = $beforeActive;
            $auditAfter['is_active']  = $newActive;
        }
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'edit',
            $id,
            $auditBefore,
            $auditAfter,
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash('success', 'ユーザー「' . $input['display_name'] . '」の情報を更新しました。');
        $this->response->redirect('/index.php?page=user');
    }

    /**
     * ユーザー無効化（管理者のみ）
     * is_active = 0 にする。自分自身は無効化不可。
     *
     * @param int $id
     */
    public function deactivate(int $id = 0): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->post('id');

        // 自分自身の無効化は禁止
        // （以前は一覧を error_message 付きで再表示していたが、ビューが表示しておらず何も起きないように見えた）
        if ($id === $this->auth->getUserId()) {
            (new \FuryoDacho\Core\Session())->setFlash('error', '自分自身を無効化することはできません。');
            $this->response->redirect('/index.php?page=user');
            return;
        }

        $userModel = new User($this->pdo);
        $target    = $userModel->findById($id, $tenantId);

        if ($target === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }

        // オーナー（テナント作成時の初期管理者）は無効化不可
        if (!empty($target['is_owner'])) {
            $session = new \FuryoDacho\Core\Session();
            $session->setFlash('error', 'オーナーアカウントは無効化できません。');
            $this->response->redirect('/index.php?page=user');
            return;
        }

        $userModel->deactivate($id, $tenantId);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'edit',
            $id,
            ['is_active' => 1, 'display_name' => $target['display_name']],
            ['is_active' => 0],
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash('success', '「' . $target['display_name'] . '」を無効化しました（ログインできなくなります）。');
        $this->response->redirect('/index.php?page=user');
    }

    /**
     * ユーザー再有効化（管理者のみ）
     * 誤って無効化した利用者や復職者を元に戻す。
     * （編集保存による暗黙の再有効化を廃止したため、明示的な操作として用意する）
     *
     * @param int $id
     */
    public function activate(int $id = 0): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->post('id');

        $userModel = new User($this->pdo);
        $target    = $userModel->findById($id, $tenantId);

        if ($target === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }

        $session = new \FuryoDacho\Core\Session();
        if ((int)$target['is_active'] === 1) {
            $session->setFlash('success', 'このユーザーは既に有効です。');
            $this->response->redirect('/index.php?page=user');
            return;
        }

        $userModel->activate($id, $tenantId);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'edit',
            $id,
            ['is_active' => 0, 'display_name' => $target['display_name']],
            ['is_active' => 1],
            $this->request->ip()
        );

        $session->setFlash('success', '「' . $target['display_name'] . '」を有効にしました。');
        $this->response->redirect('/index.php?page=user');
    }

    /**
     * ユーザー削除（管理者のみ・オーナーは削除不可）
     *
     * 台帳の登録記録があるユーザーは、帳簿の登録者情報を保全するため
     * 削除できない（無効化を案内）。
     */
    public function delete(int $id = 0): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->post('id');
        $session  = new \FuryoDacho\Core\Session();

        // 自分自身の削除は禁止
        if ($id === $this->auth->getUserId()) {
            $session->setFlash('error', '自分自身を削除することはできません。');
            $this->response->redirect('/index.php?page=user');
            return;
        }

        $userModel = new User($this->pdo);
        $target    = $userModel->findById($id, $tenantId);

        if ($target === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }

        // オーナー（テナント作成時の初期管理者）は削除不可
        if (!empty($target['is_owner'])) {
            $session->setFlash('error', 'オーナーアカウントは削除できません。');
            $this->response->redirect('/index.php?page=user');
            return;
        }

        // 台帳の登録・更新記録がある場合は削除不可（法定帳簿の登録者情報を保全）
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) FROM `ledgers` WHERE `tenant_id` = ? AND (`registered_by` = ? OR `updated_by` = ?)"
        );
        $stmt->execute([$tenantId, $id, $id]);
        if ((int)$stmt->fetchColumn() > 0) {
            $session->setFlash('error', 'このユーザーには台帳の登録記録があるため削除できません。帳簿の登録者情報を保全するため、代わりに「無効化」を使用してください。');
            $this->response->redirect('/index.php?page=user');
            return;
        }

        // 承認記録の参照を解除してから削除
        $this->pdo->prepare("UPDATE `ledgers` SET `approved_by` = NULL WHERE `tenant_id` = ? AND `approved_by` = ?")
            ->execute([$tenantId, $id]);
        $this->pdo->prepare("UPDATE `alerts` SET `confirmed_by` = NULL WHERE `tenant_id` = ? AND `confirmed_by` = ?")
            ->execute([$tenantId, $id]);

        $stmt = $this->pdo->prepare("DELETE FROM `users` WHERE `id` = ? AND `tenant_id` = ?");
        $stmt->execute([$id, $tenantId]);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'delete',
            $id,
            ['display_name' => $target['display_name'], 'email' => $target['email'], 'kind' => 'user'],
            null,
            $this->request->ip()
        );

        $session->setFlash('success', 'ユーザー「' . $target['display_name'] . '」を削除しました。');
        $this->response->redirect('/index.php?page=user');
    }

    /**
     * パスワードの再設定（管理者のみ）
     * 利用者がパスワードを忘れた・ロックされた場合に、管理者が仮パスワードを設定する。
     * 仮パスワードでログインすると、本人のパスワードへの変更が求められる。ロックも解除する。
     * 以前はパスワードを再設定する手段が無く、DBを直接操作するしかなかった。
     *
     * オーナーのパスワードは他の管理者からは再設定できない（乗っ取り防止。システム管理者が再設定する）。
     * 自分自身は「パスワード変更」画面で変更する。
     */
    public function resetPassword(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = (int)$this->request->post('id');
        $session  = new \FuryoDacho\Core\Session();
        $back     = '/index.php?page=user.edit&id=' . $id;

        $userModel = new User($this->pdo);
        $target    = $userModel->findById($id, $tenantId);
        if ($target === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }
        if ($id === $this->auth->getUserId()) {
            $session->setFlash('error', '自分のパスワードは「パスワード変更」画面で変更してください。');
            $this->response->redirect($back);
            return;
        }
        if (!empty($target['is_owner'])) {
            $session->setFlash('error', 'オーナーのパスワードは他の管理者からは再設定できません。オーナー本人が変更するか、システム管理者に再設定を依頼してください。');
            $this->response->redirect($back);
            return;
        }

        $password = is_string($_POST['new_password'] ?? null) ? $_POST['new_password'] : '';
        $confirm  = is_string($_POST['new_password_confirm'] ?? null) ? $_POST['new_password_confirm'] : '';
        $pwError  = \FuryoDacho\Helpers\Validator::passwordPolicyError($password, self::PASSWORD_MIN_LENGTH);
        if ($pwError === null && !hash_equals($password, $confirm)) {
            $pwError = '新しいパスワードと確認用パスワードが一致しません。';
        }
        if ($pwError !== null) {
            $session->setFlash('error', 'パスワードを再設定できませんでした: ' . $pwError);
            $this->response->redirect($back);
            return;
        }

        $userModel->resetPassword($id, $tenantId, $password);
        (new \FuryoDacho\Helpers\LoginThrottle($this->pdo))
            ->clearFailures(\FuryoDacho\Helpers\LoginThrottle::accountKey('tenant', 'uid:' . $id));

        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'edit',
            $id,
            ['display_name' => $target['display_name']],
            ['action' => 'password_reset_by_admin', 'unlocked' => true],
            $this->request->ip()
        );

        $session->setFlash('success', '「' . $target['display_name'] . '」のパスワードを再設定しました（ロックも解除しました）。設定したパスワードを本人に伝えてください。次回ログイン時に本人のパスワードへの変更が求められます。');
        $this->response->redirect('/index.php?page=user');
    }

    /**
     * アカウントロックの解除（管理者のみ）
     * ログインに5回失敗してロックされた利用者を、30分待たずにログインできるようにする。
     */
    public function unlock(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = (int)$this->request->post('id');
        $session  = new \FuryoDacho\Core\Session();

        $userModel = new User($this->pdo);
        $target    = $userModel->findById($id, $tenantId);
        if ($target === null) {
            $this->response->notFound('ユーザーが見つかりません。');
            return;
        }

        $userModel->unlock($id, $tenantId);
        (new \FuryoDacho\Helpers\LoginThrottle($this->pdo))
            ->clearFailures(\FuryoDacho\Helpers\LoginThrottle::accountKey('tenant', 'uid:' . $id));

        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'edit',
            $id,
            ['display_name' => $target['display_name'], 'locked_until' => $target['locked_until']],
            ['action' => 'account_unlocked'],
            $this->request->ip()
        );

        $session->setFlash('success', '「' . $target['display_name'] . '」のログインロックを解除しました。');
        $this->response->redirect('/index.php?page=user');
    }

    // ----------------------------------------------------------------
    // 内部ユーティリティ
    // ----------------------------------------------------------------

    /**
     * ユーザー入力バリデーション
     *
     * @param array    $input
     * @param int|null $excludeId  編集時は重複チェックで自分を除外
     * @param int      $tenantId
     * @return array エラーメッセージ
     */
    private function validateUserInput(array $input, ?int $excludeId, int $tenantId): array
    {
        $errors = [];

        foreach (['display_name', 'email', 'role', 'branch_id'] as $k) {
            if (isset($input[$k]) && !is_string($input[$k])) {
                $input[$k] = '';
                $errors[$k] = '入力値の形式が不正です。';
            }
        }

        if (empty($input['display_name'])) {
            $errors['display_name'] = '表示名は必須です。';
        } elseif (mb_strlen($input['display_name']) > 255) {
            $errors['display_name'] = '表示名は255文字以内で入力してください。';
        }

        if (empty($input['email'])) {
            $errors['email'] = 'メールアドレスは必須です。';
        } elseif (mb_strlen($input['email']) > 255) {
            $errors['email'] = 'メールアドレスは255文字以内で入力してください。';
        } elseif (!filter_var($input['email'], FILTER_VALIDATE_EMAIL)) {
            $errors['email'] = '正しいメールアドレス形式で入力してください。';
        } else {
            // テナント内メールアドレス重複チェック
            $pdo  = $this->pdo;
            $sql  = "SELECT `id` FROM `users` WHERE `tenant_id` = ? AND `email` = ?";
            $args = [$tenantId, $input['email']];
            if ($excludeId !== null) {
                $sql  .= " AND `id` != ?";
                $args[] = $excludeId;
            }
            $stmt = $pdo->prepare($sql);
            $stmt->execute($args);
            if ($stmt->fetch()) {
                $errors['email'] = 'このメールアドレスはすでに使用されています。';
            }
        }

        if (!in_array($input['role'] ?? '', ['admin', 'user'], true)) {
            $errors['role'] = '権限の値が無効です。';
        }

        // 所属拠点は自テナントの拠点のみ（他テナントの拠点IDの指定を防ぐ）
        $branchId = $input['branch_id'] ?? '';
        if ($branchId !== '' && $branchId !== null) {
            if (!ctype_digit((string)$branchId)
                || (new Branch($this->pdo))->findById((int)$branchId, $tenantId) === null) {
                $errors['branch_id'] = '所属拠点の値が無効です。';
            }
        }

        return $errors;
    }
}
