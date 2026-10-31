<?php
$pageTitle  = 'アカウント設定 - 古物台帳管理システム';
$activePage = 'account';

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">アカウント設定</h1>
</div>

<?php if (!empty($error)): ?>
<div class="alert alert-danger"><?= htmlspecialchars($error) ?></div>
<?php endif; ?>

<!-- メールアドレス変更 -->
<div class="card" style="max-width: 560px;">
    <div class="card__header">メールアドレス（ログインID）の変更</div>
    <div class="card__body">
        <div class="form-group">
            <label class="form-label">現在のメールアドレス</label>
            <input type="text" class="form-control" value="<?= htmlspecialchars($currentEmail ?? '') ?>" readonly>
        </div>

        <form method="POST" action="/index.php?page=account">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">

            <div class="form-group">
                <label class="form-label" for="new_email">
                    新しいメールアドレス <span class="required">*</span>
                </label>
                <input type="email" id="new_email" name="new_email" class="form-control"
                       placeholder="例：taro@example.com" maxlength="255" required>
                <div class="form-hint">変更後は新しいアドレスがログインIDになります。</div>
            </div>

            <div class="form-group">
                <label class="form-label" for="current_password">
                    現在のパスワード <span class="required">*</span>
                </label>
                <input type="password" id="current_password" name="current_password"
                       class="form-control" autocomplete="current-password" required>
                <div class="form-hint">本人確認のため現在のパスワードを入力してください。</div>
            </div>

            <button type="submit" class="btn btn-primary">メールアドレスを変更</button>
        </form>
    </div>
</div>

<!-- パスワード変更への導線 -->
<div class="card" style="max-width: 560px;">
    <div class="card__header">パスワード</div>
    <div class="card__body">
        <a href="/index.php?page=change_password" class="btn btn-outline">パスワードを変更する</a>
    </div>
</div>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
