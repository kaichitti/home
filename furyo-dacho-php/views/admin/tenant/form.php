<?php
/**
 * テナント追加・編集フォーム
 * 変数: $tenant (array|null), $csrf_token, $error (string|null), $errors (array), $old (array 再表示用)
 */
$isEdit     = isset($tenant) && $tenant !== null;
$adminTitle = $isEdit ? 'テナント編集' : 'テナント追加';
$errors     = $errors ?? [];
$old        = (isset($old) && is_array($old)) ? array_map(static fn ($v) => is_scalar($v) ? (string)$v : '', $old) : [];
$val = static function (string $key, string $default = '') use ($old, $tenant): string {
    if (array_key_exists($key, $old)) {
        return $old[$key];
    }
    return isset($tenant[$key]) ? (string)$tenant[$key] : $default;
};
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
$err = static function (string $key) use ($errors, $h): string {
    return !empty($errors[$key]) ? '<div class="form-error">' . $h($errors[$key]) . '</div>' : '';
};
$inv = static fn (string $key): string => !empty($errors[$key]) ? ' is-invalid' : '';
$action = $isEdit ? '/admin/index.php?page=tenant.update' : '/admin/index.php?page=tenant.store';
?>
<div class="page-header">
    <h1 class="page-header__title"><?= $isEdit ? 'テナント編集' : 'テナント追加' ?></h1>
    <div class="page-header__actions">
        <a href="<?= $isEdit ? '/admin/index.php?page=tenant.show&amp;id=' . (int)$tenant['id'] : '/admin/index.php?page=tenant' ?>" class="btn btn-outline">&#8592; 戻る</a>
    </div>
</div>

<?php if (!empty($error)): ?>
<div class="alert alert-danger" role="alert"><span><?= $h($error) ?></span></div>
<?php endif; ?>

<form method="POST" action="<?= $h($action) ?>" style="max-width:760px;">
    <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">
    <?php if ($isEdit): ?>
    <input type="hidden" name="id" value="<?= (int)$tenant['id'] ?>">
    <?php endif; ?>

    <div class="card">
        <div class="card__header">テナント情報</div>
        <div class="card__body">
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label" for="code">テナントコード <span class="required">*</span></label>
                    <input type="text" id="code" name="code" class="form-control<?= $inv('code') ?>" required maxlength="50"
                           pattern="[a-zA-Z0-9_\-]+" autocapitalize="off" spellcheck="false"
                           value="<?= $h($val('code')) ?>" placeholder="例：kaitori-shop">
                    <div class="form-hint">半角英数字・ハイフン・アンダースコア。利用者がログイン時に入力します。</div>
                    <?= $err('code') ?>
                </div>
                <div class="form-group">
                    <label class="form-label" for="name">テナント名（事業者名） <span class="required">*</span></label>
                    <input type="text" id="name" name="name" class="form-control<?= $inv('name') ?>" required maxlength="255"
                           value="<?= $h($val('name')) ?>" placeholder="例：株式会社〇〇リサイクル">
                    <?= $err('name') ?>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label" for="type">種別 <span class="required">*</span></label>
                    <select id="type" name="type" class="form-control<?= $inv('type') ?>" required>
                        <option value="client" <?= $val('type', 'client') === 'client' ? 'selected' : '' ?>>顧客</option>
                        <option value="own"    <?= $val('type', 'client') === 'own'    ? 'selected' : '' ?>>自社</option>
                    </select>
                    <?= $err('type') ?>
                </div>
                <?php if ($isEdit): ?>
                <div class="form-group">
                    <label class="form-label" for="status">状態 <span class="required">*</span></label>
                    <select id="status" name="status" class="form-control<?= $inv('status') ?>" required>
                        <option value="active"    <?= $val('status') === 'active'    ? 'selected' : '' ?>>有効</option>
                        <option value="suspended" <?= $val('status') === 'suspended' ? 'selected' : '' ?>>停止中</option>
                    </select>
                    <div class="form-hint">停止中のテナントの利用者はログインできません。</div>
                    <?= $err('status') ?>
                </div>
                <?php endif; ?>
            </div>
        </div>
    </div>

    <?php if (!$isEdit): ?>
    <div class="card">
        <div class="card__header">初期管理者（オーナー）</div>
        <div class="card__body">
            <p class="form-hint" style="margin:0 0 14px; font-size:.82rem;">
                テナントの最初の管理者（オーナー）を作成します。オーナーは削除・無効化・権限変更ができません。
                初回ログイン時にパスワードの変更が求められます。主拠点「本社」も自動で作成されます。
            </p>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label" for="admin_name">表示名 <span class="required">*</span></label>
                    <input type="text" id="admin_name" name="admin_name" class="form-control<?= $inv('admin_name') ?>" required maxlength="255"
                           value="<?= $h($old['admin_name'] ?? '') ?>" placeholder="例：山田 太郎">
                    <?= $err('admin_name') ?>
                </div>
                <div class="form-group">
                    <label class="form-label" for="admin_email">メールアドレス（ログインID） <span class="required">*</span></label>
                    <input type="email" id="admin_email" name="admin_email" class="form-control<?= $inv('admin_email') ?>" required maxlength="255"
                           value="<?= $h($old['admin_email'] ?? '') ?>" placeholder="例：owner@example.com" autocomplete="off">
                    <?= $err('admin_email') ?>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label" for="admin_password">初期パスワード <span class="required">*</span></label>
                    <input type="password" id="admin_password" name="admin_password" class="form-control<?= $inv('admin_password') ?>"
                           required minlength="8" maxlength="72" autocomplete="new-password">
                    <div class="form-hint">8文字以上で、英字・数字をそれぞれ1文字以上含めてください。</div>
                    <?= $err('admin_password') ?>
                </div>
                <div class="form-group">
                    <label class="form-label" for="admin_password_confirm">初期パスワード（確認） <span class="required">*</span></label>
                    <input type="password" id="admin_password_confirm" name="admin_password_confirm" class="form-control<?= $inv('admin_password_confirm') ?>"
                           required minlength="8" maxlength="72" autocomplete="new-password">
                    <?= $err('admin_password_confirm') ?>
                </div>
            </div>
        </div>
    </div>
    <?php endif; ?>

    <div class="form-actions">
        <a href="<?= $isEdit ? '/admin/index.php?page=tenant.show&amp;id=' . (int)$tenant['id'] : '/admin/index.php?page=tenant' ?>" class="btn btn-secondary">キャンセル</a>
        <button type="submit" class="btn btn-primary"><?= $isEdit ? '変更を保存する' : 'テナントを作成する' ?></button>
    </div>
</form>
