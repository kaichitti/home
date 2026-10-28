<?php
$isEdit     = isset($member) && $member !== null;
$pageTitle  = ($isEdit ? '会員編集' : '会員新規登録') . ' - 古物台帳管理システム';
$activePage = 'member';

$input  = $input ?? [];
$member = $member ?? [];

$v = function (string $key) use ($member, $input) {
    return htmlspecialchars((string)($input[$key] ?? $member[$key] ?? ''));
};
$cpType = $input['counterpart_type'] ?? $member['counterpart_type'] ?? 'individual';
$docSel = $input['id_document_type'] ?? $member['id_document_type'] ?? '';

$docTypes = [
    'driver_license'    => '運転免許証',
    'my_number'         => 'マイナンバーカード',
    'passport'          => 'パスポート',
    'health_insurance'  => '健康保険証',
    'residence_card'    => '住民基本台帳カード',
    'residence_status'  => '在留カード',
    'special_permanent' => '特別永住者証明書',
    'other'             => 'その他',
];

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title"><?= $isEdit ? '会員編集' : '会員新規登録' ?></h1>
    <a href="/index.php?page=member" class="btn btn-secondary">一覧に戻る</a>
</div>

<?php if (!empty($errors)): ?>
<div class="alert alert-danger" role="alert">
    <strong>入力内容を確認してください（<?= count($errors) ?>件）</strong>
    <ul style="margin:6px 0 0 18px;">
        <?php foreach ($errors as $msg): ?>
        <li><?= htmlspecialchars((string)$msg) ?></li>
        <?php endforeach; ?>
    </ul>
</div>
<?php endif; ?>

<form method="POST" action="/index.php?page=<?= $isEdit ? 'member.update' : 'member.store' ?>">
    <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
    <?php if ($isEdit): ?>
    <input type="hidden" name="id" value="<?= (int)$member['id'] ?>">
    <?php endif; ?>

    <div class="card">
        <div class="card__header">基本情報</div>
        <div class="card__body">

            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="member_code">会員番号<?= !empty($member) ? ' <span class="required">*</span>' : '' ?></label>
                    <input type="text" id="member_code" name="member_code"
                           class="form-control <?= !empty($errors['member_code']) ? 'is-invalid' : '' ?>"
                           value="<?= $v('member_code') ?>" maxlength="50"
                           placeholder="<?= !empty($member) ? '例：M-0001' : '空欄で自動採番（例：M-0001）' ?>" <?= !empty($member) ? 'required' : '' ?>>
                    <?php if (empty($member)): ?><div class="form-hint">空欄のまま登録すると M-0001 形式で自動採番します。</div><?php endif; ?>
                    <?php if (!empty($errors['member_code'])): ?><div class="form-error"><?= htmlspecialchars($errors['member_code']) ?></div><?php endif; ?>
                </div>

                <div class="form-group">
                    <label class="form-label">区分 <span class="required">*</span></label>
                    <div style="display:flex; gap:20px; padding-top:8px;">
                        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                            <input type="radio" name="counterpart_type" value="individual" <?= $cpType !== 'corporate' ? 'checked' : '' ?>> 個人
                        </label>
                        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                            <input type="radio" name="counterpart_type" value="corporate" <?= $cpType === 'corporate' ? 'checked' : '' ?>> 法人
                        </label>
                    </div>
                </div>
            </div>

            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="name">
                        <span id="m_name_label"><?= $cpType === 'corporate' ? '名称（会社名）' : '氏名' ?></span>
                        <span class="required">*</span>
                    </label>
                    <input type="text" id="name" name="name"
                           class="form-control <?= !empty($errors['name']) ? 'is-invalid' : '' ?>"
                           value="<?= $v('name') ?>" required>
                    <?php if (!empty($errors['name'])): ?><div class="form-error"><?= htmlspecialchars($errors['name']) ?></div><?php endif; ?>
                </div>

                <div class="form-group" id="m_contact_wrap" style="<?= $cpType !== 'corporate' ? 'display:none;' : '' ?>">
                    <label class="form-label" for="contact_name">担当者名 <span class="required">*</span></label>
                    <input type="text" id="contact_name" name="contact_name"
                           class="form-control <?= !empty($errors['contact_name']) ? 'is-invalid' : '' ?>"
                           value="<?= $v('contact_name') ?>" placeholder="例：営業部 佐藤 花子">
                    <?php if (!empty($errors['contact_name'])): ?><div class="form-error"><?= htmlspecialchars($errors['contact_name']) ?></div><?php endif; ?>
                </div>
            </div>

            <div class="form-group">
                <label class="form-label" for="address"><span id="m_addr_label"><?= $cpType === 'corporate' ? '所在地' : '住所' ?></span></label>
                <input type="text" id="address" name="address" class="form-control" value="<?= $v('address') ?>">
            </div>

            <div class="form-row form-row-2">
                <div class="form-group" id="m_occupation_wrap" style="<?= $cpType === 'corporate' ? 'display:none;' : '' ?>">
                    <label class="form-label" for="occupation">職業</label>
                    <input type="text" id="occupation" name="occupation" class="form-control" value="<?= $v('occupation') ?>">
                </div>
                <div class="form-group" id="m_age_wrap" style="<?= $cpType === 'corporate' ? 'display:none;' : '' ?>">
                    <label class="form-label" for="age">年齢</label>
                    <input type="number" id="age" name="age"
                           class="form-control <?= !empty($errors['age']) ? 'is-invalid' : '' ?>"
                           value="<?= $v('age') ?>" min="0" max="150">
                    <?php if (!empty($errors['age'])): ?><div class="form-error"><?= htmlspecialchars($errors['age']) ?></div><?php endif; ?>
                </div>
            </div>

            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="phone">電話番号</label>
                    <input type="text" id="phone" name="phone" class="form-control" value="<?= $v('phone') ?>">
                </div>
                <div class="form-group">
                    <label class="form-label" for="account">取引アカウント</label>
                    <input type="text" id="account" name="account" class="form-control" value="<?= $v('account') ?>"
                           maxlength="255" placeholder="例：メルカリ @user123（オンラインID等・任意）">
                </div>
            </div>
        </div>
    </div>

    <div class="card">
        <div class="card__header">本人確認情報（任意）</div>
        <div class="card__body">
            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="id_document_type">確認書類種別</label>
                    <select id="id_document_type" name="id_document_type"
                            class="form-control <?= !empty($errors['id_document_type']) ? 'is-invalid' : '' ?>">
                        <option value="">-- 未登録 --</option>
                        <?php foreach ($docTypes as $dv => $dl): ?>
                        <option value="<?= $dv ?>" <?= $docSel === $dv ? 'selected' : '' ?>><?= $dl ?></option>
                        <?php endforeach; ?>
                    </select>
                    <?php if (!empty($errors['id_document_type'])): ?><div class="form-error"><?= htmlspecialchars($errors['id_document_type']) ?></div><?php endif; ?>
                </div>
                <div class="form-group">
                    <label class="form-label" for="id_document_number">書類番号・記号</label>
                    <input type="text" id="id_document_number" name="id_document_number" class="form-control"
                           value="<?= $v('id_document_number') ?>" maxlength="64" placeholder="任意">
                    <div class="form-hint" id="m_mynumber_hint" style="display:<?= $docSel === 'my_number' ? '' : 'none' ?>; color:#c0392b;">
                        &#9888; マイナンバーカードの個人番号は法令上記録できないため、番号欄は入力できません。
                    </div>
                </div>
            </div>

            <div class="form-group">
                <label class="form-label" for="note">備考</label>
                <textarea id="note" name="note" class="form-control" rows="2"><?= $v('note') ?></textarea>
            </div>
        </div>
    </div>

    <div style="display:flex; gap:8px;">
        <button type="submit" class="btn btn-primary"><?= $isEdit ? '更新する' : '登録する' ?></button>
        <a href="/index.php?page=member" class="btn btn-secondary">キャンセル</a>
    </div>
</form>

<script>
(function () {
    'use strict';
    var radios = document.querySelectorAll('input[name="counterpart_type"]');
    function toggle() {
        var checked   = document.querySelector('input[name="counterpart_type"]:checked');
        var corporate = checked && checked.value === 'corporate';
        document.getElementById('m_contact_wrap').style.display    = corporate ? '' : 'none';
        document.getElementById('m_occupation_wrap').style.display = corporate ? 'none' : '';
        document.getElementById('m_age_wrap').style.display        = corporate ? 'none' : '';
        document.getElementById('m_name_label').textContent        = corporate ? '名称（会社名）' : '氏名';
        document.getElementById('m_addr_label').textContent        = corporate ? '所在地' : '住所';
    }
    for (var i = 0; i < radios.length; i++) radios[i].addEventListener('change', toggle);

    var docSel = document.getElementById('id_document_type');
    var hint   = document.getElementById('m_mynumber_hint');
    var numIn  = document.getElementById('id_document_number');
    function toggleMn() {
        var isMn = docSel && docSel.value === 'my_number';
        if (hint) hint.style.display = isMn ? '' : 'none';
        if (numIn) {
            numIn.disabled = isMn;
            if (isMn) {
                numIn.value = '';
                numIn.placeholder = 'マイナンバーカードの番号は記録できません';
                numIn.style.background = '#e9ecef';
                numIn.style.cursor = 'not-allowed';
            } else {
                numIn.placeholder = '任意';
                numIn.style.background = '';
                numIn.style.cursor = '';
            }
        }
    }
    if (docSel) {
        docSel.addEventListener('change', toggleMn);
        toggleMn();
    }
}());
</script>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
