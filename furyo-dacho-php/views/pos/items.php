<?php
/**
 * レジ明細検索（会計明細を1行ずつ検索・集計）
 *
 * 変数: $rows, $total, $sumQty, $sumAmount, $sumAlloc, $filters, $page, $totalPages, $branches, $registers, $isAdmin
 */
$pageTitle  = 'レジ明細検索 - 古物台帳管理システム';
$activePage = 'pos.items';
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
$yen = static fn ($v): string => ((int)$v < 0 ? '-¥' : '¥') . number_format(abs((int)$v));
$methods = \FuryoDacho\Helpers\ReceiptLayout::PAYMENT_LABELS;
$query = static fn (array $f, array $extra = []): string => \FuryoDacho\Controllers\PosController::filterQuery($f, $extra);

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">レジ明細検索</h1>
    <div class="page-header__actions">
        <a href="/index.php?page=pos" class="btn btn-primary">POSレジ</a>
        <a href="/index.php?page=pos.history&<?= $h($query($filters)) ?>" class="btn btn-outline">取引単位で表示</a>
        <?php if (!empty($isAdmin)): ?>
            <a href="/index.php?page=pos.export&mode=items&<?= $h($query($filters)) ?>" class="btn btn-outline">CSV出力</a>
        <?php endif; ?>
    </div>
</div>

<?php include __DIR__ . '/_lookup_box.php'; ?>

<div class="card">
    <div class="card__body">
        <form method="GET" action="/index.php" class="pos-filter">
            <input type="hidden" name="page" value="pos.items">
            <?php if (!empty($filters['member_id'])): ?>
                <input type="hidden" name="member_id" value="<?= (int)$filters['member_id'] ?>">
            <?php endif; ?>
            <div class="form-group" style="grid-column: span 2;"><label class="form-label">品名・シリアル番号</label>
                <input type="text" name="keyword" class="form-control" maxlength="100" value="<?= $h($filters['keyword']) ?>" placeholder="品名・シリアル番号の一部" autofocus></div>
            <div class="form-group"><label class="form-label">台帳番号</label>
                <input type="text" name="ledger_id" class="form-control" inputmode="numeric" maxlength="18" value="<?= !empty($filters['ledger_id']) ? (int)$filters['ledger_id'] : '' ?>"></div>
            <?php include __DIR__ . '/_filter_fields.php'; ?>
            <div class="form-group" style="align-self:end;">
                <button type="submit" class="btn btn-primary">検索</button>
                <a href="/index.php?page=pos.items" class="btn btn-secondary">クリア</a>
            </div>
        </form>
        <?php if (!empty($filters['member_id'])): ?>
            <p class="text-muted" style="font-size:.8rem; margin-top:8px;">会員（ID <?= (int)$filters['member_id'] ?>）の明細に絞り込んでいます。
                <a href="/index.php?page=pos.items&<?= $h($query(array_merge($filters, ['member_id' => 0]))) ?>">解除</a></p>
        <?php endif; ?>
    </div>
</div>

<div class="pos-hist-sum">
    <span>該当 <b><?= number_format((int)$total) ?></b> 明細</span>
    <span>販売点数 <b><?= number_format((int)$sumQty) ?></b> 点</span>
    <span>明細金額 <b><?= $yen($sumAmount) ?></b></span>
    <span title="小計値引・外税を按分した、販売記録上の金額">売上計上額 <b><?= $yen($sumAlloc) ?></b></span>
    <span class="text-muted" style="font-size:.8rem;">（合計は取消を除く）</span>
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
                <th>シリアル</th>
                <th style="text-align:right;">単価</th>
                <th style="text-align:right;">数量</th>
                <th style="text-align:right;">値引</th>
                <th style="text-align:right;">金額</th>
                <th>支払</th>
                <th>会員</th>
                <th>担当</th>
                <th>状態</th>
                <th></th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($rows as $r): $voided = $r['status'] === 'voided'; ?>
            <tr<?= $voided ? ' style="opacity:.6;"' : '' ?>>
                <td><?= $h($r['created_at']) ?></td>
                <td><?= !empty($r['register_no']) ? sprintf('%02d', (int)$r['register_no']) : '-' ?></td>
                <td><a href="/index.php?page=pos.show&id=<?= (int)$r['tx_id'] ?>"><?= $h($r['receipt_no']) ?></a></td>
                <td style="white-space:normal; min-width:160px;">
                    <a href="/index.php?page=ledger.show&id=<?= (int)$r['ledger_id'] ?>" title="台帳 #<?= (int)$r['ledger_id'] ?>"><?= $h($r['item_name']) ?></a>
                </td>
                <td style="font-size:.8rem;"><?= $h($r['serial_number'] ?? '') ?></td>
                <td style="text-align:right;"><?= $yen($r['unit_price']) ?></td>
                <td style="text-align:right;"><?= (int)$r['quantity'] ?></td>
                <td style="text-align:right;"><?= (int)$r['line_discount'] > 0 ? $yen(-(int)$r['line_discount']) : '-' ?></td>
                <td style="text-align:right; font-weight:600;<?= $voided ? ' text-decoration:line-through;' : '' ?>"><?= $yen($r['amount']) ?></td>
                <td><?= $h($methods[$r['payment_method']] ?? $r['payment_method']) ?></td>
                <td style="font-size:.8rem;">
                    <?php if (!empty($r['member_id'])): ?>
                        <a href="/index.php?page=member.show&id=<?= (int)$r['member_id'] ?>"><?= $h($r['member_code'] ?? '') ?></a><br><?= $h($r['member_name'] ?? '') ?>
                    <?php elseif (!empty($r['member_code'])): ?>
                        <?= $h($r['member_code']) ?>
                    <?php else: ?>-<?php endif; ?>
                </td>
                <td><?= $h($r['cashier_name'] ?? '') ?></td>
                <td><?= $voided ? '<span class="badge badge-danger">取消</span>' : '<span class="badge badge-success">完了</span>' ?></td>
                <td style="white-space:nowrap;">
                    <a href="/index.php?page=pos.show&id=<?= (int)$r['tx_id'] ?>" class="btn btn-secondary btn-sm">明細</a>
                    <button type="button" class="btn btn-outline btn-sm" data-reprint="<?= (int)$r['tx_id'] ?>">再印刷</button>
                </td>
            </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    <?php else: ?>
    <div class="empty-state" style="background:#fff;">
        <div class="empty-state__icon">&#128269;</div>
        <div class="empty-state__text">該当する明細はありません（期間の既定は本日です）</div>
    </div>
    <?php endif; ?>
</div>

<?php if ($totalPages > 1): ?>
<div class="pagination">
    <a href="/index.php?<?= $h($query($filters, ['page' => 'pos.items', 'p' => max(1, $page - 1)])) ?>" class="pagination__item <?= $page <= 1 ? 'disabled' : '' ?>">&#8249;</a>
    <?php for ($i = max(1, $page - 3); $i <= min($totalPages, $page + 3); $i++): ?>
        <a href="/index.php?<?= $h($query($filters, ['page' => 'pos.items', 'p' => $i])) ?>" class="pagination__item <?= $i === $page ? 'active' : '' ?>"><?= $i ?></a>
    <?php endfor; ?>
    <a href="/index.php?<?= $h($query($filters, ['page' => 'pos.items', 'p' => min($totalPages, $page + 1)])) ?>" class="pagination__item <?= $page >= $totalPages ? 'disabled' : '' ?>">&#8250;</a>
</div>
<?php endif; ?>

<style>
.pos-filter { display:grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap:10px; }
.pos-filter .form-group { margin:0; }
.pos-hist-sum { display:flex; gap:20px; flex-wrap:wrap; margin:0 0 12px; font-size:.9rem; align-items:baseline; }
@media (max-width: 768px) { .pos-filter .form-group[style*="span 2"] { grid-column: auto !important; } }
</style>

<?php include __DIR__ . '/_printer.php'; ?>
<?php include __DIR__ . '/_reprint.php'; ?>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
