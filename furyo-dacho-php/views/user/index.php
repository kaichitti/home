<?php
$pageTitle  = 'ユーザー管理 - 古物台帳管理システム';
$activePage = 'user';

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">ユーザー管理</h1>
    <?php if (!empty($isAdmin)): ?>
    <div class="page-header__actions">
        <a href="/index.php?page=user.create" class="btn btn-primary">ユーザー新規登録</a>
    </div>
    <?php endif; ?>
</div>


<div class="table-wrap">
    <?php if (!empty($users)): ?>
    <table class="table table--striped">
        <thead>
            <tr>
                <th>表示名</th>
                <th>メールアドレス</th>
                <th>権限</th>
                <th>所属拠点</th>
                <th>状態</th>
                <th>最終ログイン</th>
                <th>操作</th>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($users as $u): ?>
            <tr>
                <td>
                    <?= htmlspecialchars($u['display_name'] ?? '') ?>
                    <?php if (!empty($u['is_owner'])): ?>
                    <span class="badge badge-primary">オーナー</span>
                    <?php endif; ?>
                </td>
                <td><?= htmlspecialchars($u['email'] ?? '') ?></td>
                <td>
                    <?php if (($u['role'] ?? '') === 'admin'): ?>
                        <span class="badge badge-warning">管理者</span>
                    <?php else: ?>
                        <span class="badge badge-secondary">一般</span>
                    <?php endif; ?>
                </td>
                <td><?= htmlspecialchars($u['branch_name'] ?? '-') ?></td>
                <td>
                    <?php if (!empty($u['is_active'])): ?>
                        <span class="badge badge-success">有効</span>
                    <?php else: ?>
                        <span class="badge badge-secondary">無効</span>
                    <?php endif; ?>
                    <?php if (!empty($u['is_locked'])): ?>
                        <span class="badge badge-danger" title="<?= htmlspecialchars((string)$u['locked_until']) ?> までログイン不可">ロック中</span>
                    <?php endif; ?>
                    <?php if (!empty($u['must_change_password']) && !empty($u['is_active'])): ?>
                        <span class="badge badge-warning" title="次回ログイン時にパスワードの変更が必要です">PW変更待ち</span>
                    <?php endif; ?>
                </td>
                <td style="font-size:.8rem;"><?= !empty($u['last_login_at']) ? htmlspecialchars(substr((string)$u['last_login_at'], 0, 16)) : '<span class="text-muted">未ログイン</span>' ?></td>
                <td>
                    <div class="d-flex gap-8">
                        <?php if (!empty($isAdmin)): ?>
                        <a href="/index.php?page=user.edit&id=<?= (int)$u['id'] ?>"
                           class="btn btn-outline btn-sm">編集</a>
                        <?php if (!empty($u['is_locked'])): ?>
                        <form method="POST" action="/index.php?page=user.unlock" style="display:inline;">
                            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                            <input type="hidden" name="id" value="<?= (int)$u['id'] ?>">
                            <button type="submit" class="btn btn-warning btn-sm"
                                    onclick="return confirm('このユーザーのログインロックを解除しますか？')">ロック解除</button>
                        </form>
                        <?php endif; ?>
                        <?php if (!empty($u['is_active']) && (int)($u['id'] ?? 0) !== (int)($currentUserId ?? 0) && empty($u['is_owner'])): ?>
                        <form method="POST" action="/index.php?page=user.deactivate" style="display:inline;">
                            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                            <input type="hidden" name="id" value="<?= (int)$u['id'] ?>">
                            <button type="submit" class="btn btn-secondary btn-sm"
                                    onclick="return confirm('このユーザーを無効化しますか？')">
                                無効化
                            </button>
                        </form>
                        <?php endif; ?>
                        <?php if (empty($u['is_active'])): ?>
                        <form method="POST" action="/index.php?page=user.activate" style="display:inline;">
                            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                            <input type="hidden" name="id" value="<?= (int)$u['id'] ?>">
                            <button type="submit" class="btn btn-outline btn-sm"
                                    onclick="return confirm('このユーザーを有効にしますか？\n（再びログインできるようになります）')">
                                有効化
                            </button>
                        </form>
                        <?php endif; ?>
                        <?php if ((int)($u['id'] ?? 0) !== (int)($currentUserId ?? 0) && empty($u['is_owner'])): ?>
                        <form method="POST" action="/index.php?page=user.delete" style="display:inline;">
                            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                            <input type="hidden" name="id" value="<?= (int)$u['id'] ?>">
                            <button type="submit" class="btn btn-danger btn-sm"
                                    onclick="return confirm('このユーザーを完全に削除しますか？\nこの操作は取り消せません。\n（台帳の登録記録があるユーザーは削除できません）')">
                                削除
                            </button>
                        </form>
                        <?php endif; ?>
                        <?php else: ?>
                        <a href="/index.php?page=user.edit&id=<?= (int)$u['id'] ?>"
                           class="btn btn-outline btn-sm">編集</a>
                        <?php endif; ?>
                    </div>
                </td>
            </tr>
            <?php endforeach; ?>
        </tbody>
    </table>
    <?php else: ?>
    <div class="empty-state" style="background:#fff;">
        <div class="empty-state__icon">&#128100;</div>
        <div class="empty-state__text">ユーザーが登録されていません</div>
    </div>
    <?php endif; ?>
</div>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
