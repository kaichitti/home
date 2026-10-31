<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\ItemCategory;
use FuryoDacho\Models\AuditLog;
use FuryoDacho\Core\Session;

/**
 * 古物区分管理コントローラー（テナント管理者専用）
 * 法定13区分に加えてテナント独自の区分を追加・削除できる。
 */
class CategoryController extends BaseController
{
    /**
     * 区分一覧 + 追加フォーム
     */
    public function index(): void
    {
        $this->auth->requireAdmin();

        $tenantId   = $this->auth->getTenantId();
        $model      = new ItemCategory($this->pdo);
        $categories = $model->findAllByTenant($tenantId);
        $statutory  = ItemCategory::STATUTORY;

        $this->render('category/index', compact('categories', 'statutory'));
    }

    /**
     * 区分追加（POST）
     */
    public function store(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        // 配列が送られた場合は空欄として扱う（以前は区分名「Array」が登録されていた）
        $name     = $this->request->post('name', '');
        $name     = is_string($name) ? trim($name) : '';
        $session  = new Session();

        try {
            $model = new ItemCategory($this->pdo);
            $newId = $model->create($tenantId, $name);

            // 監査ログ
            (new AuditLog($this->pdo))->log(
                $tenantId,
                $this->auth->getUserId(),
                $this->auth->user()['display_name'],
                null,
                'create',
                $newId,
                null,
                ['item_category_name' => $name],
                $this->request->ip()
            );

            $session->setFlash('success', '古物区分「' . $name . '」を追加しました。');
        } catch (\RuntimeException $e) {
            $session->setFlash('error', $e->getMessage());
        }

        $this->response->redirect('/index.php?page=category');
    }

    /**
     * 区分削除（POST）
     * 過去の台帳レコードには区分名がそのまま保存されているため、
     * 削除しても既存データには影響しない。
     */
    public function delete(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = (int)$this->request->post('id');
        $session  = new Session();

        $model  = new ItemCategory($this->pdo);
        $target = $model->findById($id, $tenantId);

        if ($target === null) {
            $session->setFlash('error', '区分が見つかりません。');
            $this->response->redirect('/index.php?page=category');
            return;
        }

        $model->delete($id, $tenantId);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'delete',
            $id,
            ['item_category_name' => $target['name']],
            null,
            $this->request->ip()
        );

        $session->setFlash('success', '古物区分「' . $target['name'] . '」を削除しました。（登録済みの台帳の表記は変わりません）');
        $this->response->redirect('/index.php?page=category');
    }
}
