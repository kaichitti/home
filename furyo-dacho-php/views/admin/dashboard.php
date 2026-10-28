<?php
/**
 * システム管理者ダッシュボード
 * 変数: $tenants (array: 利用状況付き), $totalCount (int)
 */
require_once __DIR__ . '/_tenant_helpers.php';
$tenants    = $tenants    ?? [];
$totalCount = $totalCount ?? count($tenants);
$adminTitle = 'ダッシュボード';

$activeCount = 0;
$suspendedCount = 0;
$userTotal = 0;
$ledgerTotal = 0;
foreach ($tenants as $t) {
    if (($t['status'] ?? '') === 'active') {
        $activeCount++;
    } elseif (($t['status'] ?? '') === 'suspended') {
        $suspendedCount++;
    }
    $userTotal   += (int)($t['active_user_count'] ?? 0);
    $ledgerTotal += (int)($t['ledger_count'] ?? 0);
}
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
?>
<div class="page-header">
    <h1 class="page-header__title">システム管理 ダッシュボード</h1>
    <div class="page-header__actions">
        <a href="/admin/index.php?page=tenant.create" class="btn btn-primary">＋ 新規テナント登録</a>
    </div>
</div>

<div class="stat-cards">
    <div class="stat-card">
        <div class="stat-card__label">テナント総数</div>
        <div class="stat-card__value"><?= (int)$totalCount ?></div>
    </div>
    <div class="stat-card stat-card--success">
        <div class="stat-card__label">有効</div>
        <div class="stat-card__value"><?= $activeCount ?></div>
    </div>
    <div class="stat-card stat-card--warning">
        <div class="stat-card__label">停止中</div>
        <div class="stat-card__value"><?= $suspendedCount ?></div>
    </div>
    <div class="stat-card stat-card--accent">
        <div class="stat-card__label">有効な利用者 / 台帳件数（全テナント）</div>
        <div class="stat-card__value" style="font-size:1.5rem;"><?= number_format($userTotal) ?>人 / <?= number_format($ledgerTotal) ?>件</div>
    </div>
</div>

<div class="card">
    <div class="card__header">
        テナント一覧
        <a href="/admin/index.php?page=tenant" class="btn btn-outline btn-sm">テナント管理へ</a>
    </div>
    <div class="table-wrap">
        <table class="table">
            <thead>
                <tr>
                    <th>コード</th>
                    <th>テナント名</th>
                    <th>種別</th>
                    <th>状態</th>
                    <th style="text-align:right;">利用者</th>
                    <th style="text-align:right;">台帳</th>
                    <th>最終ログイン</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
            <?php if (empty($tenants)): ?>
                <tr><td colspan="8" class="empty-state">テナントが登録されていません。</td></tr>
            <?php else: ?>
                <?php foreach ($tenants as $t): ?>
                <tr>
                    <td class="nowrap"><code><?= $h($t['code'] ?? '') ?></code></td>
                    <td><a href="/admin/index.php?page=tenant.show&amp;id=<?= (int)$t['id'] ?>"><?= $h($t['name'] ?? '') ?></a></td>
                    <td class="nowrap"><?= $h(furyo_admin_type_label((string)($t['type'] ?? ''))) ?></td>
                    <td class="nowrap"><?= furyo_admin_status_badge((string)($t['status'] ?? '')) ?></td>
                    <td class="nowrap" style="text-align:right;"><?= (int)($t['active_user_count'] ?? 0) ?>人</td>
                    <td class="nowrap" style="text-align:right;"><?= number_format((int)($t['ledger_count'] ?? 0)) ?>件</td>
                    <td class="nowrap" style="font-size:.8rem;"><?= !empty($t['last_login_at']) ? $h(substr((string)$t['last_login_at'], 0, 16)) : '<span class="text-muted">-</span>' ?></td>
                    <td class="nowrap"><a href="/admin/index.php?page=tenant.show&amp;id=<?= (int)$t['id'] ?>" class="btn btn-accent btn-sm">詳細</a></td>
                </tr>
                <?php endforeach; ?>
            <?php endif; ?>
            </tbody>
        </table>
    </div>
</div>
