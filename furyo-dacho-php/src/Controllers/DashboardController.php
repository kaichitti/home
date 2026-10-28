<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\Ledger;
use FuryoDacho\Models\Alert;

/**
 * ダッシュボードコントローラー
 */
class DashboardController extends BaseController
{
    /**
     * ダッシュボード表示
     * - 今月の台帳登録件数
     * - 未確認アラート件数（お知らせ欄に表示）
     * - 最近の登録5件
     */
    public function index(): void
    {
        $this->auth->requireAuth();

        $tenantId    = $this->auth->getTenantId();
        $ledgerModel = new Ledger($this->pdo);
        $alertModel  = new Alert($this->pdo);

        // 今月の登録件数
        $thisMonthCount = $ledgerModel->countThisMonth($tenantId);

        // 未確認アラート件数（お知らせ欄）
        $alertCount = $alertModel->countUnconfirmed($tenantId);

        // 最近の登録5件
        $recentRecords = $ledgerModel->getRecent($tenantId, 5);

        // 後方互換: 既存ビューで使われていた変数も維持
        $currentFiscalYear = $ledgerModel->getFiscalYear(date('Y-m-d'));
        $totalRecords      = $ledgerModel->countByTenant($tenantId);
        $thisYear          = $ledgerModel->countByTenant($tenantId, ['fiscal_year' => $currentFiscalYear]);

        // 本日のPOS売上（POSテーブル未作成の環境では表示しない）
        $posToday = null;
        try {
            \FuryoDacho\Models\PosSchema::ensure($this->pdo);
            $posToday = (new \FuryoDacho\Models\PosTransaction($this->pdo))
                ->dailySummary($tenantId, date('Y-m-d'), null);
        } catch (\Throwable $e) {
            $posToday = null;
        }

        // 承認待ち台帳（管理者のみ表示）
        $approvalCount = 0;
        if ($this->auth->isAdmin()) {
            try {
                $stmt = $this->pdo->prepare(
                    "SELECT COUNT(*) FROM `ledgers`
                     WHERE `tenant_id` = ? AND `approval_status` = 'pending' AND `deleted_at` IS NULL"
                );
                $stmt->execute([$tenantId]);
                $approvalCount = (int)$stmt->fetchColumn();
            } catch (\Throwable $e) {
                $approvalCount = 0;
            }
        }

        $this->render('dashboard/index', [
            'pos_today'          => $posToday,
            'approval_count'     => $approvalCount,
            // ビュー（dashboard/index.php）は $monthly_count を参照する。
            // 以前は this_month_count しか渡しておらず「今月の登録件数」が常に0表示だった。
            'monthly_count'      => $thisMonthCount,
            'this_month_count'   => $thisMonthCount,
            'alert_count'        => $alertCount,
            'recent_records'     => $recentRecords,
            // 後方互換変数
            'total_records'      => $totalRecords,
            'this_year'          => $thisYear,
            'current_year'       => $currentFiscalYear,
        ]);
    }
}
