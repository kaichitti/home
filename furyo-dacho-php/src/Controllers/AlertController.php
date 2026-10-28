<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\Alert;
use FuryoDacho\Models\AuditLog;

/**
 * 重複検知アラートコントローラー（管理者専用）
 */
class AlertController extends BaseController
{
    /**
     * アラート一覧表示
     */
    public function index(): void
    {
        $this->auth->requireAdmin();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();
        $status   = $this->request->get('status');
        $status   = (is_string($status) && in_array($status, ['unconfirmed', 'confirmed'], true)) ? $status : null;

        $perPage = 50;
        $page    = max(1, (int)$this->request->get('p', 1));

        $alertModel = new Alert($this->pdo);
        $total      = $alertModel->countAll($tenantId, $status);
        $totalPages = max(1, (int)ceil($total / $perPage));
        $page       = min($page, $totalPages);
        $offset     = ($page - 1) * $perPage;

        $alerts = $alertModel->findAll($tenantId, $status, $perPage, $offset);

        $csrf_token = $this->generateCsrfToken();
        $isAdmin    = true;

        $pagination = [
            'current_page' => $page,
            'total_pages'  => $totalPages,
            'total'        => $total,
        ];

        $this->render('alert/index', compact('alerts', 'status', 'csrf_token', 'isAdmin', 'pagination'));
    }

    /**
     * アラート確認処理（POST のみ受け付け）
     */
    public function confirm(): void
    {
        $this->auth->requireAdmin();

        if (!$this->request->isPost()) {
            $this->response->redirect('/index.php?page=alert');
            return;
        }

        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();
        $id       = (int)$this->request->get('id');

        if ($id <= 0) {
            $this->response->redirect('/index.php?page=alert');
            return;
        }

        $alertModel = new Alert($this->pdo);
        $success    = $alertModel->confirm($id, $tenantId, $userId);

        if ($success) {
            // 監査ログ記録
            (new AuditLog($this->pdo))->log(
                $tenantId,
                $userId,
                $this->auth->user()['display_name'],
                null,
                'alert_action',
                $id,
                null,
                ['status' => 'confirmed'],
                $this->request->ip()
            );

            $_SESSION['_flash_success'] = 'アラートを確認済みにしました。';
        } else {
            $_SESSION['_flash_error'] = 'アラートの確認処理に失敗しました（既に確認済みか、見つかりません）。';
        }

        $this->response->redirect('/index.php?page=alert');
    }
}
