<?php
$isEdit    = isset($ledger);
// 再表示用の入力値は文字列・数値のみ使う（念のため。配列等はコントローラーの検証でエラーにしている）
$input = (isset($input) && is_array($input))
    ? array_map(static fn ($v) => is_scalar($v) ? $v : null, $input)
    : [];
$pageTitle = ($isEdit ? '台帳編集' : '台帳新規登録') . ' - 古物台帳管理システム';
// 新規登録時はサイドバーの「台帳登録」をハイライトする
// （以前は常に 'ledger' で「台帳一覧」がハイライトされていた）
$activePage = $isEdit ? 'ledger' : 'ledger.create';

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title"><?= $isEdit ? '台帳編集' : '台帳新規登録' ?></h1>
    <div class="page-header__actions">
        <a href="/index.php?page=ledger" class="btn btn-outline">&#8592; 一覧に戻る</a>
    </div>
</div>

<?php if (!empty($errors['general'])): ?>
<div class="alert alert-danger"><?= htmlspecialchars($errors['general']) ?></div>
<?php elseif (!empty($errors)): ?>
<?php /* 入力エラーの概要を先頭に表示する（以前は各項目の下にだけ表示され、下の方の項目のエラーに気付きにくかった） */ ?>
<div class="alert alert-danger" role="alert">
    <strong>入力内容を確認してください（<?= count($errors) ?>件）</strong>
    <ul style="margin:6px 0 0 18px;">
        <?php foreach ($errors as $msg): ?>
        <li><?= htmlspecialchars((string)$msg) ?></li>
        <?php endforeach; ?>
    </ul>
</div>
<?php endif; ?>

<form method="POST"
      action="<?= $isEdit ? '/index.php?page=ledger.update&id=' . (int)$ledger['id'] : '/index.php?page=ledger.store' ?>"
      enctype="multipart/form-data"
      id="ledgerForm">
    <input type="hidden" name="_csrf_token" value="<?= htmlspecialchars($csrf_token ?? '') ?>">
    <?php if ($isEdit): ?>
    <!-- 更新処理は POST の id を参照するため必須（以前は欠落しており、編集内容の保存が常に「台帳が見つかりません」になっていた） -->
    <input type="hidden" name="id" value="<?= (int)$ledger['id'] ?>">
    <?php endif; ?>

    <!-- ============================================================
         取引情報セクション
    ============================================================ -->
    <div class="card">
        <div class="card__header">取引情報</div>
        <div class="card__body">

            <!-- 拠点 -->
            <div class="form-group">
                <label class="form-label" for="branch_id">
                    拠点 <span class="required">*</span>
                </label>
                <select id="branch_id" name="branch_id"
                        class="form-control <?= !empty($errors['branch_id']) ? 'is-invalid' : '' ?>"
                        required>
                    <option value="">-- 選択してください --</option>
                    <?php if (!empty($branches)): ?>
                    <?php foreach ($branches as $b): ?>
                    <option value="<?= (int)$b['id'] ?>"
                        <?= (int)($input['branch_id'] ?? $ledger['branch_id'] ?? 0) === (int)$b['id'] ? 'selected' : '' ?>>
                        <?= htmlspecialchars($b['name']) ?>
                    </option>
                    <?php endforeach; ?>
                    <?php endif; ?>
                </select>
                <?php if (!empty($errors['branch_id'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['branch_id']) ?></div>
                <?php endif; ?>
            </div>

            <div class="form-row form-row-2">
                <!-- 取引年月日 -->
                <div class="form-group">
                    <label class="form-label" for="transaction_date">
                        取引年月日 <span class="required">*</span>
                    </label>
                    <input type="date" id="transaction_date" name="transaction_date"
                           class="form-control <?= !empty($errors['transaction_date']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['transaction_date'] ?? $ledger['transaction_date'] ?? '') ?>"
                           required>
                    <?php if (!empty($errors['transaction_date'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['transaction_date']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 取引種別 -->
                <div class="form-group">
                    <label class="form-label" for="transaction_type">
                        取引種別 <span class="required">*</span>
                    </label>
                    <select id="transaction_type" name="transaction_type"
                            class="form-control <?= !empty($errors['transaction_type']) ? 'is-invalid' : '' ?>"
                            required>
                        <option value="">-- 選択してください --</option>
                        <option value="buy"          <?= ($input['transaction_type'] ?? $ledger['transaction_type'] ?? '') === 'buy'          ? 'selected' : '' ?>>買取</option>
                        <option value="exchange"     <?= ($input['transaction_type'] ?? $ledger['transaction_type'] ?? '') === 'exchange'     ? 'selected' : '' ?>>交換</option>
                        <option value="consignment"  <?= ($input['transaction_type'] ?? $ledger['transaction_type'] ?? '') === 'consignment'  ? 'selected' : '' ?>>委託販売受け</option>
                        <option value="other"        <?= ($input['transaction_type'] ?? $ledger['transaction_type'] ?? '') === 'other'        ? 'selected' : '' ?>>その他</option>
                    </select>
                    <?php if (!empty($errors['transaction_type'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['transaction_type']) ?></div>
                    <?php endif; ?>
                </div>
            </div>

            <!-- 取引種別補足（other選択時に表示） -->
            <div class="form-group" id="transaction_type_note_wrap"
                 style="<?= ($input['transaction_type'] ?? $ledger['transaction_type'] ?? '') !== 'other' ? 'display:none;' : '' ?>">
                <label class="form-label" for="transaction_type_note">取引種別の補足</label>
                <input type="text" id="transaction_type_note" name="transaction_type_note" maxlength="255"
                       class="form-control <?= !empty($errors['transaction_type_note']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($input['transaction_type_note'] ?? $ledger['transaction_type_note'] ?? '') ?>"
                       placeholder="取引種別の詳細を入力してください">
                <?php if (!empty($errors['transaction_type_note'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['transaction_type_note']) ?></div>
                <?php endif; ?>
            </div>

            <div class="form-row form-row-2">
                <!-- 古物の種類 -->
                <div class="form-group">
                    <label class="form-label" for="item_category">
                        古物の種類 <span class="required">*</span>
                    </label>
                    <?php
                    // 選択肢: 法定13区分 + テナント独自区分 + その他（自由記述）
                    $catOptions  = $categoryOptions ?? \FuryoDacho\Models\ItemCategory::STATUTORY + ['other' => 'その他（自由記述）'];
                    $catSelected = $input['item_category'] ?? $ledger['item_category'] ?? '';
                    ?>
                    <select id="item_category" name="item_category"
                            class="form-control <?= !empty($errors['item_category']) ? 'is-invalid' : '' ?>">
                        <option value="">-- 選択してください --</option>
                        <?php foreach ($catOptions as $catVal => $catLabel): ?>
                        <option value="<?= htmlspecialchars((string)$catVal) ?>"
                            <?= (string)$catSelected === (string)$catVal ? 'selected' : '' ?>>
                            <?= htmlspecialchars($catLabel) ?>
                        </option>
                        <?php endforeach; ?>
                    </select>
                    <?php if (!empty($errors['item_category'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['item_category']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 品目 -->
                <div class="form-group">
                    <label class="form-label" for="item_name">
                        品目 <span class="required">*</span>
                    </label>
                    <input type="text" id="item_name" name="item_name" maxlength="255"
                           class="form-control <?= !empty($errors['item_name']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['item_name'] ?? $ledger['item_name'] ?? '') ?>"
                           placeholder="例：ロレックス デイトナ" required>
                    <?php if (!empty($errors['item_name'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['item_name']) ?></div>
                    <?php endif; ?>
                </div>

            </div>

            <!-- 古物の種類: その他の自由記述 -->
            <?php $catNote = $input['item_category_note'] ?? $ledger['item_category_note'] ?? ''; ?>
            <div class="form-group" id="item_category_note_wrap"
                 style="<?= $catSelected !== 'other' ? 'display:none;' : '' ?>">
                <label class="form-label" for="item_category_note">
                    古物の種類（自由記述） <span class="required">*</span>
                </label>
                <input type="text" id="item_category_note" name="item_category_note"
                       class="form-control <?= !empty($errors['item_category_note']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($catNote) ?>"
                       maxlength="255"
                       placeholder="区分名を入力してください（例: 楽器類）">
                <?php if (!empty($errors['item_category_note'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['item_category_note']) ?></div>
                <?php endif; ?>
            </div>


            <!-- 特徴・説明 -->
            <div class="form-group">
                <label class="form-label" for="item_description">特徴・説明</label>
                <textarea id="item_description" name="item_description"
                          class="form-control <?= !empty($errors['item_description']) ? 'is-invalid' : '' ?>"
                          rows="3"
                          placeholder="品物の特徴・状態・シリアル番号等を入力してください"><?= htmlspecialchars($input['item_description'] ?? $ledger['item_description'] ?? '') ?></textarea>
                <?php if (!empty($errors['item_description'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['item_description']) ?></div>
                <?php endif; ?>
            </div>

            <!-- シリアル番号（任意） -->
            <div class="form-group">
                <label class="form-label" for="serial_number">シリアル番号・製造番号</label>
                <input type="text" id="serial_number" name="serial_number"
                       class="form-control <?= !empty($errors['serial_number']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($input['serial_number'] ?? $ledger['serial_number'] ?? '') ?>"
                       maxlength="100" placeholder="例：C02XL0GWJGH5（任意・検索に使用できます）">
                <?php if (!empty($errors['serial_number'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['serial_number']) ?></div>
                <?php endif; ?>
            </div>

            <div class="form-row form-row-3">
                <!-- 数量 -->
                <div class="form-group">
                    <label class="form-label" for="quantity">
                        数量 <span class="required">*</span>
                    </label>
                    <input type="number" id="quantity" name="quantity"
                           class="form-control <?= !empty($errors['quantity']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['quantity'] ?? $ledger['quantity'] ?? '1') ?>"
                           min="1" required>
                    <?php if (!empty($errors['quantity'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['quantity']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 取引金額 -->
                <div class="form-group">
                    <label class="form-label" for="transaction_amount">
                        取引金額（円） <span class="required">*</span>
                    </label>
                    <input type="number" id="transaction_amount" name="transaction_amount"
                           class="form-control <?= !empty($errors['transaction_amount']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['transaction_amount'] ?? $ledger['transaction_amount'] ?? '') ?>"
                           min="1" placeholder="例：10000" required>
                    <?php if (!empty($errors['transaction_amount'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['transaction_amount']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 販売予定価格（任意・POSレジの単価の初期値） -->
                <div class="form-group">
                    <label class="form-label" for="sale_price">販売予定価格（円・任意）</label>
                    <input type="text" id="sale_price" name="sale_price" inputmode="numeric" maxlength="15"
                           class="form-control <?= !empty($errors['sale_price']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars((string)($input['sale_price'] ?? $ledger['sale_price'] ?? '')) ?>"
                           placeholder="例：15000">
                    <div class="form-hint">POSレジでカートに入れたときの単価に自動入力されます（1点あたり）。</div>
                    <?php if (!empty($errors['sale_price'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['sale_price']) ?></div>
                    <?php endif; ?>
                </div>
            </div>

        </div>
    </div>

    <!-- ============================================================
         相手方情報セクション
    ============================================================ -->
    <div class="card">
        <div class="card__header">相手方情報</div>
        <div class="card__body">

            <!-- 会員番号による紐付け・引用（任意） -->
            <?php
            $cpType = $input['counterpart_type'] ?? $ledger['counterpart_type'] ?? 'individual';
            ?>
            <div class="form-group">
                <label class="form-label" for="member_code">会員番号（任意）</label>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                    <input type="text" id="member_code" name="member_code"
                           class="form-control <?= !empty($errors['member_code']) ? 'is-invalid' : '' ?>"
                           style="max-width:220px;"
                           value="<?= htmlspecialchars($input['member_code'] ?? $ledger['member_code'] ?? '') ?>"
                           maxlength="50" placeholder="例：M-0001">
                    <button type="button" id="member_lookup_btn" class="btn btn-secondary">会員情報を引用</button>
                </div>
                <div class="form-hint">会員管理に登録済みの会員番号を入力して「会員情報を引用」を押すと、相手方情報・本人確認情報が自動入力されます。</div>
                <div id="member_lookup_msg" class="form-hint" style="display:none;"></div>
                <?php if (!empty($errors['member_code'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['member_code']) ?></div>
                <?php endif; ?>
                <?php if (!$isEdit): ?>
                <label style="display:flex; align-items:center; gap:6px; margin-top:8px; cursor:pointer; font-size:.85rem;">
                    <input type="checkbox" id="register_member" name="register_member" value="1"
                           <?= !empty($input['register_member']) ? 'checked' : '' ?>>
                    この相手方を新規会員として登録する（下に入力した相手方情報で会員を作成します）
                </label>
                <div class="form-hint" style="margin-left:22px;">
                    上の会員番号が未入力の場合は自動で採番、入力済みでその番号が未登録の場合はその番号で登録します。既に登録済みの番号なら会員登録はスキップされます。
                </div>
                <?php endif; ?>
            </div>

            <!-- 個人／法人切り替え -->
            <div class="form-group">
                <label class="form-label">相手方区分 <span class="required">*</span></label>
                <div style="display:flex; gap:20px;">
                    <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                        <input type="radio" name="counterpart_type" value="individual"
                               <?= $cpType !== 'corporate' ? 'checked' : '' ?>> 個人
                    </label>
                    <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                        <input type="radio" name="counterpart_type" value="corporate"
                               <?= $cpType === 'corporate' ? 'checked' : '' ?>> 法人
                    </label>
                </div>
            </div>

            <div class="form-row form-row-2">
                <!-- 氏名／名称 -->
                <div class="form-group">
                    <label class="form-label" for="counterpart_name">
                        <span id="counterpart_name_label"><?= $cpType === 'corporate' ? '名称（会社名）' : '氏名' ?></span>
                        <span class="required">*</span>
                    </label>
                    <input type="text" id="counterpart_name" name="counterpart_name" maxlength="255"
                           class="form-control <?= !empty($errors['counterpart_name']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['counterpart_name'] ?? $ledger['counterpart_name'] ?? '') ?>"
                           placeholder="例：山田 太郎" required>
                    <?php if (!empty($errors['counterpart_name'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['counterpart_name']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 職業（個人のみ） -->
                <div class="form-group" id="occupation_wrap" style="<?= $cpType === 'corporate' ? 'display:none;' : '' ?>">
                    <label class="form-label" for="counterpart_occupation">
                        職業 <span class="required">*</span>
                    </label>
                    <input type="text" id="counterpart_occupation" name="counterpart_occupation" maxlength="255"
                           class="form-control <?= !empty($errors['counterpart_occupation']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['counterpart_occupation'] ?? $ledger['counterpart_occupation'] ?? '') ?>"
                           placeholder="例：会社員">
                    <?php if (!empty($errors['counterpart_occupation'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['counterpart_occupation']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 担当者名（法人のみ） -->
                <div class="form-group" id="contact_name_wrap" style="<?= $cpType !== 'corporate' ? 'display:none;' : '' ?>">
                    <label class="form-label" for="counterpart_contact_name">
                        担当者名 <span class="required">*</span>
                    </label>
                    <input type="text" id="counterpart_contact_name" name="counterpart_contact_name" maxlength="255"
                           class="form-control <?= !empty($errors['counterpart_contact_name']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['counterpart_contact_name'] ?? $ledger['counterpart_contact_name'] ?? '') ?>"
                           placeholder="例：営業部 佐藤 花子">
                    <?php if (!empty($errors['counterpart_contact_name'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['counterpart_contact_name']) ?></div>
                    <?php endif; ?>
                </div>
            </div>

            <!-- 住所 -->
            <div class="form-group">
                <label class="form-label" for="counterpart_address">
                    <span id="counterpart_address_label"><?= $cpType === 'corporate' ? '所在地' : '住所' ?></span>
                    <span class="required">*</span>
                </label>
                <input type="text" id="counterpart_address" name="counterpart_address" maxlength="512"
                       class="form-control <?= !empty($errors['counterpart_address']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($input['counterpart_address'] ?? $ledger['counterpart_address'] ?? '') ?>"
                       placeholder="例：東京都新宿区西新宿1-1-1" required>
                <?php if (!empty($errors['counterpart_address'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['counterpart_address']) ?></div>
                <?php endif; ?>
            </div>

            <div class="form-row form-row-2">
                <!-- 年齢（個人のみ） -->
                <div class="form-group" id="age_wrap" style="<?= $cpType === 'corporate' ? 'display:none;' : '' ?>">
                    <label class="form-label" for="counterpart_age">
                        年齢 <span class="required">*</span>
                    </label>
                    <input type="number" id="counterpart_age" name="counterpart_age"
                           class="form-control <?= !empty($errors['counterpart_age']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['counterpart_age'] ?? $ledger['counterpart_age'] ?? '') ?>"
                           min="0" max="150" placeholder="例：35">
                    <?php if (!empty($errors['counterpart_age'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['counterpart_age']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 電話番号 -->
                <div class="form-group">
                    <label class="form-label" for="counterpart_phone">電話番号</label>
                    <input type="text" id="counterpart_phone" name="counterpart_phone" maxlength="20"
                           class="form-control <?= !empty($errors['counterpart_phone']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['counterpart_phone'] ?? $ledger['counterpart_phone'] ?? '') ?>"
                           placeholder="例：090-1234-5678">
                    <?php if (!empty($errors['counterpart_phone'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['counterpart_phone']) ?></div>
                    <?php endif; ?>
                </div>
            </div>

            <!-- 取引アカウント（任意） -->
            <div class="form-group">
                <label class="form-label" for="counterpart_account">取引アカウント</label>
                <input type="text" id="counterpart_account" name="counterpart_account"
                       class="form-control <?= !empty($errors['counterpart_account']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($input['counterpart_account'] ?? $ledger['counterpart_account'] ?? '') ?>"
                       maxlength="255" placeholder="例：メルカリ @user123 / ヤフオク example_id（オンライン買付時のID等・任意）">
                <?php if (!empty($errors['counterpart_account'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['counterpart_account']) ?></div>
                <?php endif; ?>
            </div>

            <!-- 備考（任意） -->
            <div class="form-group">
                <label class="form-label" for="counterpart_note">備考</label>
                <textarea id="counterpart_note" name="counterpart_note"
                          class="form-control <?= !empty($errors['counterpart_note']) ? 'is-invalid' : '' ?>"
                          rows="2" placeholder="相手方に関する特記事項があれば入力してください（任意）"><?= htmlspecialchars($input['counterpart_note'] ?? $ledger['counterpart_note'] ?? '') ?></textarea>
                <?php if (!empty($errors['counterpart_note'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['counterpart_note']) ?></div>
                <?php endif; ?>
            </div>

        </div>
    </div>

    <!-- ============================================================
         本人確認情報セクション
    ============================================================ -->
<?php $maxUploadMb = (int)floor(((require __DIR__ . '/../../config/config.php')['max_file_size'] ?? 52428800) / 1048576); ?>
    <div class="card">
        <div class="card__header">本人確認情報</div>
        <div class="card__body">

            <div class="form-row form-row-2">
                <!-- 確認書類種別 -->
                <div class="form-group">
                    <label class="form-label" for="id_document_type">
                        確認書類種別
                    </label>
                    <?php
                    // 選択状態: 再表示時は入力値、編集時は登録値（未登録＝NULL は「未登録」）、新規は未選択。
                    // 以前は編集時に未登録の台帳を開くと「-- 選択してください --」が選ばれ、
                    // そのまま保存すると「本人確認書類種別の値が不正です」となって保存できなかった
                    if (array_key_exists('id_document_type', $input) && $input['id_document_type'] !== null) {
                        $selDoc = (string)$input['id_document_type'];
                    } elseif ($isEdit) {
                        $selDoc = (string)($ledger['id_document_type'] ?? '');
                    } else {
                        $selDoc = '__unset';
                    }
                    ?>
                    <select id="id_document_type" name="id_document_type"
                            class="form-control <?= !empty($errors['id_document_type']) ? 'is-invalid' : '' ?>">
                        <option value="__unset" <?= $selDoc === '__unset' ? 'selected' : '' ?>>-- 選択してください --</option>
                        <option value="" <?= $selDoc === '' ? 'selected' : '' ?>>未登録（本人確認をスキップ）</option>
                        <option value="driver_license"    <?= $selDoc === 'driver_license' ? 'selected' : '' ?>>運転免許証</option>
                        <option value="my_number"         <?= $selDoc === 'my_number' ? 'selected' : '' ?>>マイナンバーカード</option>
                        <option value="passport"          <?= $selDoc === 'passport' ? 'selected' : '' ?>>パスポート</option>
                        <option value="health_insurance"  <?= $selDoc === 'health_insurance' ? 'selected' : '' ?>>健康保険証</option>
                        <option value="residence_card"    <?= $selDoc === 'residence_card' ? 'selected' : '' ?>>住民基本台帳カード</option>
                        <option value="residence_status"  <?= $selDoc === 'residence_status' ? 'selected' : '' ?>>在留カード</option>
                        <option value="special_permanent" <?= $selDoc === 'special_permanent' ? 'selected' : '' ?>>特別永住者証明書</option>
                        <option value="other"             <?= $selDoc === 'other' ? 'selected' : '' ?>>その他</option>
                    </select>
                    <?php if (!empty($errors['id_document_type'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['id_document_type']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 書類番号・記号 -->
                <div class="form-group">
                    <label class="form-label" for="id_document_number">
                        書類番号・記号
                    </label>
                    <input type="text" id="id_document_number" name="id_document_number" maxlength="64"
                           class="form-control <?= !empty($errors['id_document_number']) ? 'is-invalid' : '' ?>"
                           value="<?= htmlspecialchars($input['id_document_number'] ?? $ledger['id_document_number'] ?? '') ?>"
                           placeholder="免許証番号・証明書番号等（任意）">
                    <div class="form-hint" id="mynumber_hint" style="display:none; color:#c0392b;">
                        &#9888; マイナンバーカードの個人番号は法令上記録できないため、番号欄は入力できません。
                    </div>
                    <?php if (!empty($errors['id_document_number'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['id_document_number']) ?></div>
                    <?php endif; ?>
                </div>
            </div>

            <!-- 書類種別補足（other選択時に表示） -->
            <div class="form-group" id="id_document_type_note_wrap"
                 style="<?= $selDoc !== 'other' ? 'display:none;' : '' ?>">
                <label class="form-label" for="id_document_type_note">確認書類の内容 <span class="required">*</span></label>
                <input type="text" id="id_document_type_note" name="id_document_type_note" maxlength="255"
                       class="form-control <?= !empty($errors['id_document_type_note']) ? 'is-invalid' : '' ?>"
                       value="<?= htmlspecialchars($input['id_document_type_note'] ?? $ledger['id_document_type_note'] ?? '') ?>"
                       placeholder="例：社員証（顔写真付き）・学生証 など">
                <?php if (!empty($errors['id_document_type_note'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['id_document_type_note']) ?></div>
                <?php endif; ?>
            </div>

            <div class="form-row form-row-2">
                <!-- 本人確認書類スキャン -->
                <div class="form-group">
                    <label class="form-label" for="id_document_file">
                        本人確認書類スキャンデータ
                    </label>
                    <?php if ($isEdit && !empty($ledger['has_id_document'])): ?>
                        <div class="mb-8">
                            <a href="/index.php?page=file.download&id=<?= (int)$ledger['id'] ?>&type=id_document"
                               class="btn btn-outline btn-sm">
                                &#128196; 登録済みのファイルをダウンロード
                            </a>
                            <div class="form-hint">新しいファイルを選択すると追加で保存され、詳細画面では最新のファイルが表示されます（任意）。</div>
                        </div>
                    <?php endif; ?>
                    <input type="file" id="id_document_file" name="id_document_file"
                           class="form-control <?= !empty($errors['id_document_file']) ? 'is-invalid' : '' ?>"
                           accept="image/jpeg,image/png,image/gif,image/webp,application/pdf">
                    <div class="form-hint">JPEG・PNG・GIF・WebP・PDF（最大<?= $maxUploadMb ?>MB）。本人確認をスキップする場合は不要です。</div>
                    <?php if (!empty($errors['id_document_file'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['id_document_file']) ?></div>
                    <?php endif; ?>
                </div>

                <!-- 買取受付表スキャン -->
                <div class="form-group">
                    <label class="form-label" for="receipt_form_file">買取受付表スキャンデータ</label>
                    <?php if ($isEdit && !empty($ledger['has_receipt_form'])): ?>
                        <div class="mb-8">
                            <a href="/index.php?page=file.download&id=<?= (int)$ledger['id'] ?>&type=receipt_form"
                               class="btn btn-outline btn-sm">
                                &#128196; 登録済みのファイルをダウンロード
                            </a>
                            <div class="form-hint">新しいファイルを選択すると追加で保存され、詳細画面では最新のファイルが表示されます（任意）。</div>
                        </div>
                    <?php endif; ?>
                    <input type="file" id="receipt_form_file" name="receipt_form_file"
                           class="form-control <?= !empty($errors['receipt_form_file']) ? 'is-invalid' : '' ?>"
                           accept="image/jpeg,image/png,image/gif,image/webp,application/pdf">
                    <div class="form-hint">JPEG・PNG・GIF・WebP・PDF（最大<?= $maxUploadMb ?>MB）</div>
                    <?php if (!empty($errors['receipt_form_file'])): ?>
                        <div class="form-error"><?= htmlspecialchars($errors['receipt_form_file']) ?></div>
                    <?php endif; ?>
                </div>
            </div>

            <!-- 商品画像（複数・任意） -->
            <div class="form-group">
                <label class="form-label" for="item_photos">商品画像</label>
                <?php if ($isEdit && !empty($itemPhotoCount)): ?>
                    <div class="form-hint mb-8">現在 <?= (int)$itemPhotoCount ?> 点登録済み（詳細画面で確認できます）。追加でアップロードできます。</div>
                <?php endif; ?>
                <input type="file" id="item_photos" name="item_photos[]"
                       class="form-control <?= !empty($errors['item_photos']) ? 'is-invalid' : '' ?>"
                       accept="image/jpeg,image/png,image/gif,image/webp" multiple>
                <div class="form-hint">JPEG・PNG・GIF・WebP／1点あたり25MBまで・1件の台帳につき最大20点（複数選択可）</div>
                <?php if (!empty($errors['item_photos'])): ?>
                    <div class="form-error"><?= htmlspecialchars($errors['item_photos']) ?></div>
                <?php endif; ?>
            </div>

        </div>
    </div>

    <!-- フォームアクション -->
    <div class="d-flex gap-8" style="justify-content: flex-end; margin-bottom: 24px;">
        <a href="/index.php?page=ledger" class="btn btn-secondary">キャンセル</a>
        <button type="submit" class="btn btn-primary">
            <?= $isEdit ? '変更を保存する' : '登録する' ?>
        </button>
    </div>

</form>

<script>
(function () {
    'use strict';

    /* 取引種別 → その他補足欄の表示切替 */
    var transType     = document.getElementById('transaction_type');
    var transNoteWrap = document.getElementById('transaction_type_note_wrap');
    var transNote     = document.getElementById('transaction_type_note');

    function toggleTransNote() {
        var show = transType.value === 'other';
        transNoteWrap.style.display = show ? '' : 'none';
        if (!show) transNote.value = '';
    }
    if (transType) {
        transType.addEventListener('change', toggleTransNote);
    }

    /* 古物の種類「その他」で自由記述欄を表示 */
    var catType     = document.getElementById('item_category');
    var catNoteWrap = document.getElementById('item_category_note_wrap');
    var catNote     = document.getElementById('item_category_note');

    function toggleCatNote() {
        var show = catType.value === 'other';
        catNoteWrap.style.display = show ? '' : 'none';
        if (!show) catNote.value = '';
    }
    if (catType && catNoteWrap && catNote) {
        catType.addEventListener('change', toggleCatNote);
    }

    /* ============ 個人／法人切り替え ============ */
    function currentCpType() {
        var checked = document.querySelector('input[name="counterpart_type"]:checked');
        return checked ? checked.value : 'individual';
    }
    function toggleCpType() {
        var corporate = currentCpType() === 'corporate';
        var occWrap   = document.getElementById('occupation_wrap');
        var ageWrap   = document.getElementById('age_wrap');
        var conWrap   = document.getElementById('contact_name_wrap');
        var nameLabel = document.getElementById('counterpart_name_label');
        var addrLabel = document.getElementById('counterpart_address_label');
        var nameInput = document.getElementById('counterpart_name');
        if (occWrap) occWrap.style.display = corporate ? 'none' : '';
        if (ageWrap) ageWrap.style.display = corporate ? 'none' : '';
        if (conWrap) conWrap.style.display = corporate ? '' : 'none';
        if (nameLabel) nameLabel.textContent = corporate ? '名称（会社名）' : '氏名';
        if (addrLabel) addrLabel.textContent = corporate ? '所在地' : '住所';
        if (nameInput) nameInput.placeholder = corporate ? '例：株式会社〇〇商事' : '例：山田 太郎';
    }
    var cpRadios = document.querySelectorAll('input[name="counterpart_type"]');
    for (var r = 0; r < cpRadios.length; r++) {
        cpRadios[r].addEventListener('change', toggleCpType);
    }

    /* ============ 会員情報の引用 ============ */
    var lookupBtn = document.getElementById('member_lookup_btn');
    if (lookupBtn) {
        lookupBtn.addEventListener('click', function () {
            var code = (document.getElementById('member_code').value || '').trim();
            var msg  = document.getElementById('member_lookup_msg');
            function showMsg(text, ok) {
                if (!msg) return;
                msg.style.display = '';
                msg.style.color = ok ? '#27ae60' : '#c0392b';
                msg.textContent = text;
            }
            if (code === '') { showMsg('会員番号を入力してください。', false); return; }

            var xhr = new XMLHttpRequest();
            xhr.open('GET', '/index.php?page=member.lookup&code=' + encodeURIComponent(code), true);
            xhr.onreadystatechange = function () {
                if (xhr.readyState !== 4) return;
                var data;
                try { data = JSON.parse(xhr.responseText); } catch (e) { showMsg('引用に失敗しました。', false); return; }
                if (!data.found) { showMsg(data.message || '会員が見つかりません。', false); return; }
                var m = data.member;
                // 区分ラジオ
                for (var i = 0; i < cpRadios.length; i++) {
                    cpRadios[i].checked = (cpRadios[i].value === m.counterpart_type);
                }
                toggleCpType();
                function setVal(id, v) { var el = document.getElementById(id); if (el) el.value = v || ''; }
                setVal('counterpart_name', m.name);
                setVal('counterpart_address', m.address);
                setVal('counterpart_occupation', m.occupation);
                setVal('counterpart_age', m.age);
                setVal('counterpart_phone', m.phone);
                setVal('counterpart_contact_name', m.contact_name);
                setVal('counterpart_account', m.account);
                var docSel = document.getElementById('id_document_type');
                if (docSel) { docSel.value = m.id_document_type || ''; docSel.dispatchEvent(new Event('change')); }
                // 本人確認書類番号は個人情報保護のため会員引用では自動入力しない
                // （必要な場合は書類を確認のうえ手入力する）。
                showMsg('会員「' + m.name + '」の情報を引用しました。', true);
            };
            xhr.send();
        });
    }

    /* ============ マイナンバーカード選択時は番号欄を無効化（入力不可） ============ */
    var docTypeSel = document.getElementById('id_document_type');
    var mnHint     = document.getElementById('mynumber_hint');
    var docNumIn   = document.getElementById('id_document_number');
    function toggleMnHint() {
        var isMn   = docTypeSel && docTypeSel.value === 'my_number';
        var isSkip = docTypeSel && (docTypeSel.value === '' || docTypeSel.value === '__unset');
        if (mnHint) mnHint.style.display = isMn ? '' : 'none';
        if (docNumIn) {
            docNumIn.disabled = isMn || isSkip;
            if (isMn || isSkip) {
                docNumIn.value = '';
                docNumIn.placeholder = isMn ? 'マイナンバーカードの番号は記録できません' : '確認書類種別を選択すると入力できます';
                docNumIn.style.background = '#e9ecef';
                docNumIn.style.cursor = 'not-allowed';
            } else {
                docNumIn.placeholder = '免許証番号・証明書番号等（任意）';
                docNumIn.style.background = '';
                docNumIn.style.cursor = '';
            }
        }
    }
    if (docTypeSel) {
        docTypeSel.addEventListener('change', toggleMnHint);
        toggleMnHint();
    }

    /* ============ 本人確認スキップ時の確認アラート ============ */
    var ledgerForm = document.querySelector('form[action*="ledger."]');
    if (ledgerForm && docTypeSel) {
        ledgerForm.addEventListener('submit', function (e) {
            var fileInput = document.getElementById('id_document_file');
            var hasFile   = fileInput && fileInput.files && fileInput.files.length > 0;
            if (docTypeSel.value === '__unset') {
                // 種別か「未登録」のどちらかを明示的に選んでもらう（サーバー側でも同じ検証を行う）
                e.preventDefault();
                window.alert('本人確認情報の「確認書類種別」を選択してください。\n本人確認をしない場合は「未登録（本人確認をスキップ）」を選択します。');
                docTypeSel.focus();
                return;
            }
            if (docTypeSel.value === '' && !hasFile) {
                if (!window.confirm('本人確認情報が未登録です。\n古物営業法上、1万円以上の買受け等では相手方の確認が義務付けられています。\nこのまま登録しますか？')) {
                    e.preventDefault();
                }
            }
        });
    }

    /* 確認書類種別 → その他補足欄の表示切替 */
    var docType     = document.getElementById('id_document_type');
    var docNoteWrap = document.getElementById('id_document_type_note_wrap');
    var docNote     = document.getElementById('id_document_type_note');

    function toggleDocNote() {
        var show = docType.value === 'other';
        docNoteWrap.style.display = show ? '' : 'none';
        if (!show) docNote.value = '';
    }
    if (docType) {
        docType.addEventListener('change', toggleDocNote);
    }
}());
</script>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
