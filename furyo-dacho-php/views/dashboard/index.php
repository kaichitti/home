<?php
$pageTitle  = 'ダッシュボード - 古物台帳管理システム';
$activePage = 'dashboard';

// アラート一覧・CSV/PDF出力は管理者専用の画面のため、一般ユーザーにはリンクを出さない
// （以前は全員にリンクを表示しており、一般ユーザーが押すと「権限がありません」になっていた）
$isAdminUser = !empty($isAdmin);
$alertCnt    = (int)($alert_count ?? 0);
$approvalCnt = (int)($approval_count ?? 0);

$transactionTypeLabels = [
    'buy' => '買取', 'exchange' => '交換', 'consignment' => '委託販売受け', 'other' => 'その他',
];

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">ダッシュボード</h1>
    <div class="page-header__actions">
        <a href="/index.php?page=ledger.create" class="btn btn-primary">台帳を新規登録</a>
        <a href="/index.php?page=pos" class="btn btn-outline">POSレジ</a>
    </div>
</div>

<!-- 統計カード -->
<div class="stat-cards">

    <a href="/index.php?page=ledger&amp;date_from=<?= date('Y-m-01') ?>&amp;date_to=<?= date('Y-m-t') ?>" class="stat-card">
        <div class="stat-card__label">今月の取引（台帳）</div>
        <div class="stat-card__value"><?= (int)($monthly_count ?? 0) ?></div>
        <div class="stat-card__sub">件（取引年月日が今月）</div>
    </a>

    <a href="/index.php?page=ledger&amp;fiscal_year=<?= (int)($current_year ?? date('Y')) ?>" class="stat-card">
        <div class="stat-card__label">年度累計（<?= (int)($current_year ?? date('Y')) ?>年度）</div>
        <div class="stat-card__value"><?= (int)($this_year ?? 0) ?></div>
        <div class="stat-card__sub">件</div>
    </a>

    <?php if (is_array($pos_today ?? null)): ?>
    <a href="/index.php?page=pos.daily" class="stat-card">
        <div class="stat-card__label">本日のPOS売上</div>
        <div class="stat-card__value">¥<?= number_format((int)$pos_today['total']) ?></div>
        <div class="stat-card__sub"><?= (int)$pos_today['tx_count'] ?>件・<?= (int)$pos_today['item_count'] ?>点<?= (int)$pos_today['void_count'] > 0 ? '（取消 ' . (int)$pos_today['void_count'] . '件）' : '' ?></div>
    </a>
    <?php endif; ?>

    <?php if ($isAdminUser): ?>
    <a href="/index.php?page=alert" class="stat-card">
        <div class="stat-card__label">未確認アラート</div>
        <div class="stat-card__value <?= $alertCnt > 0 ? 'has-alert' : '' ?>"><?= $alertCnt ?></div>
        <div class="stat-card__sub">
            <?php if ($alertCnt > 0): ?>
                <span style="color: #c0392b; font-weight: 600;">要確認</span>
            <?php else: ?>
                件（問題なし）
            <?php endif; ?>
        </div>
    </a>
    <?php if ($approvalCnt > 0): ?>
    <a href="/index.php?page=ledger&amp;approval=pending" class="stat-card">
        <div class="stat-card__label">承認待ち台帳</div>
        <div class="stat-card__value has-alert"><?= $approvalCnt ?></div>
        <div class="stat-card__sub"><span style="color: #c0392b; font-weight: 600;">要承認</span></div>
    </a>
    <?php endif; ?>
    <?php endif; ?>

    <a href="/index.php?page=ledger" class="stat-card">
        <div class="stat-card__label">台帳総件数</div>
        <div class="stat-card__value"><?= (int)($total_records ?? 0) ?></div>
        <div class="stat-card__sub">件（全期間）</div>
    </a>

</div>

<!-- アラートバナー（管理者のみ） -->
<?php if ($isAdminUser && $alertCnt > 0): ?>
<div class="alert alert-danger" style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;">
    <span>
        <strong>重複疑いのアラートが <?= $alertCnt ?> 件あります。</strong>
        内容を確認してください。
    </span>
    <a href="/index.php?page=alert" class="btn btn-danger btn-sm">アラートを確認する</a>
</div>
<?php endif; ?>

<!-- 最近の登録 -->
<div class="card">
    <div class="card__header">
        最近の登録（直近5件）
        <a href="/index.php?page=ledger" class="btn btn-outline btn-sm">一覧を見る</a>
    </div>
    <div class="table-wrap" style="box-shadow:none; border-radius:0;">
        <?php if (!empty($recent_records)): ?>
        <table class="table">
            <thead>
                <tr>
                    <th>台帳番号</th>
                    <th>取引年月日</th>
                    <th>品目</th>
                    <th>古物の種類</th>
                    <th>取引種別</th>
                    <th style="text-align:right;">取引金額</th>
                    <th>登録者</th>
                    <th>拠点</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                <?php foreach ($recent_records as $rec): ?>
                <tr>
                    <td>
                        <span style="font-family: monospace; font-size: 0.8rem; color: #6c757d;">
                            #<?= (int)$rec['id'] ?>
                        </span>
                    </td>
                    <td><?= htmlspecialchars($rec['transaction_date'] ?? '') ?></td>
                    <td style="white-space: normal; min-width: 120px;">
                        <?= htmlspecialchars($rec['item_name'] ?? '') ?>
                        <?php if (($rec['approval_status'] ?? 'none') === 'pending'): ?>
                        <span class="badge badge-danger">承認待ち</span>
                        <?php endif; ?>
                    </td>
                    <td>
                        <span class="badge badge-primary">
                            <?= htmlspecialchars(\FuryoDacho\Models\ItemCategory::label($rec['item_category'] ?? '', $rec['item_category_note'] ?? null)) ?>
                        </span>
                    </td>
                    <td><?= htmlspecialchars($transactionTypeLabels[$rec['transaction_type'] ?? ''] ?? ($rec['transaction_type'] ?? '')) ?></td>
                    <td style="text-align:right;">
                        <?= isset($rec['transaction_amount']) && $rec['transaction_amount'] !== '' ? '¥' . number_format((float)$rec['transaction_amount']) : '-' ?>
                    </td>
                    <td><?= (($_v = htmlspecialchars($rec['registered_by_name'] ?? '')) !== '' ? $_v : '-') ?></td>
                    <td><?= htmlspecialchars($rec['branch_name'] ?? '') ?></td>
                    <td>
                        <a href="/index.php?page=ledger.show&id=<?= (int)$rec['id'] ?>" class="btn btn-accent btn-sm">詳細</a>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
        <?php else: ?>
        <div class="empty-state">
            <div class="empty-state__icon" aria-hidden="true">&#128196;</div>
            <div class="empty-state__text">登録データがありません</div>
            <a href="/index.php?page=ledger.create" class="btn btn-primary" style="margin-top:14px;">最初の台帳を登録する</a>
        </div>
        <?php endif; ?>
    </div>
</div>

<!-- クイックアクション -->
<div style="display: flex; gap: 12px; flex-wrap: wrap;">
    <a href="/index.php?page=ledger" class="btn btn-outline">台帳一覧を見る</a>
    <a href="/index.php?page=member" class="btn btn-outline">会員管理</a>
    <a href="/index.php?page=pos.history" class="btn btn-outline">取引履歴</a>
    <?php if ($isAdminUser): ?>
    <a href="/index.php?page=export" class="btn btn-outline">CSV・PDFを出力</a>
    <a href="/index.php?page=report" class="btn btn-outline">集計レポート</a>
    <?php endif; ?>
</div>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
