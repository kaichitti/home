<?php
/**
 * レジ精算（日計表・現金過不足）
 *
 * 変数: $date, $branchId, $registerNo, $registers, $branches, $branchLabel, $summary, $closings, $closedId, $denominations, $csrf_token
 */
$pageTitle  = 'レジ精算 - 古物台帳管理システム';
$activePage = 'pos.daily';
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
$yen = static fn ($v): string => ((int)$v < 0 ? '-¥' : '¥') . number_format(abs((int)$v));
$methods = \FuryoDacho\Helpers\ReceiptLayout::PAYMENT_LABELS;
$s = $summary;
$isToday = $date === date('Y-m-d');
$prev = date('Y-m-d', strtotime($date . ' -1 day'));
$next = date('Y-m-d', strtotime($date . ' +1 day'));
$registerNo = $registerNo ?? null;
$branchQ = ($branchId !== null ? '&branch=' . (int)$branchId : '') . ($registerNo !== null ? '&register=' . (int)$registerNo : '');
$scopeLabel = $branchLabel . ' ／ ' . ($registerNo !== null ? 'レジ' . sprintf('%02d', (int)$registerNo) : '全レジ');
$latest = null;
foreach ($closings as $c) {
    if (($c['branch_id'] === null ? null : (int)$c['branch_id']) === $branchId
        && (empty($c['register_no']) ? null : (int)$c['register_no']) === $registerNo) { $latest = $c; break; }
}

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">レジ精算（日計）</h1>
    <div class="page-header__actions">
        <a href="/index.php?page=pos.history&date_from=<?= $h($date) ?>&date_to=<?= $h($date) ?><?= $branchQ ?>" class="btn btn-outline">この日の取引</a>
        <a href="/index.php?page=pos" class="btn btn-primary">POSレジ</a>
    </div>
</div>

<div class="card">
    <div class="card__body">
        <form method="GET" action="/index.php" style="display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap;">
            <input type="hidden" name="page" value="pos.daily">
            <a href="/index.php?page=pos.daily&date=<?= $h($prev) ?><?= $branchQ ?>" class="btn btn-secondary">&#8249; 前日</a>
            <div class="form-group" style="margin:0;"><label class="form-label">営業日</label>
                <input type="date" name="date" class="form-control" value="<?= $h($date) ?>" max="<?= $h(date('Y-m-d')) ?>"></div>
            <?php if (count($branches) > 1): ?>
            <div class="form-group" style="margin:0;"><label class="form-label">拠点</label>
                <select name="branch" class="form-control">
                    <option value="">全拠点</option>
                    <?php foreach ($branches as $b): ?>
                        <option value="<?= (int)$b['id'] ?>" <?= $branchId === (int)$b['id'] ? 'selected' : '' ?>><?= $h($b['name']) ?></option>
                    <?php endforeach; ?>
                </select></div>
            <?php endif; ?>
            <div class="form-group" style="margin:0;"><label class="form-label">レジ</label>
                <select name="register" class="form-control">
                    <option value="">全レジ</option>
                    <?php foreach (array_unique(array_merge($registers ?? [], $registerNo !== null ? [$registerNo] : [])) as $rn): ?>
                        <option value="<?= (int)$rn ?>" <?= $registerNo === (int)$rn ? 'selected' : '' ?>>レジ<?= sprintf('%02d', (int)$rn) ?></option>
                    <?php endforeach; ?>
                </select></div>
            <button type="submit" class="btn btn-primary">表示</button>
            <?php if (!$isToday): ?>
                <a href="/index.php?page=pos.daily&date=<?= $h($next) ?><?= $branchQ ?>" class="btn btn-secondary">翌日 &#8250;</a>
            <?php endif; ?>
        </form>
    </div>
</div>

<div class="stat-cards">
    <div class="stat-card"><div class="stat-card__label">売上合計</div><div class="stat-card__value"><?= $yen($s['total']) ?></div>
        <div class="stat-card__sub"><?= (int)$s['tx_count'] ?>件・<?= (int)$s['item_count'] ?>点</div></div>
    <div class="stat-card"><div class="stat-card__label">現金売上</div><div class="stat-card__value"><?= $yen($s['cash_sales']) ?></div>
        <div class="stat-card__sub"><?= (int)$s['by_method']['cash']['count'] ?>件</div></div>
    <div class="stat-card"><div class="stat-card__label">値引合計</div><div class="stat-card__value"><?= $yen($s['discount']) ?></div>
        <div class="stat-card__sub">消費税等 <?= $yen($s['tax']) ?></div></div>
    <div class="stat-card"><div class="stat-card__label">取消</div><div class="stat-card__value<?= (int)$s['void_count'] > 0 ? ' has-alert' : '' ?>"><?= (int)$s['void_count'] ?>件</div>
        <div class="stat-card__sub"><?= $yen($s['void_total']) ?></div></div>
</div>

<div class="pos-daily-grid">
    <div>
        <div class="card">
            <div class="card__header">支払方法別（<?= $h($scopeLabel) ?>）</div>
            <div class="table-wrap" style="box-shadow:none;">
                <table class="table">
                    <thead><tr><th>支払方法</th><th style="text-align:right;">件数</th><th style="text-align:right;">金額</th></tr></thead>
                    <tbody>
                    <?php foreach ($methods as $k => $label): $m = $s['by_method'][$k]; ?>
                        <tr><td><?= $h($label) ?></td><td style="text-align:right;"><?= (int)$m['count'] ?></td><td style="text-align:right;"><?= $yen($m['total']) ?></td></tr>
                    <?php endforeach; ?>
                        <tr style="font-weight:700;"><td>合計</td><td style="text-align:right;"><?= (int)$s['tx_count'] ?></td><td style="text-align:right;"><?= $yen($s['total']) ?></td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <?php if (!empty($s['by_hour'])): ?>
        <div class="card">
            <div class="card__header">時間帯別</div>
            <div class="card__body">
                <?php $maxH = max(array_map(static fn ($x) => (int)$x['total'], $s['by_hour'])) ?: 1; ?>
                <?php foreach ($s['by_hour'] as $hour => $x): ?>
                    <div style="display:flex; align-items:center; gap:8px; font-size:.8rem; margin-bottom:4px;">
                        <span style="width:44px;"><?= (int)$hour ?>時台</span>
                        <span style="flex:1; background:#eef1f5; height:14px; border-radius:2px;">
                            <span style="display:block; height:14px; border-radius:2px; background:#3a7bd5; width:<?= max(1, (int)round((int)$x['total'] / $maxH * 100)) ?>%;"></span>
                        </span>
                        <span style="width:120px; text-align:right;"><?= (int)$x['count'] ?>件 <?= $yen($x['total']) ?></span>
                    </div>
                <?php endforeach; ?>
            </div>
        </div>
        <?php endif; ?>

        <?php if ((int)$s['refund_prev_count'] > 0): ?>
        <div class="alert alert-warning">
            この日に、前日以前の会計を <?= (int)$s['refund_prev_count'] ?>件（<?= $yen($s['refund_prev_total']) ?>）取り消しています。
            うち現金分 <?= $yen($s['refund_prev_cash']) ?> は、この日のレジから返金したものとして理論現金残高から差し引きます。
        </div>
        <?php endif; ?>

        <?php if ((int)$s['other_sales']['count'] > 0): ?>
        <div class="alert alert-info">
            参考: この日、台帳画面から直接登録された販売記録（POS以外）が <?= (int)$s['other_sales']['count'] ?>件・<?= (int)$s['other_sales']['qty'] ?>点・<?= $yen($s['other_sales']['total']) ?> あります（全拠点・精算の集計には含みません）。
        </div>
        <?php endif; ?>

        <div class="card">
            <div class="card__header">精算履歴（<?= $h($date) ?>）</div>
            <?php if (empty($closings)): ?>
                <div class="card__body text-muted" style="font-size:.85rem;">この日の精算記録はまだありません。</div>
            <?php else: ?>
            <div class="table-wrap" style="box-shadow:none;">
                <table class="table">
                    <thead><tr><th>精算日時</th><th>拠点 / レジ</th><th>担当</th><th style="text-align:right;">売上</th><th style="text-align:right;">理論現金</th><th style="text-align:right;">実査</th><th style="text-align:right;">過不足</th><th></th></tr></thead>
                    <tbody>
                    <?php foreach ($closings as $c): $d = (int)$c['difference']; ?>
                        <tr<?= (int)$c['id'] === (int)$closedId ? ' style="background:#fffbe6;"' : '' ?>>
                            <td><?= $h($c['created_at']) ?></td>
                            <td><?= $c['branch_id'] === null ? '全拠点' : $h($c['branch_name'] ?? ('#' . $c['branch_id'])) ?> / <?= !empty($c['register_no']) ? 'レジ' . sprintf('%02d', (int)$c['register_no']) : '全レジ' ?></td>
                            <td><?= $h($c['closed_by_name'] ?? '') ?></td>
                            <td style="text-align:right;"><?= $yen($c['sales_total']) ?></td>
                            <td style="text-align:right;"><?= $yen($c['expected_cash']) ?></td>
                            <td style="text-align:right;"><?= $yen($c['counted_cash']) ?></td>
                            <td style="text-align:right; font-weight:700; color:<?= $d === 0 ? '#155724' : '#c0392b' ?>;"><?= $d > 0 ? '+' : '' ?><?= $yen($d) ?></td>
                            <td><button type="button" class="btn btn-outline btn-sm" data-print-closing="<?= (int)$c['id'] ?>">印刷</button></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
            <?php endif; ?>
            <div id="closing_status" class="alert" style="display:none; margin:12px; white-space:pre-wrap;"></div>
        </div>
    </div>

    <div>
        <div class="card">
            <div class="card__header">現金の精算（<?= $h($scopeLabel) ?>）</div>
            <div class="card__body">
                <form method="POST" action="/index.php?page=pos.close" id="close_form"
                      onsubmit="return confirm('この内容で精算を記録しますか？');">
                    <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
                    <input type="hidden" name="date" value="<?= $h($date) ?>">
                    <input type="hidden" name="branch" value="<?= $branchId !== null ? (int)$branchId : '' ?>">
                    <input type="hidden" name="register" value="<?= $registerNo !== null ? (int)$registerNo : '' ?>">

                    <div class="form-group">
                        <label class="form-label" for="opening_float">釣銭準備金（営業開始時の現金）</label>
                        <input type="text" id="opening_float" name="opening_float" class="form-control" inputmode="numeric"
                               value="<?= $latest ? (int)$latest['opening_float'] : '' ?>" placeholder="例：30000">
                    </div>

                    <div class="form-label">金種別の枚数（入力すると合計を実査額にします）</div>
                    <table class="pos-den">
                        <?php foreach ($denominations as $face):
                            $cnt = $latest ? (int)($latest['denominations'][(string)$face] ?? 0) : 0; ?>
                        <tr>
                            <td><?= number_format($face) ?>円</td>
                            <td>× <input type="text" name="den[<?= (int)$face ?>]" class="form-control den" data-face="<?= (int)$face ?>" inputmode="numeric" value="<?= $cnt > 0 ? $cnt : '' ?>" style="width:80px; display:inline-block;"> 枚</td>
                            <td class="den-sub" style="text-align:right;">¥0</td>
                        </tr>
                        <?php endforeach; ?>
                    </table>

                    <div class="form-group" style="margin-top:10px;">
                        <label class="form-label" for="counted_cash">現金実査額（レジ内の現金の合計）</label>
                        <input type="text" id="counted_cash" name="counted_cash" class="form-control" inputmode="numeric"
                               value="<?= $latest ? (int)$latest['counted_cash'] : '' ?>">
                    </div>

                    <div class="pos-calc">
                        <div class="pos-trow"><span>釣銭準備金</span><span id="c_open">¥0</span></div>
                        <div class="pos-trow"><span>＋ 現金売上</span><span><?= $yen($s['cash_sales']) ?></span></div>
                        <?php if ((int)$s['refund_prev_cash'] > 0): ?>
                        <div class="pos-trow"><span>− 前日以前の会計の現金返金</span><span><?= $yen(-(int)$s['refund_prev_cash']) ?></span></div>
                        <?php endif; ?>
                        <div class="pos-trow" style="font-weight:700;"><span>＝ 理論現金残高</span><span id="c_expected">¥0</span></div>
                        <div class="pos-trow"><span>現金実査額</span><span id="c_counted">¥0</span></div>
                        <div class="pos-trow" style="font-size:1.2rem; font-weight:700;"><span>過不足</span><span id="c_diff">¥0</span></div>
                    </div>

                    <div class="form-group" style="margin-top:10px;">
                        <label class="form-label" for="close_note">備考</label>
                        <input type="text" id="close_note" name="note" class="form-control" maxlength="400" placeholder="過不足の理由など">
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%; padding:12px;">精算を記録する</button>
                    <p class="form-hint" style="margin-top:6px;">精算はやり直すことができます（記録は履歴として残り、最新のものが有効です）。</p>
                </form>
            </div>
        </div>
    </div>
</div>

<style>
.pos-daily-grid { display:grid; grid-template-columns: minmax(0,1.3fr) minmax(0,1fr); gap:16px; align-items:start; }
@media (max-width: 1000px) { .pos-daily-grid { grid-template-columns: minmax(0, 1fr); } }
.pos-den { width:100%; font-size:.85rem; border-collapse:collapse; }
.pos-den td { padding:3px 4px; }
.pos-calc { background:#f4f6f9; border-radius:4px; padding:10px 12px; margin-top:10px; }
.pos-trow { display:flex; justify-content:space-between; padding:2px 0; }
</style>

<?php include __DIR__ . '/_printer.php'; ?>
<script>
(function () {
    'use strict';
    var cashSales = <?= (int)$s['cash_sales'] - (int)$s['refund_prev_cash'] ?>; // 現金売上 − 前日以前分の現金返金
    var $ = function (id) { return document.getElementById(id); };
    function num(v) {
        v = String(v || '').replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); }).replace(/[^0-9]/g, '');
        return v === '' ? 0 : parseInt(v, 10);
    }
    function yen(n) { return (n < 0 ? '-¥' : '¥') + Math.abs(n).toLocaleString('ja-JP'); }
    function recalc() {
        var denTotal = 0;
        Array.prototype.forEach.call(document.querySelectorAll('input.den'), function (el) {
            var sub = num(el.value) * parseInt(el.getAttribute('data-face'), 10);
            denTotal += sub;
            el.closest('tr').querySelector('.den-sub').textContent = yen(sub);
        });
        if (denTotal > 0) { $('counted_cash').value = denTotal; $('counted_cash').readOnly = true; }
        else { $('counted_cash').readOnly = false; }
        var open = num($('opening_float').value), counted = num($('counted_cash').value), expected = open + cashSales, diff = counted - expected;
        $('c_open').textContent = yen(open);
        $('c_expected').textContent = yen(expected);
        $('c_counted').textContent = yen(counted);
        $('c_diff').textContent = (diff > 0 ? '+' : '') + yen(diff);
        $('c_diff').style.color = diff === 0 ? '#155724' : '#c0392b';
    }
    $('close_form').addEventListener('input', recalc);
    recalc();

    function status(msg, kind) {
        var el = $('closing_status');
        el.className = 'alert alert-' + (kind || 'info');
        el.textContent = msg; el.style.display = msg ? '' : 'none';
    }
    function printClosing(id) {
        var P = window.FuryoPrinter;
        var url = '/index.php?page=pos.closing.print&id=' + id;
        P.check().then(function (st) {
            if (!st.connected) {
                status('レシートプリンタが接続されていないため、精算レポートを別画面で表示します。', 'warning');
                window.open(P.withParam(url, { w: P.load().paper }), '_blank', 'noopener');
                return;
            }
            status('印刷しています…');
            P.printUrl(url).then(function () { status('✓ 精算レポートを印刷しました。', 'success'); },
                function (e) { status('印刷に失敗しました。' + (e && e.message ? '\n' + e.message : ''), 'danger'); });
        });
    }
    Array.prototype.forEach.call(document.querySelectorAll('[data-print-closing]'), function (b) {
        b.addEventListener('click', function () { printClosing(b.getAttribute('data-print-closing')); });
    });
}());
</script>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
