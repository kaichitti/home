<?php
$isEdit = $isEdit ?? false;
$pageTitle  = ($isEdit ? 'ユーザー編集' : 'ユーザー新規登録') . ' - 古物台帳管理システム';
$activePage = 'user';

// 入力エラーで再表示した場合は入力値を優先する
// （以前は表示名・所属拠点・権限が保存済みの値／空欄に戻っていた）
$input = (isset($input) && is_array($input))
    ? array_map(static fn ($v) => is_scalar($v) ? (string)$v : '', $input)
    : [];
$val = static function (string $key, $default = '') use ($input, $user) {
    if (array_key_exists($key, $input)) {
        return $input[$key];
    }
    return isset($user[$key]) && $user[$key] !== null ? (string)$user[$key] : (string)$default;
};
$selBranch = $val('branch_id');
$selRole   = $val('role', 'user');
$isSelf    = $isEdit && (int)($user['id'] ?? 0) === (int)($currentUserId ?? 0);
$isOwnerU  = $isEdit && !empty($user['is_owner']);

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title"><?= $isEdit ? 'ユーザー編集' : 'ユーザー新規登録' ?></h1>
    <div class="page-header__actions">
        <a href="/index.php?page=user" class="btn btn-outline">&#8592; 一覧に戻る</a>
    </div>
</div>

<?php if (!empty($errors['general'])): ?>
<div class="alert alert-danger"><?= htmlspecialchars($errors['general']) ?></div>
<?php elseif (!empty($errors)): ?>
<div class="alert alert-danger">入力内容を確認してください。</div>
<?php endif; ?>

<div class="card">
    <div class="card__header"><?= $isEdit ? '基本情報' : 'ユーザー情報' ?></div>
    <div class="card__body">
        <form method="POST"
              action="<?= $isEdit ? '/index.php?page=user.update&id=' . (int)$user['id'] : '/index.php?page=user.store' ?>">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
            <?php if ($isEdit): ?>
            <!-- 更新処理は POST の id を参照するため必須 -->
            <input type="hidden" name="id" value="<?= (int)$user['id'] ?>">
            <?php endif; ?>

            <!-- 表示名 -->
            <div class="form-group">
                <label class="form-label" for="display_name">
                    表示名 <span class="required">*</span>
                </label>
                <input type="text" id="display_name" name="display_name" maxlength="255"
                       class="form-control <?= !empty($errors['display_name']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($val('display_name')) ?>"
                       placeholder="例：山田 太郎" required>
                <?php if (!empty($errors['display_name'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['display_name']) ?></div>
                <?php endif; ?>
            </div>

            <!-- メールアドレス -->
            <div class="form-group">
                <label class="form-label" for="email">
                    メールアドレス（ログインID） <span class="required">*</span>
                </label>
                <input type="email" id="email" name="email" maxlength="255"
                       class="form-control <?= !empty($errors['email']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($val('email')) ?>"
                       placeholder="例：taro@example.com" autocomplete="off"
                       <?= ($isOwnerU && !$isSelf) ? 'readonly' : '' ?>
                       required>
                <?php if ($isOwnerU && !$isSelf): ?>
                    <div class="form-hint">オーナーのメールアドレスは、オーナー本人が「アカウント設定」から変更します。</div>
                <?php elseif ($isEdit): ?>
                    <div class="form-hint">メールアドレスはログインIDです。変更すると次回から新しいアドレスでログインします。</div>
                <?php endif; ?>
                <?php if (!empty($errors['email'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['email']) ?></div>
                <?php endif; ?>
            </div>

            <?php if (!$isEdit): ?>
            <!-- 初期パスワード（新規登録時のみ） -->
            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="password">
                        初期パスワード <span class="required">*</span>
                    </label>
                    <input type="password" id="password" name="password"
                           class="form-control <?= !empty($errors['password']) ? 'is-invalid' : '' ?>"
                           autocomplete="new-password" minlength="8" maxlength="72" required>
                    <div class="form-hint">8文字以上で英字・数字を含めてください。本人に伝え、初回ログイン時に本人のパスワードへ変更してもらいます。</div>
                    <?php if (!empty($errors['password'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['password']) ?></div>
                    <?php endif; ?>
                </div>
                <div class="form-group">
                    <label class="form-label" for="password_confirm">
                        初期パスワード（確認） <span class="required">*</span>
                    </label>
                    <input type="password" id="password_confirm" name="password_confirm"
                           class="form-control <?= !empty($errors['password_confirm']) ? 'is-invalid' : '' ?>"
                           autocomplete="new-password" minlength="8" maxlength="72" required>
                    <?php if (!empty($errors['password_confirm'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['password_confirm']) ?></div>
                    <?php endif; ?>
                </div>
            </div>
            <?php endif; ?>

            <div class="form-row form-row-2">
                <!-- 所属拠点 -->
                <div class="form-group">
                    <label class="form-label" for="branch_id">
                        所属拠点 <span class="required">*</span>
                    </label>
                    <select id="branch_id" name="branch_id"
                            class="form-control <?= !empty($errors['branch_id']) ? 'is-invalid' : '' ?>"
                            required>
                        <option value="">-- 選択してください --</option>
                        <?php foreach (($branches ?? []) as $b): ?>
                        <option value="<?= (int)$b['id'] ?>" <?= $selBranch === (string)$b['id'] ? 'selected' : '' ?>>
                            <?= htmlspecialchars($b['name']) ?>
                        </option>
                        <?php endforeach; ?>
                    </select>
                    <?php if (!empty($errors['branch_id'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['branch_id']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 権限 -->
                <div class="form-group">
                    <label class="form-label" for="role">権限</label>
                    <select id="role" name="role"
                            class="form-control <?= !empty($errors['role']) ? 'is-invalid' : '' ?>">
                        <option value="user"  <?= $selRole === 'user'  ? 'selected' : '' ?>>一般ユーザー</option>
                        <option value="admin" <?= $selRole === 'admin' ? 'selected' : '' ?>>管理者</option>
                    </select>
                    <div class="form-hint">管理者はユーザー・拠点の管理、台帳の削除・承認、取引の取消、CSV出力などができます。</div>
                    <?php if (!empty($errors['role'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['role']) ?></div>
                    <?php endif; ?>
                </div>
            </div>

            <!-- フォームアクション -->
            <div class="d-flex gap-8" style="justify-content: flex-end; margin-top: 8px; flex-wrap: wrap;">
                <a href="/index.php?page=user" class="btn btn-secondary">キャンセル</a>
                <button type="submit" class="btn btn-primary">
                    <?= $isEdit ? '変更を保存する' : '登録する' ?>
                </button>
            </div>
        </form>
    </div>
</div>

<?php if ($isEdit): ?>
<!-- パスワードの再設定（管理者が仮パスワードを設定する） -->
<div class="card">
    <div class="card__header">パスワードの再設定</div>
    <div class="card__body">
        <?php if ($isSelf): ?>
            <p class="text-muted" style="font-size:.875rem;">
                自分のパスワードは <a href="/index.php?page=change_password">パスワード変更</a> から変更してください。
            </p>
        <?php elseif ($isOwnerU): ?>
            <p class="text-muted" style="font-size:.875rem;">
                オーナーのパスワードは他の管理者からは再設定できません。オーナー本人が変更するか、システム管理者に再設定を依頼してください。
            </p>
        <?php else: ?>
            <p style="font-size:.85rem; margin-bottom:12px;">
                本人がパスワードを忘れた場合やログインがロックされた場合に、仮のパスワードを設定します。
                設定するとロックも解除され、次回ログイン時に本人のパスワードへの変更が求められます。
            </p>
            <?php if (!empty($user['locked_until']) && strtotime((string)$user['locked_until']) > time()): ?>
            <div class="alert alert-warning" style="font-size:.85rem;">
                このユーザーはログイン失敗によりロック中です（<?= htmlspecialchars((string)$user['locked_until']) ?> まで）。
            </div>
            <?php endif; ?>
            <form method="POST" action="/index.php?page=user.password" autocomplete="off"
                  onsubmit="return confirm('このユーザーのパスワードを再設定しますか？\n（今のパスワードではログインできなくなります）');">
                <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
                <input type="hidden" name="id" value="<?= (int)$user['id'] ?>">
                <div class="form-row form-row-2">
                    <div class="form-group">
                        <label class="form-label" for="new_password">仮パスワード <span class="required">*</span></label>
                        <input type="password" id="new_password" name="new_password" class="form-control"
                               autocomplete="new-password" minlength="8" maxlength="72" required>
                        <div class="form-hint">8文字以上で英字・数字を含めてください。</div>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="new_password_confirm">仮パスワード（確認） <span class="required">*</span></label>
                        <input type="password" id="new_password_confirm" name="new_password_confirm" class="form-control"
                               autocomplete="new-password" minlength="8" maxlength="72" required>
                    </div>
                </div>
                <div class="d-flex" style="justify-content:flex-end;">
                    <button type="submit" class="btn btn-warning">パスワードを再設定する</button>
                </div>
            </form>
        <?php endif; ?>
    </div>
</div>
<?php endif; ?>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
