<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\Branch;
use FuryoDacho\Models\AuditLog;

/**
 * 拠点管理コントローラー（テナント管理者専用）
 */
class BranchController extends BaseController
{
    /**
     * 拠点一覧（管理者のみ）
     */
    public function index(): void
    {
        $this->auth->requireAdmin();

        $tenantId = $this->auth->getTenantId();
        $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);

        $this->render('branch/index', [
            'branches' => $branches,
        ]);
    }

    /**
     * 新規拠点登録フォーム（管理者のみ）
     */
    public function create(): void
    {
        $this->auth->requireAdmin();

        $this->render('branch/form', [
            'branch'     => null,
            'csrf_token' => $this->generateCsrfToken(),
            'errors'     => [],
            'isEdit'     => false,
        ]);
    }

    /**
     * 拠点登録処理（POST）
     * バリデーション・CSRF検証を行い、AuditLog に記録する。
     */
    public function store(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId  = $this->auth->getTenantId();
        $name      = $this->postString('name');
        $address   = $this->postString('address');
        $loginCode = $this->postString('login_code');

        $errors = $this->validateBranchInput($name, $address);
        $model  = new Branch($this->pdo);
        if ($loginCode !== '') {
            if (mb_strlen($loginCode) > 50) {
                $errors['login_code'] = '拠点ログインコードは50文字以内で入力してください。';
            } elseif (!preg_match('/^[A-Za-z0-9_-]+$/', $loginCode)) {
                $errors['login_code'] = '拠点ログインコードは半角英数字・ハイフン・アンダースコアのみ使用できます。';
            } elseif ($model->loginCodeExists($tenantId, $loginCode)) {
                $errors['login_code'] = 'この拠点ログインコードは既に使用されています。';
            }
        }

        if (!empty($errors)) {
            $this->render('branch/form', [
                'branch'     => null,
                'csrf_token' => $this->generateCsrfToken(),
                'errors'     => $errors,
                'input'      => ['name' => $name, 'address' => $address, 'login_code' => $loginCode],
                'isEdit'     => false,
            ]);
            return;
        }

        $id = $model->create($tenantId, $name, $address ?: null, $loginCode ?: null);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'create',
            $id,
            null,
            ['name' => $name, 'address' => $address],
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash('success', '拠点「' . $name . '」を登録しました。');
        $this->response->redirect('/index.php?page=branch');
    }

    /**
     * 拠点編集フォーム（管理者のみ）
     *
     * @param int $id
     */
    public function edit(int $id = 0): void
    {
        $this->auth->requireAdmin();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->get('id');
        $branch   = (new Branch($this->pdo))->findById($id, $tenantId);

        if ($branch === null) {
            $this->response->notFound('拠点が見つかりません。');
            return;
        }

        $this->render('branch/form', [
            'branch'     => $branch,
            'csrf_token' => $this->generateCsrfToken(),
            'errors'     => [],
            'isEdit'     => true,
        ]);
    }

    /**
     * 拠点更新処理（POST）
     *
     * @param int $id
     */
    public function update(int $id = 0): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId  = $this->auth->getTenantId();
        $id        = $id ?: (int)$this->request->post('id');
        $name      = $this->postString('name');
        $address   = $this->postString('address');
        $loginCode = $this->postString('login_code');

        $model  = new Branch($this->pdo);
        $before = $model->findById($id, $tenantId);

        if ($before === null) {
            $this->response->notFound('拠点が見つかりません。');
            return;
        }

        $errors = $this->validateBranchInput($name, $address);
        // 重複チェックはコードを変更する場合のみ行う。旧バージョンで登録された
        // テナント間の重複コードが残っていても、名称・住所の変更は保存できるようにする。
        $codeChanged = strcasecmp($loginCode, (string)($before['login_code'] ?? '')) !== 0;
        if ($loginCode !== '' && $codeChanged) {
            if (mb_strlen($loginCode) > 50) {
                $errors['login_code'] = '拠点ログインコードは50文字以内で入力してください。';
            } elseif (!preg_match('/^[A-Za-z0-9_-]+$/', $loginCode)) {
                $errors['login_code'] = '拠点ログインコードは半角英数字・ハイフン・アンダースコアのみ使用できます。';
            } elseif ($model->loginCodeExists($tenantId, $loginCode, $id)) {
                $errors['login_code'] = 'この拠点ログインコードは既に使用されています。';
            }
        }

        if (!empty($errors)) {
            $this->render('branch/form', [
                'branch'     => array_merge($before, ['login_code' => $loginCode]),
                'csrf_token' => $this->generateCsrfToken(),
                'errors'     => $errors,
                'input'      => ['name' => $name, 'address' => $address, 'login_code' => $loginCode],
                'isEdit'     => true,
            ]);
            return;
        }

        $model->update($id, $tenantId, $name, $address ?: null, $loginCode ?: null);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'edit',
            $id,
            ['name' => $before['name'], 'address' => $before['address']],
            ['name' => $name, 'address' => $address],
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash('success', '拠点「' . $name . '」を更新しました。');
        $this->response->redirect('/index.php?page=branch');
    }

    /**
     * 拠点削除処理（POST・管理者のみ）
     * 所属ユーザーまたは台帳レコードが存在する場合はエラーメッセージを表示する。
     *
     * @param int $id
     */
    public function delete(int $id = 0): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->post('id');

        $model  = new Branch($this->pdo);
        $branch = $model->findById($id, $tenantId);

        if ($branch === null) {
            $this->response->notFound('拠点が見つかりません。');
            return;
        }

        // 主拠点は削除不可（名称変更のみ可能）
        if (!empty($branch['is_main'])) {
            $session = new \FuryoDacho\Core\Session();
            $session->setFlash('error', '主拠点は削除できません。名称の変更のみ可能です。');
            $this->response->redirect('/index.php?page=branch');
            return;
        }

        try {
            $model->delete($id, $tenantId);
        } catch (\RuntimeException $e) {
            // 所属ユーザーまたは台帳が存在する場合はエラー表示して一覧に戻す
            // （以前は error_message を渡して一覧を再表示していたが、ビューが表示しておらず
            //   削除ボタンを押しても何も起きないように見えた）
            (new \FuryoDacho\Core\Session())->setFlash('error', $e->getMessage());
            $this->response->redirect('/index.php?page=branch');
            return;
        }

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'delete',
            $id,
            ['name' => $branch['name'], 'address' => $branch['address']],
            null,
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash('success', '拠点「' . $branch['name'] . '」を削除しました。');
        $this->response->redirect('/index.php?page=branch');
    }

    // ----------------------------------------------------------------
    // 内部ユーティリティ
    // ----------------------------------------------------------------

    /**
     * POST の文字列項目（配列等が送られた場合は空文字）
     */
    private function postString(string $key): string
    {
        $v = $this->request->post($key, '');
        return is_string($v) ? trim($v) : '';
    }

    /**
     * 拠点入力のバリデーション
     *
     * @param string $name
     * @param string $address
     * @return array エラーメッセージ（空配列なら正常）
     */
    private function validateBranchInput(string $name, string $address = ''): array
    {
        $errors = [];
        // 所在地は DB の列長（512文字）まで。超えると DB エラーで保存できないため入力段階で案内する
        if (mb_strlen($address) > 512) {
            $errors['address'] = '所在地は512文字以内で入力してください。';
        }

        if ($name === '') {
            $errors['name'] = '拠点名は必須です。';
        } elseif (mb_strlen($name) > 255) {
            $errors['name'] = '拠点名は255文字以内で入力してください。';
        }

        return $errors;
    }
}
