<?php
/**
 * システム管理者パスワード変更
 * 変数: $csrf_token, $error (string|null), $forced (bool), $done (bool), $minLength (int)
 */
$forced    = $forced    ?? false;
$done      = $done      ?? false;
$minLength = (int)($minLength ?? 12);
?>
<div class="page-header">
    <h1 class="page-header__title">パスワード変更</h1>
</div>

<?php if ($forced): ?>
<div class="alert alert-danger" role="alert">
    <span><strong>初期パスワードのままです。</strong>セキュリティのため、パスワードを変更するまで他の管理画面は利用できません。</span>
</div>
<?php endif; ?>

<?php if ($done): ?>
<div class="alert alert-success" role="status">
    <span>パスワードを変更しました。<a href="/admin/index.php?page=dashboard">ダッシュボードへ</a></span>
</div>
<?php endif; ?>

<?php if (!empty($error)): ?>
<div class="alert alert-danger" role="alert"><span><?= htmlspecialchars($error) ?></span></div>
<?php endif; ?>

<div class="card" style="max-width:560px;">
    <div class="card__header">システム管理者のパスワード</div>
    <div class="card__body">
        <form method="POST" action="/admin/index.php?page=password">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
            <div class="form-group">
                <label class="form-label" for="current_password">現在のパスワード <span class="required">*</span></label>
                <input type="password" id="current_password" name="current_password" class="form-control" required autocomplete="current-password">
            </div>
            <div class="form-group">
                <label class="form-label" for="new_password">新しいパスワード <span class="required">*</span></label>
                <input type="password" id="new_password" name="new_password" class="form-control" required minlength="<?= $minLength ?>" autocomplete="new-password">
                <div class="form-hint"><?= $minLength ?>文字以上で、英字・数字をそれぞれ1文字以上含めてください（初期パスワードは使用不可）。</div>
            </div>
            <div class="form-group">
                <label class="form-label" for="confirm_password">新しいパスワード（確認） <span class="required">*</span></label>
                <input type="password" id="confirm_password" name="confirm_password" class="form-control" required minlength="<?= $minLength ?>" autocomplete="new-password">
            </div>
            <div class="form-actions">
                <button type="submit" class="btn btn-primary">変更する</button>
            </div>
        </form>
    </div>
</div>
