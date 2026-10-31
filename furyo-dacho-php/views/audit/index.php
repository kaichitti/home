<?php
$pageTitle  = '監査ログ - 古物台帳管理システム';
$activePage = 'audit';

$actionLabels = [
    'login'        => 'ログイン',
    'create'       => '登録',
    'edit'         => '編集',
    'delete'       => '削除',
    'export'       => '出力',
    'alert_action' => 'アラート処理',
];

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">監査ログ</h1>
</div>

<div class="table-wrap">
    <?php if (!empty($logs)): ?>
    <table class="table table--striped">
        <thead>
            <tr>
                <th>操作日時</th>
                <th>操作者</th>
                <th>所属拠点</th>
                <th>操作種別</th>
                <th>対象ID</th>
                <th>IPアドレス</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($logs as $log): ?>
            <?php $action = $log['action_type'] ?? ''; ?>
            <tr>
                <td style="white-space: nowrap;"><?= htmlspecialchars($log['created_at'] ?? '') ?></td>
                <td><?= htmlspecialchars($log['user_display_name'] ?? '-') ?></td>
                <td><?= htmlspecialchars($log['branch_name'] ?? '-') ?></td>
                <td>
                    <?php
                    $label  = $actionLabels[$action] ?? $action; // 出力時にエスケープする（二重エスケープしない）
                    $badgeClass = 'badge-secondary';
                    if ($action === 'delete')       $badgeClass = 'badge-danger';
                    elseif ($action === 'create')   $badgeClass = 'badge-success';
                    elseif ($action === 'edit')     $badgeClass = 'badge-warning';
                    elseif ($action === 'login')    $badgeClass = 'badge-primary';
                    elseif ($action === 'export')   $badgeClass = 'badge-primary';
                    ?>
                    <span class="badge <?= $badgeClass ?>"><?= htmlspecialchars($label) ?></span>
                </td>
                <td>
                    <?php
                    // 対象の種類（after/before の kind）に応じてリンク先を決める。
                    // 以前は種類に関係なく台帳詳細へリンクしており、販売記録のIDで
                    // 別の台帳が開く（または404になる）不具合があった。
                    $vals = [];
                    foreach (['after_value', 'before_value'] as $vk) {
                        $dv = json_decode((string)($log[$vk] ?? ''), true);
                        if (is_array($dv)) { $vals += $dv; }
                    }
                    $kind = (string)($vals['kind'] ?? '');
                    $kindLabels = [
                        'sale' => '販売記録', 'pos_transaction' => 'POS取引', 'pos_void' => 'POS取引',
                        'pos_print' => 'POS取引', 'pos_closing' => 'レジ精算', 'pos_settings' => 'POS設定',
                        'pos_csv' => 'POS売上CSV', 'member' => '会員', 'user' => 'ユーザー',
                    ];
                    $tid  = (int)($log['target_id'] ?? 0);
                    $link = null;
                    if ($kind === 'sale' && !empty($vals['ledger_id'])) {
                        $link = '/index.php?page=ledger.show&id=' . (int)$vals['ledger_id'];
                    } elseif (in_array($kind, ['pos_transaction', 'pos_void', 'pos_print'], true) && $tid > 0) {
                        $link = '/index.php?page=pos.show&id=' . $tid;
                    } elseif ($kind === '' && $tid > 0 && in_array($action, ['create', 'edit', 'delete'], true)) {
                        $link = '/index.php?page=ledger.show&id=' . $tid;
                    }
                    ?>
                    <?php if ($kind !== ''): ?>
                        <span class="text-muted" style="font-size:.75rem;"><?= htmlspecialchars($kindLabels[$kind] ?? $kind) ?></span>
                    <?php endif; ?>
                    <?php if ($tid > 0): ?>
                        <?php if ($link !== null): ?>
                            <a href="<?= htmlspecialchars($link) ?>">#<?= $tid ?></a>
                        <?php else: ?>
                            #<?= $tid ?>
                        <?php endif; ?>
                    <?php elseif ($kind === ''): ?>
                        -
                    <?php endif; ?>
                </td>
                <td style="font-family: monospace; font-size: 0.8rem;">
                    <?= htmlspecialchars($log['ip_address'] ?? '-') ?>
                </td>
            </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    <?php else: ?>
    <div class="empty-state" style="background:#fff;">
        <div class="empty-state__icon">&#128196;</div>
        <div class="empty-state__text">ログデータがありません</div>
    </div>
    <?php endif; ?>
</div>

<!-- ページネーション -->
<?php if (!empty($pagination) && (int)($pagination['total_pages'] ?? 0) > 1): ?>
<?php
$cp      = (int)($pagination['current_page'] ?? 1);
$tp      = (int)$pagination['total_pages'];
// 絞り込み条件（操作種別・操作者・期間）を引き継ぐ（以前はページを送ると条件が外れていた）
$baseUrl = '/index.php?page=audit' . (!empty($filters) && array_filter($filters) ? '&' . http_build_query(array_filter($filters)) : '');
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

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
