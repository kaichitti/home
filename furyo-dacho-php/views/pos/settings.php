<?php
/**
 * POS設定（この端末のレシートプリンタ ＋ 店舗・レシート・消費税設定）
 *
 * 変数: $settings, $isAdmin, $errors, $csrf_token
 */
$pageTitle  = 'POS設定・プリンタ - 古物台帳管理システム';
$activePage = 'pos.settings';
$h = static fn ($v): string => htmlspecialchars((string)$v, ENT_QUOTES, 'UTF-8');
$errors = $errors ?? [];
$dis = !empty($isAdmin) ? '' : ' disabled';

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">POS設定・プリンタ</h1>
    <div class="page-header__actions">
        <a href="/index.php?page=pos" class="btn btn-secondary">POSレジへ戻る</a>
    </div>
</div>

<!-- ============================================================
     この端末のレシートプリンタ（ブラウザに保存）
============================================================ -->
<div class="card">
    <div class="card__header">この端末の設定（レジ番号・レシートプリンタ）</div>
    <div class="card__body">
        <p class="text-muted" style="font-size:.82rem; margin-bottom:12px;">
            プリンタの設定はこの端末（このブラウザ）ごとに保存されます。レジとして使う端末それぞれで設定してください。<br>
            プリンタが接続されていない状態で会計すると確認ダイアログが表示され、「許可」すると決済を完了してレシートを画面に発行します。
        </p>
        <div id="prn_env" class="alert alert-warning" style="display:none;"></div>

        <div class="form-group" style="max-width:360px;">
            <label class="form-label" for="prn_register">この端末のレジ番号</label>
            <div style="display:flex; align-items:center; gap:8px;">
                <span>レジ</span>
                <input type="text" id="prn_register" class="form-control" inputmode="numeric" maxlength="2" style="width:80px; text-align:center;">
                <span class="text-muted" style="font-size:.8rem;">（1〜99）</span>
            </div>
            <div class="form-hint">レシートに「レジ01」のように印字され、取引履歴・レジ明細・レジ精算をレジ別に絞り込めます。レジが複数ある場合は端末ごとに別の番号を設定してください。</div>
        </div>

        <div class="form-group">
            <div class="form-label">接続方式</div>
            <label class="prn-opt"><input type="radio" name="prn_mode" value="none">
                <span><b>プリンタなし</b><br><small>会計のたびに「プリンタ未接続」の確認が表示され、レシートは画面に発行されます。</small></span></label>
            <label class="prn-opt"><input type="radio" name="prn_mode" value="browser">
                <span><b>ブラウザ印刷（パソコンにインストールしたプリンタ）</b><br><small>メーカーのドライバでOSに登録したレシートプリンタ・LANプリンタ等。印刷ダイアログから印刷します。ブラウザからは接続状態を確認できないため、常に「接続あり」として扱います。</small></span></label>
            <label class="prn-opt"><input type="radio" name="prn_mode" value="usb">
                <span><b>USB直結（ESC/POS対応のレシートプリンタ）</b><br><small>Chrome / Edge で https のURLから開いている場合に利用できます。接続状態を自動で確認し、印刷・自動カット・キャッシュドロワーの開放を行います。</small></span></label>
            <label class="prn-opt"><input type="radio" name="prn_mode" value="serial">
                <span><b>シリアル / Bluetooth（ESC/POS対応）</b><br><small>USB-シリアル変換やBluetooth（SPP）で接続したプリンタ。Chrome / Edge・https が必要です。</small></span></label>
        </div>

        <div id="prn_usb_box" class="prn-sub" style="display:none;">
            <button type="button" class="btn btn-accent btn-sm" id="prn_usb_pick">USBプリンタを選択…</button>
            <span id="prn_usb_name" class="text-muted" style="margin-left:8px;"></span>
            <div class="form-hint">Windows でメーカーのドライバがインストール済みの場合、USB直結では使えないことがあります。その場合は「ブラウザ印刷」を選ぶか、メーカーのユーティリティで WinUSB ドライバに切り替えてください。</div>
        </div>
        <div id="prn_serial_box" class="prn-sub" style="display:none;">
            <button type="button" class="btn btn-accent btn-sm" id="prn_serial_pick">ポートを選択…</button>
            <span id="prn_serial_name" class="text-muted" style="margin-left:8px;"></span>
            <div style="display:flex; gap:12px; align-items:center; margin-top:8px; flex-wrap:wrap;">
                <label>通信速度
                    <select id="prn_baud" class="form-control" style="display:inline-block; width:auto;">
                        <option>9600</option><option>19200</option><option>38400</option><option>57600</option><option>115200</option>
                    </select> bps</label>
                <label><input type="checkbox" id="prn_flow"> ハードウェアフロー制御（RTS/CTS）</label>
            </div>
        </div>

        <div class="form-row form-row-2" style="margin-top:12px;">
            <div class="form-group">
                <label class="form-label" for="prn_paper">用紙幅</label>
                <select id="prn_paper" class="form-control">
                    <option value="80">80mm</option>
                    <option value="58">58mm</option>
                </select>
            </div>
            <div class="form-group">
                <div class="form-label">オプション（USB / シリアルのみ）</div>
                <label style="display:block;"><input type="checkbox" id="prn_cut"> 印刷後に自動カット</label>
                <label style="display:block;"><input type="checkbox" id="prn_drawer"> 現金会計時にキャッシュドロワーを開く</label>
            </div>
        </div>

        <div id="prn_state" class="alert alert-info" style="white-space:pre-wrap;">確認中…</div>

        <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button type="button" class="btn btn-primary" id="prn_save">この端末に保存</button>
            <button type="button" class="btn btn-outline" id="prn_check">接続を確認</button>
            <button type="button" class="btn btn-outline" id="prn_test">テスト印刷</button>
            <button type="button" class="btn btn-outline" id="prn_drawer_test">ドロワーを開く</button>
        </div>
    </div>
</div>

<!-- ============================================================
     店舗・レシート・消費税（テナント共通・管理者が設定）
============================================================ -->
<div class="card">
    <div class="card__header">店舗・レシート・消費税の設定<?= empty($isAdmin) ? '（閲覧のみ・変更は管理者）' : '' ?></div>
    <div class="card__body">
        <?php if ($errors !== []): ?>
            <div class="alert alert-danger">入力内容を確認してください。</div>
        <?php endif; ?>
        <form method="POST" action="/index.php?page=pos.settings.save">
            <input type="hidden" name="_csrf_token" value="<?= $h($csrf_token ?? '') ?>">

            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="store_name">店舗名（レシートに印字）</label>
                    <input type="text" id="store_name" name="store_name" class="form-control<?= isset($errors['store_name']) ? ' is-invalid' : '' ?>"
                           maxlength="100" value="<?= $h($settings['store_name_raw'] ?? '') ?>" placeholder="<?= $h($settings['tenant_name'] ?? '') ?>"<?= $dis ?>>
                    <div class="form-hint">空欄の場合は事業者名（<?= $h($settings['tenant_name'] ?? '') ?>）を印字します。</div>
                    <?php if (isset($errors['store_name'])): ?><div class="form-error"><?= $h($errors['store_name']) ?></div><?php endif; ?>
                </div>
                <div class="form-group">
                    <label class="form-label" for="store_phone">電話番号</label>
                    <input type="text" id="store_phone" name="store_phone" class="form-control<?= isset($errors['store_phone']) ? ' is-invalid' : '' ?>"
                           maxlength="30" value="<?= $h($settings['store_phone'] ?? '') ?>" placeholder="例：03-1234-5678"<?= $dis ?>>
                    <?php if (isset($errors['store_phone'])): ?><div class="form-error"><?= $h($errors['store_phone']) ?></div><?php endif; ?>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label" for="store_address">住所</label>
                <input type="text" id="store_address" name="store_address" class="form-control<?= isset($errors['store_address']) ? ' is-invalid' : '' ?>"
                       maxlength="255" value="<?= $h($settings['store_address'] ?? '') ?>"<?= $dis ?>>
                <?php if (isset($errors['store_address'])): ?><div class="form-error"><?= $h($errors['store_address']) ?></div><?php endif; ?>
            </div>
            <div class="form-group">
                <label class="form-label" for="invoice_number">適格請求書発行事業者の登録番号（インボイス）</label>
                <input type="text" id="invoice_number" name="invoice_number" class="form-control<?= isset($errors['invoice_number']) ? ' is-invalid' : '' ?>"
                       maxlength="20" value="<?= $h($settings['invoice_number'] ?? '') ?>" placeholder="例：T1234567890123"<?= $dis ?>>
                <div class="form-hint">登録している場合に入力すると、レシートが適格簡易請求書の記載事項（登録番号・税率ごとの対象額と消費税額）を満たします。</div>
                <?php if (isset($errors['invoice_number'])): ?><div class="form-error"><?= $h($errors['invoice_number']) ?></div><?php endif; ?>
            </div>

            <div class="form-row form-row-3">
                <div class="form-group">
                    <label class="form-label" for="tax_rate">消費税率（%）</label>
                    <input type="text" id="tax_rate" name="tax_rate" class="form-control<?= isset($errors['tax_rate']) ? ' is-invalid' : '' ?>"
                           inputmode="numeric" maxlength="2" value="<?= $h($settings['tax_rate'] ?? 10) ?>"<?= $dis ?>>
                    <div class="form-hint">免税事業者等で表示しない場合は 0</div>
                    <?php if (isset($errors['tax_rate'])): ?><div class="form-error"><?= $h($errors['tax_rate']) ?></div><?php endif; ?>
                </div>
                <div class="form-group">
                    <label class="form-label" for="tax_mode">価格の入力</label>
                    <select id="tax_mode" name="tax_mode" class="form-control"<?= $dis ?>>
                        <?php foreach (\FuryoDacho\Models\PosSetting::TAX_MODES as $k => $label): ?>
                            <option value="<?= $h($k) ?>" <?= ($settings['tax_mode'] ?? '') === $k ? 'selected' : '' ?>><?= $h($label) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label" for="tax_rounding">消費税の端数処理</label>
                    <select id="tax_rounding" name="tax_rounding" class="form-control"<?= $dis ?>>
                        <?php foreach (\FuryoDacho\Models\PosSetting::TAX_ROUNDINGS as $k => $label): ?>
                            <option value="<?= $h($k) ?>" <?= ($settings['tax_rounding'] ?? '') === $k ? 'selected' : '' ?>><?= $h($label) ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
            </div>

            <div class="form-row form-row-2">
                <div class="form-group">
                    <label class="form-label" for="receipt_header">レシート上部メッセージ</label>
                    <textarea id="receipt_header" name="receipt_header" class="form-control" maxlength="200" rows="2"<?= $dis ?>><?= $h($settings['receipt_header'] ?? '') ?></textarea>
                    <?php if (isset($errors['receipt_header'])): ?><div class="form-error"><?= $h($errors['receipt_header']) ?></div><?php endif; ?>
                </div>
                <div class="form-group">
                    <label class="form-label" for="receipt_footer">レシート下部メッセージ</label>
                    <textarea id="receipt_footer" name="receipt_footer" class="form-control" maxlength="200" rows="2"<?= $dis ?>><?= $h($settings['receipt_footer'] ?? '') ?></textarea>
                    <div class="form-hint">例：返品・交換はレシートご持参のうえ7日以内にお願いします。</div>
                    <?php if (isset($errors['receipt_footer'])): ?><div class="form-error"><?= $h($errors['receipt_footer']) ?></div><?php endif; ?>
                </div>
            </div>
            <div class="form-group" style="max-width:360px;">
                <label class="form-label" for="ryoshu_tadashi">領収書の但し書き（既定）</label>
                <input type="text" id="ryoshu_tadashi" name="ryoshu_tadashi" class="form-control" maxlength="50" value="<?= $h($settings['ryoshu_tadashi'] ?? '') ?>" placeholder="お品代"<?= $dis ?>>
                <?php if (isset($errors['ryoshu_tadashi'])): ?><div class="form-error"><?= $h($errors['ryoshu_tadashi']) ?></div><?php endif; ?>
            </div>

            <?php if (!empty($isAdmin)): ?>
            <div class="form-actions">
                <button type="submit" class="btn btn-primary">保存する</button>
            </div>
            <p class="form-hint" style="margin-top:8px;">消費税の設定を変更した場合、開いているPOSレジ画面は再読み込みしてから会計してください（金額の不一致を検出して会計を止めます）。発行済みのレシートの内容は変わりません。</p>
            <?php endif; ?>
        </form>
    </div>
</div>

<style>
.prn-opt { display:flex; gap:10px; align-items:flex-start; padding:10px 12px; border:1px solid #dee2e6; border-radius:6px; margin-bottom:8px; cursor:pointer; }
.prn-opt input { margin-top:4px; }
.prn-opt small { color:#6c757d; }
.prn-sub { padding:10px 12px; background:#f4f6f9; border-radius:6px; margin-bottom:8px; }
</style>

<?php include __DIR__ . '/_printer.php'; ?>
<script>
(function () {
    'use strict';
    var P = window.FuryoPrinter;
    var $ = function (id) { return document.getElementById(id); };
    var cfg = P.load();

    function env() {
        var s = P.support(), msgs = [];
        if (!s.secure) { msgs.push('このページは https で開かれていないため、USB直結・シリアル接続は利用できません（ブラウザ印刷は利用できます）。'); }
        else if (!s.usb && !s.serial) { msgs.push('このブラウザはUSB直結・シリアル接続に対応していません。Chrome または Edge をご利用ください（ブラウザ印刷は利用できます）。'); }
        $('prn_env').textContent = msgs.join('\n');
        $('prn_env').style.display = msgs.length ? '' : 'none';
    }
    function readForm() {
        var m = document.querySelector('input[name=prn_mode]:checked');
        cfg.mode = m ? m.value : 'none';
        cfg.paper = $('prn_paper').value === '58' ? 58 : 80;
        cfg.autoCut = $('prn_cut').checked;
        cfg.drawer = $('prn_drawer').checked;
        cfg.baudRate = parseInt($('prn_baud').value, 10) || 38400;
        cfg.flowControl = $('prn_flow').checked ? 'hardware' : 'none';
        var reg = parseInt(String($('prn_register').value).replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); }), 10);
        cfg.registerNo = (reg >= 1 && reg <= 99) ? reg : 1;
        return cfg;
    }
    function fill() {
        Array.prototype.forEach.call(document.querySelectorAll('input[name=prn_mode]'), function (r) { r.checked = r.value === cfg.mode; });
        $('prn_paper').value = String(cfg.paper);
        $('prn_cut').checked = !!cfg.autoCut;
        $('prn_drawer').checked = !!cfg.drawer;
        $('prn_baud').value = String(cfg.baudRate || 38400);
        $('prn_flow').checked = cfg.flowControl === 'hardware';
        $('prn_register').value = String(cfg.registerNo || 1);
        $('prn_usb_name').textContent = cfg.usb ? '選択中: ' + cfg.usb.name : '未選択';
        $('prn_serial_name').textContent = cfg.serial ? '選択中: ' + cfg.serial.name : '未選択';
        toggle();
    }
    function toggle() {
        var m = (document.querySelector('input[name=prn_mode]:checked') || {}).value;
        $('prn_usb_box').style.display = m === 'usb' ? '' : 'none';
        $('prn_serial_box').style.display = m === 'serial' ? '' : 'none';
        var direct = m === 'usb' || m === 'serial';
        $('prn_drawer_test').style.display = direct ? '' : 'none';
        $('prn_cut').disabled = !direct;
        $('prn_drawer').disabled = !direct;
    }
    function state(msg, kind) {
        $('prn_state').className = 'alert alert-' + (kind || 'info');
        $('prn_state').textContent = msg;
    }
    function check() {
        state('確認中…');
        return P.check(readForm()).then(function (st) {
            if (cfg.mode === 'none') { state('プリンタなしに設定されています。会計時に確認ダイアログが表示されます。', 'warning'); }
            else if (st.connected && cfg.mode === 'browser') { state('ブラウザ印刷に設定されています（接続状態はブラウザから確認できません）。「テスト印刷」で印刷できることを確認してください。', 'info'); }
            else if (st.connected) { state('✓ 接続されています: ' + (st.label || ''), 'success'); }
            else { state('未接続: ' + (st.reason || ''), 'danger'); }
            return st;
        });
    }

    Array.prototype.forEach.call(document.querySelectorAll('input[name=prn_mode]'), function (r) {
        r.addEventListener('change', function () { toggle(); check(); });
    });
    $('prn_usb_pick').addEventListener('click', function () {
        P.pairUsb().then(function (dev) { cfg = Object.assign(readForm(), { usb: dev }); P.save(cfg); fill(); check(); },
            function (e) { if (e && e.name !== 'NotFoundError') { state('選択できませんでした: ' + (e.message || e), 'danger'); } });
    });
    $('prn_serial_pick').addEventListener('click', function () {
        P.pairSerial().then(function (port) { cfg = Object.assign(readForm(), { serial: port }); P.save(cfg); fill(); check(); },
            function (e) { if (e && e.name !== 'NotFoundError') { state('選択できませんでした: ' + (e.message || e), 'danger'); } });
    });
    $('prn_save').addEventListener('click', function () {
        P.save(readForm()) ? check().then(function () { $('prn_register').value = String(cfg.registerNo); $('prn_state').textContent = 'この端末に保存しました（' + P.registerLabel(cfg.registerNo) + '）。\n' + $('prn_state').textContent; })
                           : state('保存できませんでした（ブラウザの設定でサイトデータの保存が禁止されている可能性があります）。', 'danger');
    });
    $('prn_check').addEventListener('click', check);
    $('prn_test').addEventListener('click', function () {
        var c = readForm();
        P.save(c);
        check().then(function (st) {
            if (!st.connected) { return; }
            state('テスト印刷中…');
            P.printUrl('/index.php?page=pos.print.test').then(function () {
                state('✓ テスト印刷を送信しました。用紙に正しく印刷されたか確認してください。', 'success');
            }, function (e) { state('テスト印刷に失敗しました: ' + (e && e.message ? e.message : e), 'danger'); });
        });
    });
    $('prn_drawer_test').addEventListener('click', function () {
        P.save(readForm());
        P.openDrawer().then(function () { state('ドロワー開放の信号を送りました。', 'success'); },
            function (e) { state('送信に失敗しました: ' + (e && e.message ? e.message : e), 'danger'); });
    });

    env();
    fill();
    check();
}());
</script>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
