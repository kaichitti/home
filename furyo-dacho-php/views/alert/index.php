<?php
$pageTitle  = 'アラート管理 - 古物台帳管理システム';
$activePage = 'alert';

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">重複検知アラート</h1>
</div>

<?php if (!empty($flashSuccess)): ?>
<div class="alert alert-success"><?= htmlspecialchars($flashSuccess) ?></div>
<?php endif; ?>

<?php if (!empty($alerts)): ?>
<?php foreach ($alerts as $alert): ?>
<?php $isPending = ($alert['status'] ?? '') !== 'confirmed'; ?>
<div class="card" style="border-left: 4px solid <?= $isPending ? 'var(--color-danger)' : 'var(--color-border)' ?>;">
    <div class="card__header">
        <div class="d-flex align-center gap-8">
            <?php if ($isPending): ?>
                <span class="badge badge-danger">未確認</span>
            <?php else: ?>
                <span class="badge badge-secondary">確認済み</span>
            <?php endif; ?>
            <span style="font-size: 0.85rem; font-weight: 400; color: #6c757d;">
                アラートID #<?= (int)$alert['id'] ?>
                &nbsp;／&nbsp;検知日時: <?= htmlspecialchars($alert['created_at'] ?? '') ?>
            </span>
        </div>
        <?php if (!empty($isAdmin) && $isPending): ?>
        <form method="POST" action="/index.php?page=alert.confirm&id=<?= (int)$alert['id'] ?>" style="margin: 0;">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
            <button type="submit" class="btn btn-success btn-sm">確認処理</button>
        </form>
        <?php endif; ?>
    </div>
    <div class="card__body">
        <div class="alert-compare">

            <!-- レコードA -->
            <div style="background: #f8f9ff; border-radius: 4px; padding: 14px;">
                <div style="font-size: 0.75rem; font-weight: 700; color: var(--color-primary); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px;">
                    レコード A
                    &nbsp;
                    <a href="/index.php?page=ledger.show&id=<?= (int)($alert['record_a_id'] ?? 0) ?>"
                       style="font-weight: 400; font-size: 0.75rem;">#<?= (int)($alert['record_a_id'] ?? 0) ?></a>
                </div>
                <table style="width:100%; font-size: 0.85rem; border-collapse: collapse;">
                    <tr>
                        <td style="color: #6c757d; padding: 3px 0; width: 40%;">品目</td>
                        <td style="padding: 3px 0; font-weight: 600;"><?= htmlspecialchars($alert['record_a_item_name'] ?? '-') ?></td>
                    </tr>
                    <tr>
                        <td style="color: #6c757d; padding: 3px 0;">取引金額</td>
                        <td style="padding: 3px 0;">
                            <?php if (isset($alert['record_a_price'])): ?>
                                &#165;<?= number_format((int)$alert['record_a_price']) ?>
                            <?php else: ?>
                                -
                            <?php endif; ?>
                        </td>
                    </tr>
                    <tr>
                        <td style="color: #6c757d; padding: 3px 0;">登録日</td>
                        <td style="padding: 3px 0;"><?= htmlspecialchars($alert['record_a_created_at'] ?? '-') ?></td>
                    </tr>
                    <tr>
                        <td style="color: #6c757d; padding: 3px 0;">登録者</td>
                        <td style="padding: 3px 0;"><?= htmlspecialchars($alert['record_a_created_by'] ?? '-') ?></td>
                    </tr>
                </table>
            </div>

            <!-- レコードB -->
            <div style="background: #fff8f8; border-radius: 4px; padding: 14px;">
                <div style="font-size: 0.75rem; font-weight: 700; color: var(--color-danger); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px;">
                    レコード B
                    &nbsp;
                    <a href="/index.php?page=ledger.show&id=<?= (int)($alert['record_b_id'] ?? 0) ?>"
                       style="font-weight: 400; font-size: 0.75rem;">#<?= (int)($alert['record_b_id'] ?? 0) ?></a>
                </div>
                <table style="width:100%; font-size: 0.85rem; border-collapse: collapse;">
                    <tr>
                        <td style="color: #6c757d; padding: 3px 0; width: 40%;">品目</td>
                        <td style="padding: 3px 0; font-weight: 600;"><?= htmlspecialchars($alert['record_b_item_name'] ?? '-') ?></td>
                    </tr>
                    <tr>
                        <td style="color: #6c757d; padding: 3px 0;">取引金額</td>
                        <td style="padding: 3px 0;">
                            <?php if (isset($alert['record_b_price'])): ?>
                                &#165;<?= number_format((int)$alert['record_b_price']) ?>
                            <?php else: ?>
                                -
                            <?php endif; ?>
                        </td>
                    </tr>
                    <tr>
                        <td style="color: #6c757d; padding: 3px 0;">登録日</td>
                        <td style="padding: 3px 0;"><?= htmlspecialchars($alert['record_b_created_at'] ?? '-') ?></td>
                    </tr>
                    <tr>
                        <td style="color: #6c757d; padding: 3px 0;">登録者</td>
                        <td style="padding: 3px 0;"><?= htmlspecialchars($alert['record_b_created_by'] ?? '-') ?></td>
                    </tr>
                </table>
            </div>

        </div>

        <?php if (!empty($alert['confirmed_by_name'])): ?>
        <div class="mt-8" style="font-size: 0.8rem; color: #6c757d;">
            確認処理者: <?= htmlspecialchars($alert['confirmed_by_name']) ?>
            &nbsp;／&nbsp;
            確認日時: <?= htmlspecialchars($alert['confirmed_at'] ?? '') ?>
        </div>
        <?php endif; ?>
    </div>
</div>
<?php endforeach; ?>

<?php if (!empty($pagination) && (int)($pagination['total_pages'] ?? 0) > 1): ?>
<?php
$cp      = (int)($pagination['current_page'] ?? 1);
$tp      = (int)$pagination['total_pages'];
$baseUrl = '/index.php?page=alert' . (!empty($status) ? '&status=' . urlencode($status) : '');
?>
<div class="pagination">
    <a href="<?= htmlspecialchars($baseUrl . '&p=' . max(1, $cp - 1)) ?>"
       class="pagination__item <?= $cp <= 1 ? 'disabled' : '' ?>">&#8249;</a>
    <?php for ($i = max(1, $cp - 3); $i <= min($tp, $cp + 3); $i++): ?>
    <a href="<?= htmlspecialchars($baseUrl . '&p=' . $i) ?>"
       class="pagination__item <?= $i === $cp ? 'active' : '' ?>"><?= $i ?></a>
    <?php endfor; ?>
    <a href="<?= htmlspecialchars($baseUrl . '&p=' . min($tp, $cp + 1)) ?>"
       class="pagination__item <?= $cp >= $tp ? 'disabled' : '' ?>">&#8250;</a>
</div>
<?php endif; ?>

<?php else: ?>
<div class="empty-state" style="background:#fff; border-radius: 4px; box-shadow: var(--shadow);">
    <div class="empty-state__icon">&#9989;</div>
    <div class="empty-state__text">現在、未確認のアラートはありません</div>
</div>
<?php endif; ?>

<style>
/* 2件の台帳を左右に並べて比較（スマホでは縦に並べる） */
.alert-compare { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
@media (max-width: 600px) { .alert-compare { grid-template-columns: minmax(0, 1fr); } }
</style>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
