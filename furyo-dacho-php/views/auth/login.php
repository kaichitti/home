<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title>ログイン - 古物台帳管理システム</title>
    <style>
        :root {
            --color-primary:      #1e3a5f;
            --color-accent:       #3a7bd5;
            --color-danger:       #c0392b;
            --color-border:       #dee2e6;
            --color-text:         #212529;
            --color-text-muted:   #6c757d;
            --color-bg:           #f4f6f9;
            --radius:             4px;
            --transition:         0.2s ease;
            --font-family:        'Noto Sans JP','Hiragino Kaku Gothic ProN','Hiragino Sans','Yu Gothic','Meiryo',sans-serif;
        }

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html { font-size: 14px; }
        body {
            font-family: var(--font-family);
            background: var(--color-bg);
            color: var(--color-text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 24px 16px;
        }

        .login-wrap {
            width: 100%;
            max-width: 420px;
        }

        .login-logo {
            text-align: center;
            margin-bottom: 28px;
        }
        .login-logo__title {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--color-primary);
            letter-spacing: 0.08em;
        }
        .login-logo__sub {
            font-size: 0.8rem;
            color: var(--color-text-muted);
            margin-top: 4px;
        }

        .login-card {
            background: #fff;
            border-radius: 6px;
            box-shadow: 0 2px 16px rgba(0,0,0,0.1);
            padding: 32px 32px 28px;
        }

        .login-card__title {
            font-size: 1rem;
            font-weight: 700;
            color: var(--color-primary);
            margin-bottom: 24px;
            text-align: center;
        }

        .alert-danger {
            background: #fdf3f3;
            border-left: 4px solid var(--color-danger);
            color: #721c24;
            padding: 10px 14px;
            border-radius: var(--radius);
            font-size: 0.85rem;
            margin-bottom: 16px;
        }

        .form-group { margin-bottom: 16px; }

        .form-label {
            display: block;
            font-size: 0.83rem;
            font-weight: 600;
            color: var(--color-text);
            margin-bottom: 5px;
        }
        .form-label .required { color: var(--color-danger); margin-left: 3px; }

        .form-control {
            display: block;
            width: 100%;
            padding: 9px 12px;
            border: 1px solid var(--color-border);
            border-radius: var(--radius);
            background: #fff;
            color: var(--color-text);
            font-family: inherit;
            font-size: 0.95rem;
            transition: border-color var(--transition), box-shadow var(--transition);
        }
        .form-control:focus {
            outline: none;
            border-color: var(--color-accent);
            box-shadow: 0 0 0 3px rgba(58,123,213,0.15);
        }
        .form-control.is-invalid { border-color: var(--color-danger); }
        .form-error { font-size: 0.78rem; color: var(--color-danger); margin-top: 3px; }

        .btn-submit {
            display: block;
            width: 100%;
            padding: 11px;
            background: var(--color-primary);
            color: #fff;
            border: none;
            border-radius: var(--radius);
            font-size: 0.95rem;
            font-weight: 700;
            cursor: pointer;
            letter-spacing: 0.05em;
            margin-top: 24px;
            transition: background var(--transition);
            font-family: inherit;
        }
        .btn-submit:hover { background: #152b47; }

        .login-footer {
            text-align: center;
            margin-top: 20px;
            font-size: 0.75rem;
            color: var(--color-text-muted);
        }

        @media (max-width: 480px) {
            .login-card { padding: 24px 20px 20px; }
        }
    </style>
</head>
<body>

<div class="login-wrap">
    <div class="login-logo">
        <div class="login-logo__title">古物台帳</div>
        <div class="login-logo__sub">古物台帳管理システム</div>
    </div>

    <div class="login-card">
        <h1 class="login-card__title">ログイン</h1>

        <?php if (!empty($error)): ?>
            <div class="alert-danger"><?= htmlspecialchars($error) ?></div>
        <?php endif; ?>

        <form method="POST" action="/index.php?page=login" novalidate>
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token) ?>">

            <div class="form-group">
                <label for="tenant_code" class="form-label">
                    テナントコード／拠点コード<span class="required">*</span>
                </label>
                <input
                    type="text"
                    id="tenant_code"
                    name="tenant_code"
                    class="form-control <?= !empty($errors['tenant_code']) ? 'is-invalid' : '' ?>"
                    required
                    autocomplete="organization"
                    placeholder="例: company-abc / osaka-branch"
                    value="<?= htmlspecialchars($old['tenant_code'] ?? '') ?>"
                >
                <?php if (!empty($errors['tenant_code'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['tenant_code']) ?></div>
                <?php endif; ?>
            </div>

            <div class="form-group">
                <label for="email" class="form-label">
                    メールアドレス<span class="required">*</span>
                </label>
                <input
                    type="email"
                    id="email"
                    name="email"
                    class="form-control <?= !empty($errors['email']) ? 'is-invalid' : '' ?>"
                    required
                    autocomplete="email"
                    placeholder="example@email.com"
                    value="<?= htmlspecialchars($old['email'] ?? '') ?>"
                >
                <?php if (!empty($errors['email'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['email']) ?></div>
                <?php endif; ?>
            </div>

            <div class="form-group">
                <label for="password" class="form-label">
                    パスワード<span class="required">*</span>
                </label>
                <input
                    type="password"
                    id="password"
                    name="password"
                    class="form-control"
                    required
                    autocomplete="current-password"
                    placeholder="パスワードを入力"
                >
            </div>

            <button type="submit" class="btn-submit">ログイン</button>
        </form>
        <p style="margin-top:16px; font-size:.75rem; color:#6c757d; text-align:center; line-height:1.6;">
            パスワードを忘れた場合やロックされた場合は、<br>管理者にパスワードの再設定を依頼してください。
        </p>
    </div>

    <div class="login-footer">
        &copy; <?= date('Y') ?> 古物台帳管理システム
    </div>
</div>

</body>
</html>
