<?php
$pageTitle  = 'パスワード変更 - 古物台帳管理システム';
$activePage = '';

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">パスワード変更</h1>
</div>

<?php if (!empty($success)): ?>
    <div class="alert alert-success"><?= htmlspecialchars($success) ?></div>
<?php endif; ?>
<?php if (!empty($error)): ?>
    <div class="alert alert-danger"><?= htmlspecialchars($error) ?></div>
<?php endif; ?>

<div class="card" style="max-width: 520px;">
    <div class="card__header">パスワード変更フォーム</div>
    <div class="card__body">

        <div class="alert alert-info" style="margin-bottom: 20px;">
            <strong>パスワードポリシー</strong><br>
            &#x2022; 8文字以上<br>
            &#x2022; 英字（アルファベット）を1文字以上含む<br>
            &#x2022; 数字を1文字以上含む
        </div>

        <form method="POST" action="/index.php?page=change_password" novalidate id="changePasswordForm">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token) ?>">

            <div class="form-group">
                <label for="current_password" class="form-label">
                    現在のパスワード<span class="required">*</span>
                </label>
                <input
                    type="password"
                    id="current_password"
                    name="current_password"
                    class="form-control <?= !empty($errors['current_password']) ? 'is-invalid' : '' ?>"
                    required
                    autocomplete="current-password"
                >
                <?php if (!empty($errors['current_password'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['current_password']) ?></div>
                <?php endif; ?>
            </div>

            <div class="form-group">
                <label for="new_password" class="form-label">
                    新しいパスワード<span class="required">*</span>
                </label>
                <input
                    type="password"
                    id="new_password"
                    name="new_password"
                    class="form-control <?= !empty($errors['new_password']) ? 'is-invalid' : '' ?>"
                    required
                    autocomplete="new-password"
                    minlength="8"
                >
                <div class="form-hint">8文字以上、英字と数字を含む</div>
                <?php if (!empty($errors['new_password'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['new_password']) ?></div>
                <?php endif; ?>
                <!-- パスワード強度インジケーター -->
                <div id="pwStrengthWrap" style="margin-top: 6px; display:none;">
                    <div style="height:4px; background:#e9ecef; border-radius:2px; overflow:hidden;">
                        <div id="pwStrengthBar" style="height:100%; width:0; transition:width 0.3s, background 0.3s;"></div>
                    </div>
                    <div id="pwStrengthLabel" style="font-size:0.75rem; margin-top:3px; color:#6c757d;"></div>
                </div>
            </div>

            <div class="form-group">
                <label for="confirm_password" class="form-label">
                    新しいパスワード（確認）<span class="required">*</span>
                </label>
                <input
                    type="password"
                    id="confirm_password"
                    name="confirm_password"
                    class="form-control <?= !empty($errors['confirm_password']) ? 'is-invalid' : '' ?>"
                    required
                    autocomplete="new-password"
                    minlength="8"
                >
                <div id="pwMatchMsg" style="font-size:0.78rem; margin-top:3px;"></div>
                <?php if (!empty($errors['confirm_password'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['confirm_password']) ?></div>
                <?php endif; ?>
            </div>

            <div style="display: flex; gap: 10px; margin-top: 24px;">
                <button type="submit" class="btn btn-primary">パスワードを変更する</button>
                <a href="/index.php?page=dashboard" class="btn btn-outline">キャンセル</a>
            </div>
        </form>
    </div>
</div>

<script>
(function () {
    var newPw   = document.getElementById('new_password');
    var confirm = document.getElementById('confirm_password');
    var bar     = document.getElementById('pwStrengthBar');
    var label   = document.getElementById('pwStrengthLabel');
    var wrap    = document.getElementById('pwStrengthWrap');
    var matchMsg= document.getElementById('pwMatchMsg');

    function calcStrength(pw) {
        var score = 0;
        if (pw.length >= 8)  score++;
        if (pw.length >= 12) score++;
        if (/[a-zA-Z]/.test(pw)) score++;
        if (/[0-9]/.test(pw))    score++;
        if (/[^a-zA-Z0-9]/.test(pw)) score++;
        return score;
    }

    if (newPw) {
        newPw.addEventListener('input', function () {
            var pw = newPw.value;
            if (!pw) { wrap.style.display = 'none'; return; }
            wrap.style.display = 'block';
            var s = calcStrength(pw);
            var pct = Math.min(s * 20, 100) + '%';
            var color, text;
            if (s <= 2) { color = '#c0392b'; text = '弱い'; }
            else if (s <= 3) { color = '#e67e22'; text = '普通'; }
            else { color = '#27ae60'; text = '強い'; }
            bar.style.width    = pct;
            bar.style.background = color;
            label.textContent  = '強度: ' + text;
            label.style.color  = color;
            checkMatch();
        });
    }

    function checkMatch() {
        if (!confirm.value) { matchMsg.textContent = ''; return; }
        if (newPw.value === confirm.value) {
            matchMsg.textContent = '一致しています';
            matchMsg.style.color = '#27ae60';
        } else {
            matchMsg.textContent = 'パスワードが一致しません';
            matchMsg.style.color = '#c0392b';
        }
    }

    if (confirm) {
        confirm.addEventListener('input', checkMatch);
    }
}());
</script>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
