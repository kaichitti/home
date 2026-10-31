<?php
/**
 * テナント詳細（基本情報・利用状況・利用者一覧・パスワード再設定・停止/再開/削除）
 * 変数: $tenant, $users, $stats, $csrf_token
 */
require_once __DIR__ . '/../_tenant_helpers.php';
$adminTitle = 'テナント詳細';
$users = $users ?? [];
$stats = $stats ?? [];
$st    = (string)($tenant['status'] ?? '');
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
?>
<div class="page-header">
    <h1 class="page-header__title"><?= $h($tenant['name']) ?> <?= furyo_admin_status_badge($st) ?></h1>
    <div class="page-header__actions">
        <a href="/admin/index.php?page=tenant" class="btn btn-outline">&#8592; 一覧へ戻る</a>
        <?php if ($st !== 'deleted'): ?>
        <a href="/admin/index.php?page=tenant.edit&amp;id=<?= (int)$tenant['id'] ?>" class="btn btn-accent">編集</a>
        <?php endif; ?>
        <?php if ($st === 'active'): ?>
        <form method="POST" action="/admin/index.php?page=tenant.suspend" style="margin:0;">
            <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
            <input type="hidden" name="id" value="<?= (int)$tenant['id'] ?>">
            <input type="hidden" name="back" value="show">
            <button type="submit" class="btn btn-warning"
                    onclick="return confirm('このテナントを停止しますか？\n利用者はログインできなくなります（データは保持されます）。')">停止</button>
        </form>
        <?php elseif ($st === 'suspended'): ?>
        <form method="POST" action="/admin/index.php?page=tenant.resume" style="margin:0;">
            <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
            <input type="hidden" name="id" value="<?= (int)$tenant['id'] ?>">
            <input type="hidden" name="back" value="show">
            <button type="submit" class="btn btn-success" onclick="return confirm('このテナントを再開しますか？')">再開</button>
        </form>
        <?php endif; ?>
    </div>
</div>

<?php if ($st === 'suspended'): ?>
<div class="alert alert-warning"><span>このテナントは停止中です。利用者はログインできません。</span></div>
<?php elseif ($st === 'deleted'): ?>
<div class="alert alert-info"><span>このテナントは削除済みです（全利用者が無効化されています。台帳データはDBに保持されています）。</span></div>
<?php endif; ?>

<div class="stat-cards">
    <div class="stat-card"><div class="stat-card__label">利用者（有効）</div><div class="stat-card__value"><?= count(array_filter($users, static fn ($u) => !empty($u['is_active']))) ?>人</div></div>
    <div class="stat-card stat-card--accent"><div class="stat-card__label">台帳件数</div><div class="stat-card__value"><?= number_format((int)($stats['ledger_count'] ?? 0)) ?>件</div></div>
    <div class="stat-card stat-card--success"><div class="stat-card__label">拠点数</div><div class="stat-card__value"><?= (int)($stats['branch_count'] ?? 0) ?></div></div>
    <div class="stat-card stat-card--warning"><div class="stat-card__label">会員数</div><div class="stat-card__value"><?= number_format((int)($stats['member_count'] ?? 0)) ?></div></div>
</div>

<div class="card">
    <div class="card__header">基本情報</div>
    <table class="detail-table">
        <tr><th>ID</th><td><?= (int)$tenant['id'] ?></td></tr>
        <tr><th>テナントコード（ログイン時に入力）</th><td><code><?= $h($tenant['code']) ?></code></td></tr>
        <tr><th>テナント名</th><td><?= $h($tenant['name']) ?></td></tr>
        <tr><th>種別</th><td><?= $h(furyo_admin_type_label((string)$tenant['type'])) ?></td></tr>
        <tr><th>状態</th><td><?= furyo_admin_status_badge($st) ?></td></tr>
        <tr><th>作成日時</th><td><?= $h($tenant['created_at']) ?></td></tr>
        <tr><th>更新日時</th><td><?= $h($tenant['updated_at']) ?></td></tr>
    </table>
</div>

<div class="card">
    <div class="card__header">利用者一覧</div>
    <?php if (empty($users)): ?>
        <div class="empty-state">利用者が登録されていません。</div>
    <?php else: ?>
    <div class="table-wrap">
        <table class="table">
            <thead>
                <tr>
                    <th>表示名</th>
                    <th>メールアドレス（ログインID）</th>
                    <th>権限</th>
                    <th>状態</th>
                    <th>最終ログイン</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
            <?php foreach ($users as $user): ?>
                <tr>
                    <td>
                        <?= $h($user['display_name']) ?>
                        <?php if (!empty($user['is_owner'])): ?><span class="badge badge-primary">オーナー</span><?php endif; ?>
                    </td>
                    <td><?= $h($user['email']) ?></td>
                    <td class="nowrap"><?= ($user['role'] ?? '') === 'admin' ? '<span class="badge badge-warning">管理者</span>' : '<span class="badge badge-secondary">一般</span>' ?></td>
                    <td class="nowrap">
                        <?= !empty($user['is_active']) ? '<span class="badge badge-success">有効</span>' : '<span class="badge badge-secondary">無効</span>' ?>
                        <?php if (!empty($user['is_locked'])): ?><span class="badge badge-danger" title="<?= $h($user['locked_until']) ?> まで">ロック中</span><?php endif; ?>
                        <?php if (!empty($user['must_change_password']) && !empty($user['is_active'])): ?><span class="badge badge-warning">PW変更待ち</span><?php endif; ?>
                    </td>
                    <td class="nowrap" style="font-size:.8rem;"><?= !empty($user['last_login_at']) ? $h(substr((string)$user['last_login_at'], 0, 16)) : '<span class="text-muted">未ログイン</span>' ?></td>
                    <td>
                        <?php if ($st !== 'deleted'): ?>
                        <div class="actions">
                            <?php if (!empty($user['is_locked'])): ?>
                            <form method="POST" action="/admin/index.php?page=tenant.user.unlock">
                                <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
                                <input type="hidden" name="tenant_id" value="<?= (int)$tenant['id'] ?>">
                                <input type="hidden" name="user_id" value="<?= (int)$user['id'] ?>">
                                <button type="submit" class="btn btn-warning btn-sm" onclick="return confirm('この利用者のログインロックを解除しますか？')">ロック解除</button>
                            </form>
                            <?php endif; ?>
                            <button type="button" class="btn btn-outline btn-sm"
                                    onclick="var r=document.getElementById('pwreset-<?= (int)$user['id'] ?>'); r.hidden=!r.hidden; if(!r.hidden){r.querySelector('input[type=password]').focus();}">パスワード再設定</button>
                        </div>
                        <?php else: ?>
                        <span class="text-muted" style="font-size:.8rem;">-</span>
                        <?php endif; ?>
                    </td>
                </tr>
                <?php if ($st !== 'deleted'): ?>
                <tr id="pwreset-<?= (int)$user['id'] ?>" hidden>
                    <td colspan="6" style="background:#f8f9fb;">
                        <form method="POST" action="/admin/index.php?page=tenant.user.password" autocomplete="off"
                              style="display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end;"
                              onsubmit="return confirm('この利用者のパスワードを再設定しますか？\n（今のパスワードではログインできなくなります）');">
                            <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
                            <input type="hidden" name="tenant_id" value="<?= (int)$tenant['id'] ?>">
                            <input type="hidden" name="user_id" value="<?= (int)$user['id'] ?>">
                            <div>
                                <label class="form-label" style="font-size:.78rem;">仮パスワード（8文字以上・英字と数字）</label>
                                <input type="password" name="new_password" class="form-control" minlength="8" maxlength="72" required autocomplete="new-password" style="width:220px;">
                            </div>
                            <div>
                                <label class="form-label" style="font-size:.78rem;">仮パスワード（確認）</label>
                                <input type="password" name="new_password_confirm" class="form-control" minlength="8" maxlength="72" required autocomplete="new-password" style="width:220px;">
                            </div>
                            <button type="submit" class="btn btn-warning">再設定する</button>
                            <span class="form-hint" style="flex-basis:100%;">ロックも解除されます。次回ログイン時に本人のパスワードへの変更が求められます。</span>
                        </form>
                    </td>
                </tr>
                <?php endif; ?>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
    <?php endif; ?>
</div>

<?php if ($st !== 'deleted'): ?>
<div class="card" style="border:1px solid #f1c4c0;">
    <div class="card__header" style="color:#c0392b;">テナントの削除</div>
    <div class="card__body">
        <p style="font-size:.875rem; margin-bottom:12px;">
            削除すると、このテナントの全利用者が無効化され、ログインできなくなります。台帳などのデータはDBに保持されます（画面からは元に戻せません）。
            一時的に利用を止める場合は「停止」を使用してください。
        </p>
        <form method="POST" action="/admin/index.php?page=tenant.delete" style="display:flex; gap:8px; flex-wrap:wrap; align-items:flex-end;"
              onsubmit="return confirm('本当にこのテナントを削除しますか？\nこの操作は画面から元に戻せません。');">
            <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
            <input type="hidden" name="id" value="<?= (int)$tenant['id'] ?>">
            <div>
                <label class="form-label" for="confirm_code" style="font-size:.8rem;">確認のためテナントコード「<?= $h($tenant['code']) ?>」を入力</label>
                <input type="text" id="confirm_code" name="confirm_code" class="form-control" required autocomplete="off" style="width:240px;">
            </div>
            <button type="submit" class="btn btn-danger">テナントを削除する</button>
        </form>
    </div>
</div>
<?php endif; ?>
