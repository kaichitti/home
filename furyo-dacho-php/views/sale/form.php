<?php
/**
 * 販売記録の編集フォーム（管理者専用）
 *
 * 変数:
 *  - $sale       : 編集対象の販売記録
 *  - $record     : 対象の台帳（仕入記録）
 *  - $maxQty     : この記録で設定できる最大個数（他の販売分を除いた在庫）
 *  - $csrf_token
 */
$pageTitle  = '販売記録の編集 - 古物台帳管理システム';
$activePage = 'ledger';

$ledgerId = (int)$sale['ledger_id'];

// datetime-local 用に整形（"YYYY-MM-DDTHH:MM"）
$soldAtLocal = '';
if (!empty($sale['sold_at'])) {
    $ts = strtotime($sale['sold_at']);
    if ($ts !== false) {
        $soldAtLocal = date('Y-m-d\TH:i', $ts);
    }
}

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">販売記録の編集</h1>
    <div class="page-header__actions">
        <a href="/index.php?page=ledger.show&id=<?= $ledgerId ?>" class="btn btn-secondary">台帳へ戻る</a>
    </div>
</div>

<div class="card">
    <div class="card__header">対象商品</div>
    <div class="card__body">
        <div style="font-weight:700; font-size:1.05rem;"><?= htmlspecialchars($record['item_name'] ?? '') ?></div>
        <div class="text-muted" style="font-size:.8rem; margin-top:4px;">
            台帳 #<?= $ledgerId ?>
            <?php if (!empty($record['serial_number'])): ?>
                / SN: <?= htmlspecialchars($record['serial_number']) ?>
            <?php endif; ?>
            / 仕入数量: <?= (int)($record['quantity'] ?? 0) ?> 点
        </div>
    </div>
</div>

<div class="card">
    <div class="card__header">販売内容の修正</div>
    <div class="card__body">
        <form method="POST" action="/index.php?page=ledger.sale.update">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
            <input type="hidden" name="sale_id" value="<?= (int)$sale['id'] ?>">

            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="quantity">
                        販売個数 <span class="required">*</span>
                    </label>
                    <input type="number" id="quantity" name="quantity" class="form-control"
                           value="<?= (int)$sale['quantity'] ?>" min="1" max="<?= (int)$maxQty ?>" required>
                    <div class="form-hint">この記録で設定できる最大: <?= (int)$maxQty ?> 点（他の販売記録分を除いた在庫）</div>
                </div>

                <div class="form-group">
                    <label class="form-label" for="sale_amount">販売金額（円・合計）</label>
                    <input type="text" id="sale_amount" name="sale_amount" class="form-control"
                           inputmode="numeric"
                           value="<?= $sale['sale_amount'] !== null ? (int)$sale['sale_amount'] : '' ?>"
                           placeholder="例：15000">
                </div>
            </div>

            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="sold_at">販売日時</label>
                    <input type="datetime-local" id="sold_at" name="sold_at" class="form-control"
                           value="<?= htmlspecialchars($soldAtLocal) ?>">
                </div>

                <div class="form-group">
                    <label class="form-label" for="member_code">販売先の会員番号（任意）</label>
                    <input type="text" id="member_code" name="member_code" class="form-control"
                           value="<?= htmlspecialchars($sale['member_code'] ?? '') ?>"
                           maxlength="50" placeholder="例：M-0001">
                    <div class="form-hint">会員管理に登録済みの番号のみ設定できます。</div>
                </div>
            </div>

            <div class="form-group">
                <label class="form-label" for="note">備考</label>
                <input type="text" id="note" name="note" class="form-control"
                       value="<?= htmlspecialchars($sale['note'] ?? '') ?>"
                       maxlength="512" placeholder="販売先・チャネル等（任意）">
            </div>

            <div class="form-actions">
                <button type="submit" class="btn btn-primary">修正を保存</button>
                <a href="/index.php?page=ledger.show&id=<?= $ledgerId ?>" class="btn btn-secondary">キャンセル</a>
            </div>
        </form>
    </div>
</div>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
