<?php
/**
 * POS 取引履歴
 *
 * 変数: $rows, $total, $sumTotal, $sumCount, $filters, $page, $totalPages, $branches, $registers, $isAdmin
 */
$pageTitle  = '取引履歴 - 古物台帳管理システム';
$activePage = 'pos.history';
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
$methods = \FuryoDacho\Helpers\ReceiptLayout::PAYMENT_LABELS;
$receiptLabels = [
    'printed'      => ['印刷済', 'badge-success'],
    'unprinted'    => ['未印刷（画面発行）', 'badge-warning'],
    'print_failed' => ['印刷失敗', 'badge-danger'],
    'pending'      => ['未印刷', 'badge-secondary'],
];
$query = static fn (array $f, array $extra = []): string => \FuryoDacho\Controllers\PosController::filterQuery($f, $extra);

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">取引履歴</h1>
    <div class="page-header__actions">
        <a href="/index.php?page=pos" class="btn btn-primary">POSレジ</a>
        <a href="/index.php?page=pos.items&<?= $h($query($filters)) ?>" class="btn btn-outline">明細で表示</a>
        <a href="/index.php?page=pos.daily&date=<?= $h($filters['date_to']) ?>" class="btn btn-outline">レジ精算</a>
        <?php if (!empty($isAdmin)): ?>
            <a href="/index.php?page=pos.export&<?= $h($query($filters)) ?>" class="btn btn-outline">CSV出力</a>
        <?php endif; ?>
    </div>
</div>

<?php include __DIR__ . '/_lookup_box.php'; ?>

<div class="card">
    <div class="card__body">
        <form method="GET" action="/index.php" class="pos-filter">
            <input type="hidden" name="page" value="pos.history">
            <?php if (!empty($filters['member_id'])): ?>
                <input type="hidden" name="member_id" value="<?= (int)$filters['member_id'] ?>">
            <?php endif; ?>
            <?php include __DIR__ . '/_filter_fields.php'; ?>
            <div class="form-group"><label class="form-label">品名・シリアル</label>
                <input type="text" name="keyword" class="form-control" maxlength="100" value="<?= $h($filters['keyword']) ?>"></div>
            <div class="form-group" style="align-self:end;">
                <button type="submit" class="btn btn-primary">検索</button>
                <a href="/index.php?page=pos.history" class="btn btn-secondary">クリア</a>
            </div>
        </form>
        <?php if (!empty($filters['member_id'])): ?>
            <p class="text-muted" style="font-size:.8rem; margin-top:8px;">会員（ID <?= (int)$filters['member_id'] ?>）の取引に絞り込んでいます。
                <a href="/index.php?page=pos.history&<?= $h($query(array_merge($filters, ['member_id' => 0]))) ?>">解除</a></p>
        <?php endif; ?>
    </div>
</div>

<div class="pos-hist-sum">
    <span>該当 <b><?= number_format((int)$total) ?></b> 件</span>
    <span>完了 <b><?= number_format((int)$sumCount) ?></b> 件</span>
    <span>売上合計（取消を除く） <b>¥<?= number_format((int)$sumTotal) ?></b></span>
</div>

<div class="table-wrap">
    <?php if (!empty($rows)): ?>
    <table class="table table--striped">
        <thead>
            <tr>
                <th>会計日時</th>
                <th>レジ</th>
                <th>レシート番号</th>
                <th>品名</th>
                <th style="text-align:right;">点数</th>
                <th style="text-align:right;">合計</th>
                <th>支払</th>
                <th>会員</th>
                <th>担当</th>
                <th>レシート</th>
                <th>状態</th>
                <th></th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($rows as $r):
                $rl = $receiptLabels[$r['receipt_status']] ?? ['-', 'badge-secondary'];
                $names = (string)($r['item_names'] ?? '');
            ?>
            <tr<?= $r['status'] === 'voided' ? ' style="opacity:.6;"' : '' ?>>
                <td><?= $h($r['created_at']) ?></td>
                <td><?= !empty($r['register_no']) ? sprintf('%02d', (int)$r['register_no']) : '-' ?></td>
                <td><a href="/index.php?page=pos.show&id=<?= (int)$r['id'] ?>"><?= $h($r['receipt_no']) ?></a></td>
                <td style="max-width:260px; overflow:hidden; text-overflow:ellipsis;" title="<?= $h($names) ?>"><?= $h(mb_strimwidth($names, 0, 36, '…')) ?></td>
                <td style="text-align:right;"><?= (int)$r['item_count'] ?></td>
                <td style="text-align:right; font-weight:600;<?= $r['status'] === 'voided' ? ' text-decoration:line-through;' : '' ?>">¥<?= number_format((int)$r['total']) ?></td>
                <td><?= $h($methods[$r['payment_method']] ?? $r['payment_method']) ?></td>
                <td style="font-size:.8rem;">
                    <?php if (!empty($r['member_id'])): ?>
                        <a href="/index.php?page=member.show&id=<?= (int)$r['member_id'] ?>"><?= $h($r['member_code'] ?? '') ?></a><br><?= $h($r['member_name'] ?? '') ?>
                    <?php elseif (!empty($r['member_code'])): ?>
                        <?= $h($r['member_code']) ?>
                    <?php else: ?>-<?php endif; ?>
                </td>
                <td><?= $h($r['cashier_name'] ?? '') ?></td>
                <td><span class="badge <?= $rl[1] ?>"><?= $h($rl[0]) ?></span><?= (int)$r['print_count'] > 1 ? ' <small class="text-muted">再' . ((int)$r['print_count'] - 1) . '</small>' : '' ?></td>
                <td><?= $r['status'] === 'voided' ? '<span class="badge badge-danger">取消</span>' : '<span class="badge badge-success">完了</span>' ?></td>
                <td style="white-space:nowrap;">
                    <a href="/index.php?page=pos.show&id=<?= (int)$r['id'] ?>" class="btn btn-secondary btn-sm">明細</a>
                    <button type="button" class="btn btn-outline btn-sm" data-reprint="<?= (int)$r['id'] ?>">再印刷</button>
                </td>
            </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    <?php else: ?>
    <div class="empty-state" style="background:#fff;">
        <div class="empty-state__icon">&#128203;</div>
        <div class="empty-state__text">該当する取引はありません</div>
    </div>
    <?php endif; ?>
</div>

<?php if ($totalPages > 1): ?>
<div class="pagination">
    <a href="/index.php?<?= $h($query($filters, ['page' => 'pos.history', 'p' => max(1, $page - 1)])) ?>" class="pagination__item <?= $page <= 1 ? 'disabled' : '' ?>">&#8249;</a>
    <?php for ($i = max(1, $page - 3); $i <= min($totalPages, $page + 3); $i++): ?>
        <a href="/index.php?<?= $h($query($filters, ['page' => 'pos.history', 'p' => $i])) ?>" class="pagination__item <?= $i === $page ? 'active' : '' ?>"><?= $i ?></a>
    <?php endfor; ?>
    <a href="/index.php?<?= $h($query($filters, ['page' => 'pos.history', 'p' => min($totalPages, $page + 1)])) ?>" class="pagination__item <?= $page >= $totalPages ? 'disabled' : '' ?>">&#8250;</a>
</div>
<?php endif; ?>

<style>
.pos-filter { display:grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap:10px; }
.pos-filter .form-group { margin:0; }
.pos-hist-sum { display:flex; gap:20px; flex-wrap:wrap; margin:0 0 12px; font-size:.9rem; }
</style>

<?php include __DIR__ . '/_printer.php'; ?>
<?php include __DIR__ . '/_reprint.php'; ?>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
