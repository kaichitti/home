<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\AuditLog;

/**
 * 監査ログコントローラー（テナント管理者専用）
 */
class AuditController extends BaseController
{
    /**
     * 監査ログ一覧（ページネーション付き、1ページ50件）
     */
    public function index(): void
    {
        $this->auth->requireAdmin();

        $tenantId = $this->auth->getTenantId();
        $perPage  = 50;
        $page     = max(1, (int)$this->request->get('p', 1));

        $filters = [
            'action_type' => $this->request->get('action_type') ?: null,
            'user_id'     => $this->request->get('user_id')     ?: null,
            'date_from'   => $this->request->get('date_from')   ?: null,
            'date_to'     => $this->request->get('date_to')     ?: null,
        ];

        $auditModel = new AuditLog($this->pdo);

        // 総件数を取得（ページネーション計算用）
        $total      = $this->countLogs($tenantId, $filters);
        $totalPages = (int)ceil($total / $perPage);
        $offset     = ($page - 1) * $perPage;

        $logs = $auditModel->getByTenant($tenantId, $filters, $perPage, $page);

        $pagination = [
            'current_page' => $page,
            'total_pages'  => $totalPages,
            'total'        => $total,
            'per_page'     => $perPage,
        ];

        $this->render('audit/index', compact('logs', 'filters', 'page', 'perPage', 'pagination'));
    }

    /**
     * 監査ログの総件数を取得（フィルタ付き）
     *
     * @param int   $tenantId
     * @param array $filters
     * @return int
     */
    private function countLogs(int $tenantId, array $filters): int
    {
        $where  = ['tenant_id = ?'];
        $params = [$tenantId];

        if (!empty($filters['action_type'])) {
            $where[]  = 'action_type = ?';
            $params[] = $filters['action_type'];
        }
        if (!empty($filters['user_id'])) {
            $where[]  = 'user_id = ?';
            $params[] = (int)$filters['user_id'];
        }
        if (!empty($filters['date_from'])) {
            $where[]  = 'created_at >= ?';
            $params[] = $filters['date_from'] . ' 00:00:00';
        }
        if (!empty($filters['date_to'])) {
            $where[]  = 'created_at <= ?';
            $params[] = $filters['date_to'] . ' 23:59:59';
        }

        $whereClause = implode(' AND ', $where);
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) FROM `audit_logs` WHERE {$whereClause}"
        );
        $stmt->execute($params);
        return (int)$stmt->fetchColumn();
    }
}
