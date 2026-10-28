<?php
$isEdit = $isEdit ?? false;
$pageTitle  = ($isEdit ? '拠点編集' : '拠点新規登録') . ' - 古物台帳管理システム';
$activePage = 'branch';

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title"><?= $isEdit ? '拠点編集' : '拠点新規登録' ?></h1>
    <div class="page-header__actions">
        <a href="/index.php?page=branch" class="btn btn-outline">&#8592; 一覧に戻る</a>
    </div>
</div>

<?php if (!empty($errors['general'])): ?>
<div class="alert alert-danger"><?= htmlspecialchars($errors['general']) ?></div>
<?php endif; ?>

<div class="card">
    <div class="card__body">
        <form method="POST"
              action="<?= $isEdit ? '/index.php?page=branch.update&id=' . (int)$branch['id'] : '/index.php?page=branch.store' ?>">
            <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
            <?php if ($isEdit): ?>
            <!-- 更新処理は POST の id を参照するため必須（以前は欠落しており、編集の保存が常に「見つかりません」になっていた） -->
            <input type="hidden" name="id" value="<?= (int)$branch['id'] ?>">
            <?php endif; ?>

            <!-- 拠点名 -->
            <div class="form-group">
                <label class="form-label" for="name">
                    拠点名 <span class="required">*</span>
                </label>
                <input type="text" id="name" name="name"
                       class="form-control <?= !empty($errors['name']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($input['name'] ?? $branch['name'] ?? '') ?>"
                       placeholder="例：東京本店" required>
                <?php if (!empty($errors['name'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['name']) ?></div>
                <?php endif; ?>
            </div>

            <!-- 住所 -->
            <div class="form-group">
                <label class="form-label" for="address">住所</label>
                <input type="text" id="address" name="address"
                       class="form-control <?= !empty($errors['address']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($input['address'] ?? $branch['address'] ?? '') ?>"
                       placeholder="例：東京都新宿区西新宿1-1-1">
                <?php if (!empty($errors['address'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['address']) ?></div>
                <?php endif; ?>
            </div>

            <!-- 拠点ログインコード -->
            <div class="form-group">
                <label class="form-label" for="login_code">拠点ログインコード</label>
                <input type="text" id="login_code" name="login_code"
                       class="form-control <?= !empty($errors['login_code']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($input['login_code'] ?? $branch['login_code'] ?? '') ?>"
                       maxlength="50" placeholder="例：osaka-branch（半角英数字・ハイフン・アンダースコア）">
                <div class="form-hint">
                    この拠点のユーザーがログイン画面で使うコードです。設定すると、テナントコードの代わりにこのコードでログインでき、
                    その拠点に所属するユーザーのみログインできます（管理者・オーナーは全拠点からログイン可）。空欄の場合はテナントコードでログインします。
                </div>
                <?php if (!empty($errors['login_code'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['login_code']) ?></div>
                <?php endif; ?>
            </div>

            <!-- フォームアクション -->
            <div class="d-flex gap-8" style="justify-content: flex-end; margin-top: 8px;">
                <a href="/index.php?page=branch" class="btn btn-secondary">キャンセル</a>
                <button type="submit" class="btn btn-primary">
                    <?= $isEdit ? '変更を保存する' : '登録する' ?>
                </button>
            </div>

        </form>
    </div>
</div>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
