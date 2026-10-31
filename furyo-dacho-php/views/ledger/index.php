<?php
$approvalMode = !empty($approvalMode);
$pageTitle  = ($approvalMode ? '承認待ち台帳' : '台帳一覧') . ' - 古物台帳管理システム';
$activePage = $approvalMode ? 'ledger.approval' : 'ledger';

// $itemTypes, $transactionTypes はコントローラーから渡される（key=>label形式）

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title"><?= $approvalMode ? '承認待ち台帳' : '古物台帳 一覧' ?></h1>
    <div class="page-header__actions">
        <?php if ($approvalMode): ?>
        <a href="/index.php?page=ledger" class="btn btn-secondary">台帳一覧へ</a>
        <?php else: ?>
        <a href="/index.php?page=ledger.create" class="btn btn-primary">新規登録</a>
        <?php endif; ?>
    </div>
</div>

<?php if ($approvalMode): ?>
<div class="alert alert-danger" style="font-size:.85rem;">
    &#9888; 本人確認情報が未登録かつ相手方が未認証（本人確認済み会員に紐付いていない）の売買記録です。
    各行を開いて内容を確認し、詳細画面の「承認する」ボタンで承認してください。
</div>
<?php endif; ?>

<!-- 検索パネル -->
<?php if (!$approvalMode): ?>
<div class="search-panel">
    <?php
    // 検索条件が1つでも指定されていれば検索パネルを開いた状態で表示する
    // （以前は条件の有無に関わらず aria-expanded="true" だったため、閉じた状態なのに
    //   矢印が「開」を示し、1回目のクリックでは何も起きなかった）
    $searchKeys = $search ?? [];
    unset($searchKeys['approval_status']);
    $hasSearch = !empty(array_filter($searchKeys, static fn ($v) => $v !== null && $v !== '' && !is_array($v)));
    ?>
    <button type="button" class="search-panel__toggle" aria-expanded="<?= $hasSearch ? 'true' : 'false' ?>">
        <span>絞り込み検索</span>
        <span class="search-panel__chevron">&#9660;</span>
    </button>
    <div class="search-panel__body <?= $hasSearch ? '' : 'collapsed' ?>">
        <form method="GET" action="/index.php" id="searchForm">
            <input type="hidden" name="page" value="ledger">
            <div style="margin-top: 16px;">
                <div class="form-row form-row-3">
                    <div class="form-group">
                        <label class="form-label">取引年月日（From）</label>
                        <input type="date" name="date_from" class="form-control"
                            value="<?= htmlspecialchars($search['date_from'] ?? '') ?>">
                    </div>
                    <div class="form-group">
                        <label class="form-label">取引年月日（To）</label>
                        <input type="date" name="date_to" class="form-control"
                            value="<?= htmlspecialchars($search['date_to'] ?? '') ?>">
                    </div>
                    <div class="form-group">
                        <label class="form-label">古物の種類</label>
                        <select name="item_category" class="form-control">
                            <option value="">-- すべて --</option>
                            <?php foreach ($itemTypes as $val => $label): ?>
                            <option value="<?= htmlspecialchars($val) ?>"
                                <?= ($search['item_category'] ?? '') === $val ? 'selected' : '' ?>>
                                <?= htmlspecialchars($label) ?>
                            </option>
                            <?php endforeach; ?>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">取引種別</label>
                        <select name="transaction_type" class="form-control">
                            <option value="">-- すべて --</option>
                            <?php foreach ($transactionTypes as $val => $label): ?>
                            <option value="<?= htmlspecialchars($val) ?>"
                                <?= ($search['transaction_type'] ?? '') === $val ? 'selected' : '' ?>>
                                <?= htmlspecialchars($label) ?>
                            </option>
                            <?php endforeach; ?>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">品目</label>
                        <input type="text" name="item_name" class="form-control"
                            placeholder="品目名で検索"
                            value="<?= htmlspecialchars($search['item_name'] ?? '') ?>">
                    </div>
                    <div class="form-group">
                        <label class="form-label">相手方氏名</label>
                        <input type="text" name="counterpart_name" class="form-control"
                            placeholder="氏名で検索"
                            value="<?= htmlspecialchars($search['counterpart_name'] ?? '') ?>">
                    </div>
                    <div class="form-group">
                        <label class="form-label">シリアル番号</label>
                        <input type="text" name="serial_number" class="form-control"
                            placeholder="シリアル番号で検索（部分一致）"
                            value="<?= htmlspecialchars($search['serial_number'] ?? '') ?>">
                    </div>
                    <div class="form-group">
                        <label class="form-label">登録者</label>
                        <select name="registered_by" class="form-control">
                            <option value="">-- すべて --</option>
                            <?php if (!empty($users)): ?>
                            <?php foreach ($users as $u): ?>
                            <option value="<?= (int)$u['id'] ?>"
                                <?= ($search['registered_by'] ?? '') == $u['id'] ? 'selected' : '' ?>>
                                <?= htmlspecialchars($u['display_name']) ?>
                            </option>
                            <?php endforeach; ?>
                            <?php endif; ?>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">拠点</label>
                        <select name="branch_id" class="form-control">
                            <option value="">-- すべて --</option>
                            <?php if (!empty($branches)): ?>
                            <?php foreach ($branches as $b): ?>
                            <option value="<?= (int)$b['id'] ?>"
                                <?= ($search['branch_id'] ?? '') == $b['id'] ? 'selected' : '' ?>>
                                <?= htmlspecialchars($b['name']) ?>
                            </option>
                            <?php endforeach; ?>
                            <?php endif; ?>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">年度</label>
                        <select name="fiscal_year" class="form-control">
                            <option value="">-- すべて --</option>
                            <?php
                            // 年度は4月始まり（1〜3月は前年が「今年度」）
                            $currentYear = (int)date('n') >= 4 ? (int)date('Y') : (int)date('Y') - 1;
                            $oldestYear  = $currentYear - 10;
                            foreach (($years ?? []) as $yy) { $oldestYear = min($oldestYear, (int)$yy); }
                            for ($y = $currentYear; $y >= $oldestYear; $y--):
                            ?>
                            <option value="<?= $y ?>"
                                <?= ($search['fiscal_year'] ?? '') == $y ? 'selected' : '' ?>>
                                <?= $y ?>年度
                            </option>
                            <?php endfor; ?>
                        </select>
                    </div>
                </div>
            </div>
            <div class="search-panel__actions">
                <button type="submit" class="btn btn-primary">検索</button>
                <a href="/index.php?page=ledger" class="btn btn-outline">クリア</a>
            </div>
        </form>
    </div>
</div>

<?php endif; ?>

<!-- 件数表示 -->
<div style="margin-bottom: 12px; font-size: 0.85rem; color: #6c757d;">
    全 <strong style="color: #212529;"><?= (int)($total ?? 0) ?></strong> 件
    <?php if ((int)($total ?? 0) > 0 && isset($perPage, $currentPage)): ?>
    （<?= ((int)$currentPage - 1) * (int)$perPage + 1 ?>〜<?= min((int)$currentPage * (int)$perPage, (int)$total) ?> 件表示）
    <?php endif; ?>
</div>

<!-- テーブル -->
<div class="table-wrap">
    <?php if (!empty($ledgers)): ?>
    <table class="table table--striped">
        <thead>
            <tr>
                <th>台帳番号</th>
                <th>取引年月日</th>
                <th>品目</th>
                <th>古物の種類</th>
                <th>取引種別</th>
                <th>相手方氏名</th>
                <th>取引金額</th>
                <th>登録者</th>
                <th>拠点</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($ledgers as $row): ?>
            <tr>
                <td>
                    <span style="font-family: monospace; font-size: 0.8rem; color: #6c757d;">
                        #<?= (int)$row['id'] ?>
                    </span>
                </td>
                <td><?= htmlspecialchars($row['transaction_date'] ?? '') ?></td>
                <td style="white-space: normal; min-width: 100px;">
                    <?= htmlspecialchars($row['item_name'] ?? '') ?>
                    <?php if (($row['approval_status'] ?? 'none') === 'pending'): ?>
                    <span class="badge badge-danger">承認待ち</span>
                    <?php endif; ?>
                    <?php
                    $rowRemaining = (int)($row['quantity'] ?? 1) - (int)($row['sold_quantity'] ?? 0);
                    if (($row['sold_quantity'] ?? 0) > 0):
                    ?>
                        <?php if ($rowRemaining <= 0): ?>
                        <span class="badge badge-secondary">売切</span>
                        <?php else: ?>
                        <span class="badge badge-success">残<?= $rowRemaining ?></span>
                        <?php endif; ?>
                    <?php endif; ?>
                </td>
                <td>
                    <span class="badge badge-primary"><?= htmlspecialchars(\FuryoDacho\Models\ItemCategory::label($row['item_category'] ?? '', $row['item_category_note'] ?? null)) ?></span>
                </td>
                <td><?= htmlspecialchars($transactionTypes[$row['transaction_type'] ?? ''] ?? $row['transaction_type'] ?? '') ?></td>
                <td><?= htmlspecialchars($row['counterpart_name'] ?? '') ?></td>
                <td style="text-align: right;">
                    <?php if (isset($row['transaction_amount']) && $row['transaction_amount'] !== ''): ?>
                        &#165;<?= number_format((float)$row['transaction_amount']) ?>
                    <?php else: ?>
                        -
                    <?php endif; ?>
                </td>
                <td><?= htmlspecialchars($row['registered_by_name'] ?? '') ?></td>
                <td><?= htmlspecialchars($row['branch_name'] ?? '') ?></td>
                <td>
                    <a href="/index.php?page=ledger.show&id=<?= (int)$row['id'] ?>" class="btn btn-accent btn-sm">詳細</a>
                </td>
            </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    <?php elseif ($approvalMode): ?>
    <div class="empty-state" style="background:#fff;">
        <div class="empty-state__icon" style="color:#27ae60;">&#10003;</div>
        <div class="empty-state__text">現在、承認待ちの台帳はありません</div>
        <p class="text-muted" style="font-size:.8rem; margin-top:8px;">
            本人確認情報が未登録かつ未認証の相手方で売買記録が登録されると、ここに表示されます。
        </p>
        <a href="/index.php?page=ledger" class="btn btn-secondary" style="margin-top:12px;">台帳一覧へ戻る</a>
    </div>
    <?php else: ?>
    <div class="empty-state" style="background:#fff;">
        <div class="empty-state__icon">&#128196;</div>
        <div class="empty-state__text">条件に一致する台帳データがありません</div>
    </div>
    <?php endif; ?>
</div>

<!-- ページネーション -->
<?php if (!empty($totalPages) && (int)$totalPages > 1): ?>
<div class="pagination">
    <?php
    $cp = (int)($currentPage ?? 1);
    $tp = (int)$totalPages;
    $baseUrl = '/index.php?page=ledger'
        . ($approvalMode ? '&approval=pending' : '')
        . (!empty($search) ? '&' . http_build_query(array_filter($search)) : '');
    ?>
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

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
