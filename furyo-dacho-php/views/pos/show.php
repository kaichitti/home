<?php
/**
 * POS 取引詳細（レシート再発行・領収書・取消）
 *
 * 変数: $tx, $items, $settings, $isAdmin, $csrf_token
 */
$pageTitle  = '取引詳細 ' . ($tx['receipt_no'] ?? '') . ' - 古物台帳管理システム';
$activePage = 'pos.history';
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
$yen = static fn ($v): string => ((int)$v < 0 ? '-¥' : '¥') . number_format(abs((int)$v));
$methods = \FuryoDacho\Helpers\ReceiptLayout::PAYMENT_LABELS;
$voided = ($tx['status'] ?? '') === 'voided';
$receiptLabels = [
    'printed'      => '印刷済',
    'unprinted'    => '未印刷（プリンタ未接続のため画面に発行）',
    'print_failed' => '印刷失敗',
    'pending'      => '未印刷',
];
$id = (int)$tx['id'];

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">
        取引詳細 No.<?= $h($tx['receipt_no']) ?>
        <?php if ($voided): ?><span class="badge badge-danger" style="font-size:.85rem; vertical-align:middle;">取消済</span><?php endif; ?>
    </h1>
    <div class="page-header__actions">
        <a href="/index.php?page=pos.history&date_from=<?= $h(substr((string)$tx['created_at'], 0, 10)) ?>&date_to=<?= $h(substr((string)$tx['created_at'], 0, 10)) ?>" class="btn btn-secondary">取引履歴へ</a>
        <a href="/index.php?page=pos.items&receipt_no=<?= $h($tx['receipt_no']) ?>&date_from=<?= $h(substr((string)$tx['created_at'], 0, 10)) ?>&date_to=<?= $h(substr((string)$tx['created_at'], 0, 10)) ?>" class="btn btn-outline">レジ明細で表示</a>
        <a href="/index.php?page=pos" class="btn btn-primary">POSレジ</a>
    </div>
</div>

<div class="pos-show-grid">
    <div>
        <div class="card">
            <div class="card__header">会計情報</div>
            <div class="card__body" style="padding:0;">
                <table class="detail-table">
                    <tr><th>会計日時</th><td><?= $h($tx['created_at']) ?></td></tr>
                    <tr><th>レジ / レシート番号</th><td><?= !empty($tx['register_no']) ? 'レジ' . sprintf('%02d', (int)$tx['register_no']) . '　' : '' ?><?= $h($tx['receipt_no']) ?></td></tr>
                    <tr><th>担当</th><td><?= $h($tx['cashier_name'] ?? '') ?><?= !empty($tx['branch_name']) ? '（' . $h($tx['branch_name']) . '）' : '' ?></td></tr>
                    <?php if (!empty($tx['member_code'])): ?>
                        <tr><th>会員</th><td>
                            <?php if (!empty($tx['member_id'])): ?>
                                <a href="/index.php?page=member.show&id=<?= (int)$tx['member_id'] ?>"><?= $h($tx['member_code']) ?>　<?= $h($tx['member_name'] ?? '') ?></a>
                                <span class="text-muted" style="font-size:.8rem;">（<a href="/index.php?page=pos.history&member_id=<?= (int)$tx['member_id'] ?>&date_from=2000-01-01">この会員の取引履歴</a>）</span>
                            <?php else: ?>
                                <?= $h($tx['member_code']) ?>　<?= $h($tx['member_name'] ?? '') ?>
                            <?php endif; ?>
                        </td></tr>
                    <?php endif; ?>
                    <tr><th>支払方法</th><td><?= $h($methods[$tx['payment_method']] ?? $tx['payment_method']) ?>
                        <?= !empty($tx['payment_ref']) ? '（承認番号等: ' . $h($tx['payment_ref']) . '）' : '' ?></td></tr>
                    <tr><th>小計（<?= (int)$tx['item_count'] ?>点）</th><td><?= $yen($tx['subtotal']) ?></td></tr>
                    <?php if ((int)$tx['discount_amount'] > 0): ?>
                        <tr><th>値引<?= $tx['discount_type'] === 'percent' ? '（' . (int)$tx['discount_value'] . '%）' : '' ?></th><td><?= $yen(-(int)$tx['discount_amount']) ?></td></tr>
                    <?php endif; ?>
                    <?php if ((int)$tx['tax_rate'] > 0): ?>
                        <tr><th><?= $tx['tax_mode'] === 'exclusive' ? '消費税等（外税' : '内消費税等（' ?><?= (int)$tx['tax_rate'] ?>%）</th><td><?= $yen($tx['tax_amount']) ?></td></tr>
                    <?php endif; ?>
                    <tr><th>合計</th><td style="font-size:1.2rem; font-weight:700;<?= $voided ? ' text-decoration:line-through;' : '' ?>"><?= $yen($tx['total']) ?></td></tr>
                    <?php if ($tx['payment_method'] === 'cash'): ?>
                        <tr><th>お預り / お釣り</th><td><?= $yen($tx['tendered']) ?> / <?= $yen($tx['change_amount']) ?></td></tr>
                    <?php endif; ?>
                    <?php if (!empty($tx['note'])): ?>
                        <tr><th>備考</th><td><?= $h($tx['note']) ?></td></tr>
                    <?php endif; ?>
                    <tr><th>レシート</th><td><?= $h($receiptLabels[$tx['receipt_status']] ?? '-') ?>
                        （印刷 <?= (int)$tx['print_count'] ?>回<?= (int)$tx['ryoshu_count'] > 0 ? '・領収書 ' . (int)$tx['ryoshu_count'] . '回' : '' ?>）</td></tr>
                    <?php if ($voided): ?>
                        <tr><th>取消</th><td><?= $h($tx['voided_at']) ?> <?= $h($tx['voided_by_name'] ?? '') ?><br>理由: <?= $h($tx['void_reason'] ?? '') ?></td></tr>
                    <?php endif; ?>
                </table>
            </div>
        </div>

        <div class="card">
            <div class="card__header">明細</div>
            <div class="table-wrap" style="box-shadow:none;">
                <table class="table">
                    <thead><tr><th>品名</th><th style="text-align:right;">単価</th><th style="text-align:right;">数量</th><th style="text-align:right;">値引</th><th style="text-align:right;">金額</th><th style="text-align:right;" title="小計値引・外税を按分した販売記録上の金額">売上計上</th></tr></thead>
                    <tbody>
                    <?php foreach ($items as $it): ?>
                        <tr>
                            <td style="white-space:normal;">
                                <a href="/index.php?page=ledger.show&id=<?= (int)$it['ledger_id'] ?>"><?= $h($it['item_name']) ?></a>
                                <div class="text-muted" style="font-size:.75rem;">台帳 #<?= (int)$it['ledger_id'] ?><?= !empty($it['serial_number']) ? ' / SN: ' . $h($it['serial_number']) : '' ?></div>
                            </td>
                            <td style="text-align:right;"><?= $yen($it['unit_price']) ?></td>
                            <td style="text-align:right;"><?= (int)$it['quantity'] ?></td>
                            <td style="text-align:right;"><?= (int)$it['line_discount'] > 0 ? $yen(-(int)$it['line_discount']) : '-' ?></td>
                            <td style="text-align:right;"><?= $yen($it['amount']) ?></td>
                            <td style="text-align:right;" class="text-muted"><?= $yen($it['allocated_amount']) ?></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
        </div>

        <div class="card">
            <div class="card__header">操作</div>
            <div class="card__body">
                <div id="show_status" class="alert alert-info" style="display:none; white-space:pre-wrap;"></div>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                    <button type="button" class="btn btn-primary" id="show_print">
                        <?= (int)$tx['print_count'] > 0 ? 'レシートを再発行（印刷）' : 'レシートを印刷' ?>
                    </button>
                    <button type="button" class="btn btn-outline" id="show_ryoshu">領収書を発行</button>
                    <a href="/index.php?page=pos.receipt&id=<?= $id ?>" class="btn btn-outline" target="_blank" rel="noopener">レシートを別画面で表示</a>
                </div>
                <?php if (!empty($isAdmin) && !$voided): ?>
                <hr style="margin:16px 0; border:none; border-top:1px solid #eee;">
                <form method="POST" action="/index.php?page=pos.void" id="void_form"
                      onsubmit="return confirm('この取引を取り消しますか？\n販売記録を削除して在庫を戻します（元に戻せません）。');">
                    <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
                    <input type="hidden" name="id" value="<?= $id ?>">
                    <div class="form-group" style="max-width:480px;">
                        <label class="form-label" for="void_reason">取引の取消（返品・打ち間違い）<span class="required">*</span></label>
                        <input type="text" id="void_reason" name="reason" class="form-control" maxlength="255" required placeholder="取消理由（例：お客様都合による返品）">
                        <div class="form-hint">取り消すと販売記録が削除され在庫が戻ります。返金は支払方法に応じて別途行ってください。会計とレシートの記録は「取消」として残ります。</div>
                    </div>
                    <button type="submit" class="btn btn-danger">この取引を取り消す</button>
                </form>
                <?php elseif (!$voided): ?>
                <p class="text-muted" style="font-size:.8rem; margin-top:12px;">取引の取消（返品）は管理者が行えます。</p>
                <?php endif; ?>
            </div>
        </div>
    </div>

    <div>
        <div class="card">
            <div class="card__header">レシート</div>
            <div class="card__body" style="padding:8px;">
                <iframe src="/index.php?page=pos.receipt&id=<?= $id ?>&embed=1" title="レシート" style="width:100%; height:640px; border:0;"></iframe>
            </div>
        </div>
    </div>
</div>

<style>
.pos-show-grid { display:grid; grid-template-columns: minmax(0,1.4fr) minmax(0,1fr); gap:16px; align-items:start; }
@media (max-width: 1000px) { .pos-show-grid { grid-template-columns: minmax(0, 1fr); } }
</style>

<?php include __DIR__ . '/_printer.php'; ?>
<?php include __DIR__ . '/_ryoshu_modal.php'; ?>
<script>
(function () {
    'use strict';
    var P = window.FuryoPrinter;
    var id = <?= $id ?>;
    var csrf = <?= json_encode($csrf_token ?? '', JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) ?>;
    function status(msg, kind) {
        var el = document.getElementById('show_status');
        el.className = 'alert alert-' + (kind || 'info');
        el.textContent = msg;
        el.style.display = msg ? '' : 'none';
    }
    document.getElementById('show_print').addEventListener('click', function () {
        var btn = this;
        btn.disabled = true;
        P.check().then(function (st) {
            if (!st.connected) {
                status('レシートプリンタが接続されていません。\n' + (st.reason || '') + '\n右のレシートを画面でご提示いただくか、「POS設定・プリンタ」で接続してください。', 'warning');
                btn.disabled = false;
                return;
            }
            status('印刷しています…');
            return P.printUrl('/index.php?page=pos.receipt&id=' + id).then(function () {
                var body = new URLSearchParams();
                body.append('_csrf_token', csrf); body.append('id', id); body.append('doc', 'receipt'); body.append('result', 'printed');
                return fetch('/index.php?page=pos.printed', { method: 'POST', body: body, credentials: 'same-origin' }).catch(function () {});
            }).then(function () {
                status('✓ レシートを印刷しました。（2回目以降は「再発行」と印字されます）', 'success');
                var f = document.querySelector('iframe[src*="pos.receipt"]');
                if (f) { f.src = f.src; }
            }, function (e) {
                status('印刷に失敗しました。' + (e && e.message ? '\n' + e.message : ''), 'danger');
            }).then(function () { btn.disabled = false; });
        });
    });
    document.getElementById('show_ryoshu').addEventListener('click', function () {
        window.PosRyoshu.open(id, <?= json_encode($settings['ryoshu_tadashi'] ?? '', JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_UNESCAPED_UNICODE) ?>,
            <?= json_encode((string)($tx['member_name'] ?? ''), JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_UNESCAPED_UNICODE) ?>);
    });
}());
</script>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
