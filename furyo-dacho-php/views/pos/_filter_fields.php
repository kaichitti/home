<?php
/**
 * 取引履歴・レジ明細検索で共用する絞り込み項目
 *
 * 変数: $filters, $branches, $registers, $h, $methods
 */
?>
<div class="form-group"><label class="form-label">期間（開始）</label>
    <input type="date" name="date_from" class="form-control" value="<?= $h($filters['date_from']) ?>"></div>
<div class="form-group"><label class="form-label">期間（終了）</label>
    <input type="date" name="date_to" class="form-control" value="<?= $h($filters['date_to']) ?>"></div>
<div class="form-group"><label class="form-label">期間の指定</label>
    <select class="form-control" data-range-preset aria-label="期間の指定">
        <option value="">選択…</option>
        <option value="today">本日</option>
        <option value="yesterday">昨日</option>
        <option value="week">直近7日</option>
        <option value="month">今月</option>
        <option value="lastmonth">先月</option>
        <option value="year">今年</option>
        <option value="all">全期間</option>
    </select></div>
<script>
(function () {
    'use strict';
    var sel = document.currentScript.previousElementSibling.querySelector('[data-range-preset]');
    var form = sel.form;
    function ymd(d) { return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); }
    sel.addEventListener('change', function () {
        var t = new Date(), from = new Date(t), to = new Date(t);
        switch (sel.value) {
            case 'yesterday': from.setDate(t.getDate() - 1); to = new Date(from); break;
            case 'week': from.setDate(t.getDate() - 6); break;
            case 'month': from = new Date(t.getFullYear(), t.getMonth(), 1); break;
            case 'lastmonth': from = new Date(t.getFullYear(), t.getMonth() - 1, 1); to = new Date(t.getFullYear(), t.getMonth(), 0); break;
            case 'year': from = new Date(t.getFullYear(), 0, 1); break;
            case 'all': from = new Date(2000, 0, 1); break;
            case 'today': break;
            default: return;
        }
        form.elements.date_from.value = ymd(from);
        form.elements.date_to.value = ymd(to);
        form.submit();
    });
}());
</script>
<div class="form-group"><label class="form-label">レジ</label>
    <select name="register" class="form-control">
        <option value="">すべて</option>
        <?php foreach (array_unique(array_merge($registers ?? [], !empty($filters['register_no']) ? [(int)$filters['register_no']] : [])) as $rn): ?>
            <option value="<?= (int)$rn ?>" <?= (int)($filters['register_no'] ?? 0) === (int)$rn ? 'selected' : '' ?>>レジ<?= sprintf('%02d', (int)$rn) ?></option>
        <?php endforeach; ?>
    </select></div>
<div class="form-group"><label class="form-label">状態</label>
    <select name="status" class="form-control">
        <option value="">すべて</option>
        <option value="completed" <?= $filters['status'] === 'completed' ? 'selected' : '' ?>>完了</option>
        <option value="voided" <?= $filters['status'] === 'voided' ? 'selected' : '' ?>>取消</option>
    </select></div>
<div class="form-group"><label class="form-label">支払方法</label>
    <select name="payment_method" class="form-control">
        <option value="">すべて</option>
        <?php foreach ($methods as $k => $label): ?>
            <option value="<?= $h($k) ?>" <?= $filters['payment_method'] === $k ? 'selected' : '' ?>><?= $h($label) ?></option>
        <?php endforeach; ?>
    </select></div>
<?php if (count($branches ?? []) > 1): ?>
<div class="form-group"><label class="form-label">拠点</label>
    <select name="branch" class="form-control">
        <option value="">すべて</option>
        <?php foreach ($branches as $b): ?>
            <option value="<?= (int)$b['id'] ?>" <?= (int)($filters['branch_id'] ?? 0) === (int)$b['id'] ? 'selected' : '' ?>><?= $h($b['name']) ?></option>
        <?php endforeach; ?>
    </select></div>
<?php endif; ?>
<div class="form-group"><label class="form-label">レシート番号</label>
    <input type="text" name="receipt_no" class="form-control" maxlength="20" value="<?= $h($filters['receipt_no']) ?>" placeholder="20261023-0001"></div>
<div class="form-group"><label class="form-label">会員（番号・氏名）</label>
    <input type="text" name="member" class="form-control" maxlength="50" value="<?= $h($filters['member']) ?>" placeholder="M-0001 / 山田"></div>
<div class="form-group"><label class="form-label">担当者</label>
    <input type="text" name="cashier" class="form-control" maxlength="50" value="<?= $h($filters['cashier']) ?>"></div>
