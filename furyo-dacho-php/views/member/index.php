<?php
$pageTitle  = '会員管理 - 古物台帳管理システム';
$activePage = 'member';

$typeLabels = ['individual' => '個人', 'corporate' => '法人'];

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">会員管理</h1>
    <a href="/index.php?page=member.create" class="btn btn-primary">+ 新規会員登録</a>
</div>

<div class="card">
    <div class="card__body">
        <form method="GET" action="/index.php" style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px;">
            <input type="hidden" name="page" value="member">
            <input type="text" name="keyword" class="form-control" style="max-width:300px;"
                   placeholder="会員番号・氏名で検索"
                   value="<?= htmlspecialchars($keyword ?? '') ?>">
            <button type="submit" class="btn btn-secondary">検索</button>
        </form>

        <?php if (!empty($members)): ?>
        <div class="table-wrap">
            <table class="table table--striped">
                <thead>
                    <tr>
                        <th>会員番号</th>
                        <th>区分</th>
                        <th>氏名／名称</th>
                        <th>電話番号</th>
                        <th>取引アカウント</th>
                        <th style="text-align:right;">POS購入</th>
                        <th style="width:190px;">操作</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ($members as $m): ?>
                    <tr>
                        <td><?= htmlspecialchars($m['member_code']) ?></td>
                        <td>
                            <span class="badge <?= $m['counterpart_type'] === 'corporate' ? 'badge-secondary' : 'badge-primary' ?>">
                                <?= $typeLabels[$m['counterpart_type']] ?? $m['counterpart_type'] ?>
                            </span>
                        </td>
                        <td><a href="/index.php?page=member.show&id=<?= (int)$m['id'] ?>"><?= htmlspecialchars($m['name']) ?></a><?php if (!empty($m['contact_name'])): ?><span class="text-muted" style="font-size:.8rem;">（担当: <?= htmlspecialchars($m['contact_name']) ?>）</span><?php endif; ?></td>
                        <td><?= htmlspecialchars($m['phone'] ?? '') ?></td>
                        <td><?= htmlspecialchars($m['account'] ?? '') ?></td>
                        <?php $st = $stats[(int)$m['id']] ?? null; ?>
                        <td style="text-align:right; font-size:.8rem;">
                            <?php if ($st): ?><?= (int)$st['count'] ?>回 ¥<?= number_format((int)$st['total']) ?><br><span class="text-muted">最終 <?= htmlspecialchars(substr((string)$st['last_at'], 0, 10)) ?></span>
                            <?php else: ?><span class="text-muted">-</span><?php endif; ?>
                        </td>
                        <td>
                            <a href="/index.php?page=member.show&id=<?= (int)$m['id'] ?>" class="btn btn-secondary btn-sm">詳細</a>
                            <a href="/index.php?page=member.edit&id=<?= (int)$m['id'] ?>" class="btn btn-secondary btn-sm">編集</a>
                            <?php if (!empty($isAdmin)): ?>
                            <form method="POST" action="/index.php?page=member.delete" style="display:inline;">
                                <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                                <input type="hidden" name="id" value="<?= (int)$m['id'] ?>">
                                <?php // 会員番号は自由入力のため、JavaScript の文字列に直接埋め込まない（以前は ' を含む番号でスクリプトが実行できた） ?>
                                <button type="submit" class="btn btn-secondary btn-sm"
                                        data-confirm="<?= htmlspecialchars('会員「' . $m['member_code'] . '」を削除しますか？' . "\n" . '（過去の台帳記録・会計の記録は変わりません）', ENT_QUOTES, 'UTF-8') ?>"
                                        onclick="return confirm(this.getAttribute('data-confirm'))">削除</button>
                            </form>
                            <?php endif; ?>
                        </td>
                    </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <p class="text-muted" style="font-size:.8rem; margin-top:8px;">全 <?= (int)($total ?? 0) ?> 件</p>
        <?php if (($totalPages ?? 1) > 1): ?>
        <div style="display:flex; gap:6px; margin-top:8px;">
            <?php for ($i = 1; $i <= $totalPages; $i++): ?>
                <?php if ($i === ($page ?? 1)): ?>
                    <span class="btn btn-primary btn-sm"><?= $i ?></span>
                <?php else: ?>
                    <a class="btn btn-secondary btn-sm" href="/index.php?page=member&p=<?= $i ?>&keyword=<?= urlencode($keyword ?? '') ?>"><?= $i ?></a>
                <?php endif; ?>
            <?php endfor; ?>
        </div>
        <?php endif; ?>
        <?php else: ?>
        <p class="text-muted">会員はまだ登録されていません。「+ 新規会員登録」から登録すると、台帳登録時に会員番号で相手方情報を引用できます。</p>
        <?php endif; ?>
    </div>
</div>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
