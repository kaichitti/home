<?php
$pageTitle  = '拠点管理 - 古物台帳管理システム';
$activePage = 'branch';

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">拠点管理</h1>
    <?php if (!empty($isAdmin)): ?>
    <div class="page-header__actions">
        <a href="/index.php?page=branch.create" class="btn btn-primary">拠点新規登録</a>
    </div>
    <?php endif; ?>
</div>

<?php if (!empty($flashSuccess)): ?>
<div class="alert alert-success"><?= htmlspecialchars($flashSuccess) ?></div>
<?php endif; ?>
<?php if (!empty($flashError)): ?>
<div class="alert alert-danger"><?= htmlspecialchars($flashError) ?></div>
<?php endif; ?>

<div class="table-wrap">
    <?php if (!empty($branches)): ?>
    <table class="table table--striped">
        <thead>
            <tr>
                <th>拠点名</th>
                <th>ログインコード</th>
                <th>住所</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($branches as $b): ?>
            <tr>
                <td>
                    <?= htmlspecialchars($b['name'] ?? '') ?>
                    <?php if (!empty($b['is_main'])): ?>
                    <span class="badge badge-primary">主拠点</span>
                    <?php endif; ?>
                </td>
                <td>
                    <?php if (!empty($b['login_code'])): ?>
                        <code><?= htmlspecialchars($b['login_code']) ?></code>
                    <?php else: ?>
                        <span class="text-muted" style="font-size:.8rem;">（テナントコード）</span>
                    <?php endif; ?>
                </td>
                <td><?= htmlspecialchars($b['address'] ?? '-') ?></td>
                <td>
                    <div class="d-flex gap-8">
                        <a href="/index.php?page=branch.edit&id=<?= (int)$b['id'] ?>"
                           class="btn btn-outline btn-sm">編集</a>
                        <?php if (!empty($isAdmin) && empty($b['is_main'])): ?>
                        <form method="POST" action="/index.php?page=branch.delete" style="display:inline;">
                            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                            <input type="hidden" name="id" value="<?= (int)$b['id'] ?>">
                            <button type="submit" class="btn btn-danger btn-sm"
                                    onclick="return confirm('この拠点を削除しますか？')">
                                削除
                            </button>
                        </form>
                        <?php elseif (!empty($b['is_main'])): ?>
                        <span class="text-muted" style="font-size:.75rem; align-self:center;">削除不可（名称変更のみ）</span>
                        <?php endif; ?>
                    </div>
                </td>
            </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    <?php else: ?>
    <div class="empty-state" style="background:#fff;">
        <div class="empty-state__icon">&#127968;</div>
        <div class="empty-state__text">拠点が登録されていません</div>
    </div>
    <?php endif; ?>
</div>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
