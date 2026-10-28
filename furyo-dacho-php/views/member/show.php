<?php
/**
 * 会員詳細（基本情報・POSでの購入履歴・買取（台帳）履歴）
 *
 * 変数: $member, $stats, $recent, $recentTotal, $ledgers, $buyCount, $buyTotal
 */
$pageTitle  = '会員詳細 ' . ($member['member_code'] ?? '') . ' - 古物台帳管理システム';
$activePage = 'member';
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
$yen = static fn ($v): string => ((int)$v < 0 ? '-¥' : '¥') . number_format(abs((int)$v));
$methods = \FuryoDacho\Helpers\ReceiptLayout::PAYMENT_LABELS;
$typeLabels = ['buy' => '買取', 'exchange' => '交換', 'consignment' => '委託', 'other' => 'その他'];
$id = (int)$member['id'];
$allQ = 'member_id=' . $id . '&date_from=2000-01-01&date_to=' . date('Y-m-d');

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">会員詳細 <?= $h($member['member_code']) ?></h1>
    <div class="page-header__actions">
        <a href="/index.php?page=member" class="btn btn-secondary">会員一覧へ</a>
        <a href="/index.php?page=member.edit&id=<?= $id ?>" class="btn btn-outline">編集</a>
        <a href="/index.php?page=pos" class="btn btn-primary">POSレジ</a>
    </div>
</div>

<div class="stat-cards">
    <div class="stat-card"><div class="stat-card__label">POS購入回数</div><div class="stat-card__value"><?= (int)$stats['count'] ?>回</div>
        <div class="stat-card__sub">取消を除く</div></div>
    <div class="stat-card"><div class="stat-card__label">POS購入額 累計</div><div class="stat-card__value"><?= $yen($stats['total']) ?></div>
        <div class="stat-card__sub">最終購入 <?= $stats['last_at'] ? $h(substr((string)$stats['last_at'], 0, 10)) : '-' ?></div></div>
    <div class="stat-card"><div class="stat-card__label">買取・取引（台帳）</div><div class="stat-card__value"><?= (int)$buyCount ?>件</div>
        <div class="stat-card__sub">取引金額 計 <?= $yen($buyTotal) ?></div></div>
</div>

<div class="member-grid">
    <div class="card">
        <div class="card__header">基本情報</div>
        <div class="card__body" style="padding:0;">
            <table class="detail-table">
                <tr><th>会員番号</th><td><?= $h($member['member_code']) ?></td></tr>
                <tr><th>区分</th><td><?= $member['counterpart_type'] === 'corporate' ? '法人' : '個人' ?></td></tr>
                <tr><th><?= $member['counterpart_type'] === 'corporate' ? '名称' : '氏名' ?></th><td><?= $h($member['name']) ?></td></tr>
                <?php if (!empty($member['contact_name'])): ?><tr><th>担当者</th><td><?= $h($member['contact_name']) ?></td></tr><?php endif; ?>
                <?php if ($member['counterpart_type'] !== 'corporate'): ?>
                <tr><th>職業</th><td><?= $h($member['occupation'] ?? '') ?: '-' ?></td></tr>
                <tr><th>年齢</th><td><?= ($member['age'] ?? null) !== null && $member['age'] !== '' ? (int)$member['age'] . ' 歳' : '-' ?></td></tr>
                <?php endif; ?>
                <tr><th>電話番号</th><td><?= $h($member['phone'] ?? '') ?: '-' ?></td></tr>
                <tr><th>住所</th><td><?= $h($member['address'] ?? '') ?: '-' ?></td></tr>
                <?php if (!empty($member['account'])): ?><tr><th>取引アカウント</th><td><?= $h($member['account']) ?></td></tr><?php endif; ?>
                <?php
                $memberDocLabels = [
                    'driver_license' => '運転免許証', 'my_number' => 'マイナンバーカード', 'passport' => 'パスポート',
                    'health_insurance' => '健康保険証', 'residence_card' => '住民基本台帳カード', 'residence_status' => '在留カード',
                    'special_permanent' => '特別永住者証明書', 'other' => 'その他',
                ];
                ?>
                <tr><th>本人確認</th><td><?= !empty($member['id_document_type'])
                    ? '<span class="badge badge-success">確認済み</span> ' . $h($memberDocLabels[$member['id_document_type']] ?? (string)$member['id_document_type'])
                    : '<span class="badge badge-warning">未登録</span>' ?></td></tr>
                <?php if (!empty($member['note'])): ?><tr><th>備考</th><td style="white-space:pre-wrap;"><?= $h($member['note']) ?></td></tr><?php endif; ?>
                <tr><th>登録日</th><td><?= $h(substr((string)$member['created_at'], 0, 10)) ?></td></tr>
            </table>
        </div>
    </div>

    <div>
        <div class="card">
            <div class="card__header">
                POSでの購入履歴（新しい順<?= (int)$recentTotal > 20 ? '・最新20件' : '' ?>）
                <span style="display:flex; gap:6px;">
                    <a href="/index.php?page=pos.history&<?= $h($allQ) ?>" class="btn btn-outline btn-sm">すべての取引</a>
                    <a href="/index.php?page=pos.items&<?= $h($allQ) ?>" class="btn btn-outline btn-sm">購入した明細</a>
                </span>
            </div>
            <?php if (empty($recent)): ?>
                <div class="card__body text-muted" style="font-size:.85rem;">POSでの購入はまだありません。POSレジの「会員」欄でこの会員を選んで会計すると、ここに表示されます。</div>
            <?php else: ?>
            <div class="table-wrap" style="box-shadow:none;">
                <table class="table">
                    <thead><tr><th>日時</th><th>レジ / レシート番号</th><th>品名</th><th style="text-align:right;">合計</th><th>支払</th><th>状態</th><th></th></tr></thead>
                    <tbody>
                    <?php foreach ($recent as $r): $names = (string)($r['item_names'] ?? ''); ?>
                        <tr<?= $r['status'] === 'voided' ? ' style="opacity:.6;"' : '' ?>>
                            <td><?= $h(substr((string)$r['created_at'], 0, 16)) ?></td>
                            <td><?= !empty($r['register_no']) ? 'レジ' . sprintf('%02d', (int)$r['register_no']) . ' ' : '' ?><a href="/index.php?page=pos.show&id=<?= (int)$r['id'] ?>"><?= $h($r['receipt_no']) ?></a></td>
                            <td title="<?= $h($names) ?>"><?= $h(mb_strimwidth($names, 0, 30, '…')) ?></td>
                            <td style="text-align:right;<?= $r['status'] === 'voided' ? ' text-decoration:line-through;' : '' ?>"><?= $yen($r['total']) ?></td>
                            <td><?= $h($methods[$r['payment_method']] ?? '') ?></td>
                            <td><?= $r['status'] === 'voided' ? '<span class="badge badge-danger">取消</span>' : '<span class="badge badge-success">完了</span>' ?></td>
                            <td style="white-space:nowrap;"><button type="button" class="btn btn-outline btn-sm" data-reprint="<?= (int)$r['id'] ?>">再印刷</button></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
            <?php endif; ?>
        </div>

        <div class="card">
            <div class="card__header">買取・取引（台帳）<?= (int)$buyCount > 20 ? '（最新20件）' : '' ?></div>
            <?php if (empty($ledgers)): ?>
                <div class="card__body text-muted" style="font-size:.85rem;">この会員番号で登録された台帳はありません。</div>
            <?php else: ?>
            <div class="table-wrap" style="box-shadow:none;">
                <table class="table">
                    <thead><tr><th>取引日</th><th>種別</th><th>品名</th><th style="text-align:right;">数量</th><th style="text-align:right;">取引金額</th></tr></thead>
                    <tbody>
                    <?php foreach ($ledgers as $l): ?>
                        <tr>
                            <td><?= $h($l['transaction_date']) ?></td>
                            <td><?= $h($typeLabels[$l['transaction_type']] ?? $l['transaction_type']) ?></td>
                            <td><a href="/index.php?page=ledger.show&id=<?= (int)$l['id'] ?>"><?= $h($l['item_name']) ?></a></td>
                            <td style="text-align:right;"><?= (int)$l['quantity'] ?></td>
                            <td style="text-align:right;"><?= $l['transaction_amount'] !== null ? $yen($l['transaction_amount']) : '-' ?></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
            <?php endif; ?>
        </div>
    </div>
</div>

<style>
.member-grid { display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1.6fr); gap:16px; align-items:start; }
@media (max-width: 1000px) { .member-grid { grid-template-columns: minmax(0, 1fr); } }
</style>

<?php include __DIR__ . '/../pos/_printer.php'; ?>
<?php include __DIR__ . '/../pos/_reprint.php'; ?>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
