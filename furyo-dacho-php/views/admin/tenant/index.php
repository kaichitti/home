<?php
/**
 * テナント管理（一覧）
 * 変数: $tenants (array: 利用状況付き), $showDeleted (bool), $csrf_token
 */
require_once __DIR__ . '/../_tenant_helpers.php';
$tenants     = $tenants ?? [];
$showDeleted = !empty($showDeleted);
$adminTitle  = 'テナント管理';
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
?>
<div class="page-header">
    <h1 class="page-header__title">テナント管理</h1>
    <div class="page-header__actions">
        <?php if ($showDeleted): ?>
        <a href="/admin/index.php?page=tenant" class="btn btn-outline">削除済みを隠す</a>
        <?php else: ?>
        <a href="/admin/index.php?page=tenant&amp;deleted=1" class="btn btn-outline">削除済みも表示</a>
        <?php endif; ?>
        <a href="/admin/index.php?page=tenant.create" class="btn btn-primary">＋ テナント追加</a>
    </div>
</div>

<div class="card">
    <div class="table-wrap">
        <table class="table">
            <thead>
                <tr>
                    <th>ID</th>
                    <th>コード</th>
                    <th>テナント名</th>
                    <th>種別</th>
                    <th>状態</th>
                    <th style="text-align:right;">利用者</th>
                    <th style="text-align:right;">台帳</th>
                    <th>作成日</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
            <?php if (empty($tenants)): ?>
                <tr><td colspan="9" class="empty-state">テナントが登録されていません。</td></tr>
            <?php endif; ?>
            <?php foreach ($tenants as $tenant): ?>
                <?php $st = (string)($tenant['status'] ?? ''); ?>
                <tr>
                    <td class="nowrap text-muted"><?= (int)$tenant['id'] ?></td>
                    <td class="nowrap"><code><?= $h($tenant['code']) ?></code></td>
                    <td><a href="/admin/index.php?page=tenant.show&amp;id=<?= (int)$tenant['id'] ?>"><?= $h($tenant['name']) ?></a></td>
                    <td class="nowrap"><?= $h(furyo_admin_type_label((string)$tenant['type'])) ?></td>
                    <td class="nowrap"><?= furyo_admin_status_badge($st) ?></td>
                    <td class="nowrap" style="text-align:right;"><?= (int)($tenant['active_user_count'] ?? 0) ?>人</td>
                    <td class="nowrap" style="text-align:right;"><?= number_format((int)($tenant['ledger_count'] ?? 0)) ?>件</td>
                    <td class="nowrap" style="font-size:.8rem;"><?= $h(substr((string)$tenant['created_at'], 0, 10)) ?></td>
                    <td>
                        <div class="actions">
                            <a href="/admin/index.php?page=tenant.show&amp;id=<?= (int)$tenant['id'] ?>" class="btn btn-accent btn-sm">詳細</a>
                            <?php if ($st !== 'deleted'): ?>
                            <a href="/admin/index.php?page=tenant.edit&amp;id=<?= (int)$tenant['id'] ?>" class="btn btn-outline btn-sm">編集</a>
                            <?php endif; ?>
                            <?php if ($st === 'active'): ?>
                            <form method="POST" action="/admin/index.php?page=tenant.suspend">
                                <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
                                <input type="hidden" name="id" value="<?= (int)$tenant['id'] ?>">
                                <button type="submit" class="btn btn-warning btn-sm"
                                        onclick="return confirm('このテナントを停止しますか？\n利用者はログインできなくなります（データは保持されます）。')">停止</button>
                            </form>
                            <?php elseif ($st === 'suspended'): ?>
                            <form method="POST" action="/admin/index.php?page=tenant.resume">
                                <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
                                <input type="hidden" name="id" value="<?= (int)$tenant['id'] ?>">
                                <button type="submit" class="btn btn-success btn-sm"
                                        onclick="return confirm('このテナントを再開しますか？')">再開</button>
                            </form>
                            <?php endif; ?>
                        </div>
                    </td>
                </tr>
            <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</div>
<p class="form-hint">テナントの削除は、各テナントの詳細画面から行えます（誤操作防止のためテナントコードの入力が必要です）。</p>
