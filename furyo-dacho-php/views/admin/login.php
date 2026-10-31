<?php
/**
 * システム管理者ログイン
 * 変数: $csrf_token, $error (string|null)
 */
?>
<div class="login-card">
    <div class="login-card__head">
        <h1>古物台帳管理システム</h1>
        <p>システム管理者ログイン</p>
    </div>
    <div class="login-card__body">
        <?php if (!empty($error)): ?>
        <div class="alert alert-danger" role="alert"><span><?= htmlspecialchars($error) ?></span></div>
        <?php endif; ?>
        <form method="POST" action="/admin/index.php?page=login" novalidate>
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
            <div class="form-group">
                <label class="form-label" for="username">ユーザー名</label>
                <input type="text" id="username" name="username" class="form-control" required
                       autocomplete="username" autocapitalize="off" spellcheck="false" maxlength="64" autofocus>
            </div>
            <div class="form-group">
                <label class="form-label" for="password">パスワード</label>
                <input type="password" id="password" name="password" class="form-control" required autocomplete="current-password">
            </div>
            <button type="submit" class="btn btn-primary btn-block" style="padding:10px;">ログイン</button>
        </form>
        <p class="form-hint" style="margin-top:16px; text-align:center;">
            テナント（事業者）の方は <a href="/index.php?page=login">通常のログイン画面</a> をご利用ください。
        </p>
    </div>
</div>
