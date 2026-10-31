<?php
/**
 * POSレジ画面
 *
 * 変数: $settings（PosSetting::get）, $posUserKey, $isAdmin, $csrf_token
 */
$pageTitle  = 'POSレジ - 古物台帳管理システム';
$activePage = 'pos';

$jsFlags = JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_UNESCAPED_UNICODE;
$posConfig = [
    'csrf'      => $csrf_token ?? '',
    'userKey'   => $posUserKey ?? '',
    'taxRate'   => (int)$settings['tax_rate'],
    'taxMode'   => $settings['tax_mode'],
    'rounding'  => $settings['tax_rounding'],
    'tadashi'   => $settings['ryoshu_tadashi'],
];

ob_start();
?>

<div class="page-header">
    <h1 class="page-header__title">POSレジ</h1>
    <div class="page-header__actions">
        <a id="pos_register_badge" href="/index.php?page=pos.settings" class="pos-printer info" title="この端末のレジ番号（POS設定で変更）">レジ--</a>
        <a id="pos_printer_status" href="/index.php?page=pos.settings" class="pos-printer" title="プリンタ設定を開く">プリンタ確認中…</a>
        <button type="button" class="btn btn-outline" id="pos_lookup_btn" title="レシート番号・バーコードで取引を呼び出して明細表示・再印刷">レシート呼出</button>
        <button type="button" class="btn btn-secondary" id="pos_hold_btn" title="現在のカートを一時保留する">保留</button>
        <button type="button" class="btn btn-secondary" id="pos_recall_btn" title="保留したカートを呼び出す">呼出 <span id="pos_hold_count" class="badge badge-warning" style="display:none;"></span></button>
        <a href="/index.php?page=pos.history" class="btn btn-outline">取引履歴</a>
        <a href="/index.php?page=pos.daily" class="btn btn-outline">レジ精算</a>
    </div>
</div>

<div class="pos-grid" id="pos_grid">
    <!-- 左: 商品検索 -->
    <div class="card" style="margin-bottom:0;">
        <div class="card__header">商品検索 <span class="text-muted" style="font-size:.75rem; font-weight:400;">バーコード読取・Enterで追加</span></div>
        <div class="card__body">
            <input type="text" id="pos_search" class="form-control" autocomplete="off" autofocus
                   placeholder="品名・シリアル番号・台帳番号（空欄で最新30件）" maxlength="100">
            <div id="pos_search_msg" class="pos-msg" role="status" aria-live="polite"></div>
            <div id="pos_results" class="pos-results">
                <p class="text-muted" style="font-size:.85rem;">読み込み中...</p>
            </div>
        </div>
    </div>

    <!-- 右: お会計 -->
    <div class="card" style="margin-bottom:0;">
        <div class="card__header">
            お会計
            <button type="button" class="btn btn-secondary btn-sm" id="pos_clear">クリア</button>
        </div>
        <div class="card__body">
            <div id="pos_alert" class="alert alert-danger" style="display:none;" role="alert"></div>

            <div id="pos_cart">
                <p class="text-muted" style="font-size:.85rem;" id="pos_cart_empty">商品検索の一覧から商品をタップ、またはバーコードを読み取って追加してください。</p>
            </div>

            <div class="pos-totals">
                <div class="pos-trow"><span>小計（<span id="t_count">0</span>点）</span><span id="t_subtotal">¥0</span></div>
                <div class="pos-trow">
                    <span class="pos-disc">
                        値引
                        <select id="pos_disc_type" class="form-control">
                            <option value="none">なし</option>
                            <option value="amount">円</option>
                            <option value="percent">%</option>
                        </select>
                        <input type="text" id="pos_disc_value" class="form-control" inputmode="numeric" placeholder="0" disabled>
                    </span>
                    <span id="t_discount">-¥0</span>
                </div>
                <div class="pos-trow" id="t_tax_row"><span id="t_tax_label">内消費税等</span><span id="t_tax">¥0</span></div>
                <div class="pos-trow pos-total"><span>合計</span><span id="t_total">¥0</span></div>
            </div>

            <div class="pos-pay">
                <div class="form-label">支払方法</div>
                <div class="pos-methods" id="pos_methods">
                    <button type="button" data-method="cash" class="active">現金</button>
                    <button type="button" data-method="credit">クレジット</button>
                    <button type="button" data-method="emoney">電子マネー</button>
                    <button type="button" data-method="qr">QR決済</button>
                    <button type="button" data-method="other">その他</button>
                </div>
                <div id="pos_cash_box">
                    <div class="pos-tender">
                        <label for="pos_tendered" class="form-label" style="margin:0;">お預り</label>
                        <input type="text" id="pos_tendered" class="form-control" inputmode="numeric" placeholder="0">
                    </div>
                    <div class="pos-quick">
                        <button type="button" class="btn btn-outline btn-sm" data-tender="exact">ちょうど</button>
                        <button type="button" class="btn btn-outline btn-sm" data-tender="1000">+1,000</button>
                        <button type="button" class="btn btn-outline btn-sm" data-tender="5000">+5,000</button>
                        <button type="button" class="btn btn-outline btn-sm" data-tender="10000">+10,000</button>
                        <button type="button" class="btn btn-secondary btn-sm" data-tender="clear">クリア</button>
                    </div>
                    <div class="pos-trow pos-change"><span>お釣り</span><span id="t_change">¥0</span></div>
                </div>
                <div id="pos_ref_box" style="display:none;">
                    <label for="pos_ref" class="form-label">承認番号・伝票番号（任意）</label>
                    <input type="text" id="pos_ref" class="form-control" maxlength="100" placeholder="決済端末の控えに記載の番号">
                </div>
            </div>

            <div class="form-row form-row-2" style="margin-top:12px;">
                <div class="form-group" style="margin-bottom:8px;">
                    <label class="form-label" for="pos_member_code">会員（任意）</label>
                    <div id="pos_member_selected" class="pos-member-chip" style="display:none;">
                        <span id="pos_member_label"></span>
                        <a href="#" id="pos_member_link" target="_blank" rel="noopener" style="font-size:.78rem;">会員情報</a>
                        <button type="button" class="btn btn-secondary btn-sm" id="pos_member_clear" aria-label="会員の指定を解除">解除</button>
                    </div>
                    <div style="display:flex; gap:6px;" id="pos_member_input_row">
                        <input type="text" id="pos_member_code" class="form-control" maxlength="50" placeholder="会員番号・氏名・電話番号" autocomplete="off">
                        <button type="button" class="btn btn-secondary btn-sm" id="pos_member_lookup">検索</button>
                    </div>
                    <div id="pos_member_info" class="form-hint"></div>
                </div>
                <div class="form-group" style="margin-bottom:8px;">
                    <label class="form-label" for="pos_note">備考（任意）</label>
                    <input type="text" id="pos_note" class="form-control" maxlength="400" placeholder="例：店頭販売">
                </div>
            </div>

            <button type="button" class="btn btn-primary pos-checkout" id="pos_checkout">会計を確定する</button>
        </div>
    </div>
</div>

<!-- プリンタ未接続ダイアログ -->
<div class="modal-overlay" data-no-esc id="m_noprinter" role="dialog" aria-modal="true" aria-labelledby="m_noprinter_title">
    <div class="modal">
        <div class="modal__header">
            <span class="modal__title" id="m_noprinter_title">⚠ レシートプリンタが接続されていません</span>
        </div>
        <div class="modal__body">
            <p id="m_noprinter_reason" class="pos-reason"></p>
            <p style="margin:10px 0; font-weight:600;">レシートを印刷せずに決済を完了しますか？</p>
            <p class="text-muted" style="font-size:.82rem;">「許可して決済する」を押すと決済を完了し、レシートを画面に発行します。プリンタを接続した後、取引履歴からいつでも印刷できます。</p>
            <div class="pos-summary" id="m_noprinter_summary"></div>
        </div>
        <div class="modal__footer">
            <a href="/index.php?page=pos.settings" class="btn btn-outline" style="margin-right:auto;">プリンタ設定</a>
            <button type="button" class="btn btn-secondary" data-pos-cancel>キャンセル</button>
            <button type="button" class="btn btn-primary" id="m_noprinter_allow">許可して決済する</button>
        </div>
    </div>
</div>

<!-- 決済確認ダイアログ（プリンタ接続時） -->
<div class="modal-overlay" data-no-esc id="m_confirm" role="dialog" aria-modal="true" aria-labelledby="m_confirm_title">
    <div class="modal">
        <div class="modal__header"><span class="modal__title" id="m_confirm_title">決済を確定しますか？</span></div>
        <div class="modal__body">
            <div class="pos-summary" id="m_confirm_summary"></div>
            <p class="text-muted" style="font-size:.82rem; margin-top:10px;" id="m_confirm_printer"></p>
        </div>
        <div class="modal__footer">
            <button type="button" class="btn btn-secondary" data-pos-cancel>戻る</button>
            <button type="button" class="btn btn-primary" id="m_confirm_ok">決済を確定する</button>
        </div>
    </div>
</div>

<!-- 決済完了 -->
<div class="modal-overlay" data-no-esc id="m_done" role="dialog" aria-modal="true" aria-labelledby="m_done_title">
    <div class="modal" style="max-width:560px;">
        <div class="modal__header">
            <span class="modal__title" id="m_done_title">✓ 決済完了</span>
            <span class="text-muted" id="m_done_no" style="font-size:.85rem;"></span>
        </div>
        <div class="modal__body">
            <div id="m_done_amounts" class="pos-done-amounts"></div>
            <div id="m_done_status" class="alert alert-info" style="margin:12px 0 0;"></div>
            <div id="m_done_preview_wrap" style="display:none; margin-top:12px;">
                <iframe id="m_done_preview" title="レシート" class="pos-preview"></iframe>
            </div>
        </div>
        <div class="modal__footer" style="flex-wrap:wrap;">
            <button type="button" class="btn btn-outline" id="m_done_print">レシートを印刷</button>
            <button type="button" class="btn btn-outline" id="m_done_ryoshu">領収書を発行</button>
            <a href="#" class="btn btn-outline" id="m_done_show">取引詳細</a>
            <button type="button" class="btn btn-primary" id="m_done_next">次の会計へ</button>
        </div>
    </div>
</div>

<!-- 領収書 -->
<?php include __DIR__ . '/_ryoshu_modal.php'; ?>

<!-- 会員の選択 -->
<div class="modal-overlay" data-no-esc id="m_member" role="dialog" aria-modal="true" aria-labelledby="m_member_title">
    <div class="modal" style="max-width:560px;">
        <div class="modal__header">
            <span class="modal__title" id="m_member_title">会員を選択</span>
            <button type="button" class="modal__close" data-modal-close aria-label="閉じる">×</button>
        </div>
        <div class="modal__body">
            <div style="display:flex; gap:6px;">
                <input type="text" id="m_member_q" class="form-control" maxlength="50" placeholder="会員番号・氏名・電話番号（4桁以上）" autocomplete="off">
                <button type="button" class="btn btn-primary" id="m_member_go">検索</button>
            </div>
            <div id="m_member_list" style="margin-top:10px; max-height:360px; overflow-y:auto;"></div>
            <p style="margin-top:10px; font-size:.82rem;">
                <a href="/index.php?page=member.create" target="_blank" rel="noopener">＋ 新規会員登録（別タブで開きます。登録後にここで検索してください）</a>
            </p>
        </div>
    </div>
</div>

<!-- レシート番号で呼出 -->
<div class="modal-overlay" data-no-esc id="m_lookup" role="dialog" aria-modal="true" aria-labelledby="m_lookup_title">
    <div class="modal">
        <div class="modal__header">
            <span class="modal__title" id="m_lookup_title">レシートを呼び出す</span>
            <button type="button" class="modal__close" data-modal-close aria-label="閉じる">×</button>
        </div>
        <div class="modal__body">
            <label class="form-label" for="m_lookup_no">レシート番号（またはレシートのバーコードを読み取り）</label>
            <input type="text" id="m_lookup_no" class="form-control" maxlength="30" placeholder="例：20261023-0001 ／ 本日分は 12" autocomplete="off">
            <div id="m_lookup_msg" class="form-hint" style="margin-top:6px;"></div>
            <p class="text-muted" style="font-size:.8rem; margin-top:8px;">取引詳細で明細の確認・レシートの再印刷・領収書の発行・取消ができます。カートは保存されたまま戻れます。</p>
        </div>
        <div class="modal__footer">
            <button type="button" class="btn btn-secondary" data-modal-close>閉じる</button>
            <button type="button" class="btn btn-primary" id="m_lookup_go">明細を表示</button>
        </div>
    </div>
</div>

<!-- 保留一覧 -->
<div class="modal-overlay" data-no-esc id="m_holds" role="dialog" aria-modal="true" aria-labelledby="m_holds_title">
    <div class="modal">
        <div class="modal__header">
            <span class="modal__title" id="m_holds_title">保留中のカート</span>
            <button type="button" class="modal__close" data-modal-close aria-label="閉じる">×</button>
        </div>
        <div class="modal__body" id="m_holds_body"></div>
    </div>
</div>

<style>
.pos-grid { display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1.15fr); gap:16px; align-items:start; }
@media (max-width: 1000px) { .pos-grid { grid-template-columns: minmax(0, 1fr); } }
.pos-printer { display:inline-flex; align-items:center; gap:6px; padding:6px 12px; border-radius:16px; font-size:.8rem;
               font-weight:600; background:#e2e3e5; color:#383d41; text-decoration:none; }
.pos-printer:hover { text-decoration:none; opacity:.9; }
.pos-printer.ok { background:#d4edda; color:#155724; }
.pos-printer.ng { background:#f8d7da; color:#721c24; }
.pos-printer.info { background:#dae6f7; color:#1e3a5f; }
.pos-msg { font-size:.8rem; min-height:1.2em; margin-top:6px; color:#856404; }
.pos-results { margin-top:6px; max-height:520px; overflow-y:auto; }
.pos-item { display:flex; justify-content:space-between; align-items:center; gap:8px; width:100%; text-align:left;
            padding:10px 12px; border:1px solid #e0e4ea; border-radius:6px; margin-bottom:8px; cursor:pointer;
            background:#fff; font:inherit; color:inherit; }
.pos-item:hover, .pos-item:focus { background:#f0f4fa; border-color:#1e3a5f; outline:none; }
.pos-item__sub { font-size:.72rem; color:#666; }
.pos-line { padding:8px 0; border-bottom:1px solid #eee; }
.pos-line__name { font-weight:600; font-size:.88rem; word-break:break-all; }
.pos-line__ctrl { display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-top:6px; }
.pos-line__ctrl .form-control { padding:4px 6px; }
.pos-line__ctrl .qty { width:56px; text-align:center; }
.pos-line__ctrl .price { width:110px; text-align:right; }
.pos-item__price { font-weight:700; color:var(--color-primary); font-size:.85rem; margin-right:4px; white-space:nowrap; }
.pos-line__ctrl .disc { width:90px; text-align:right; }
.pos-line__amount { margin-left:auto; font-weight:700; min-width:90px; text-align:right; }
.pos-line .is-invalid { border-color: var(--color-danger); background:#fff5f5; }
.pos-totals { border-top:2px solid #1e3a5f; margin-top:12px; padding-top:8px; }
.pos-trow { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:3px 0; }
.pos-disc { display:flex; align-items:center; gap:6px; }
.pos-disc select { width:72px; padding:4px; }
.pos-disc input { width:100px; padding:4px 6px; text-align:right; }
.pos-total { font-size:1.6rem; font-weight:700; color:#1e3a5f; border-top:1px solid #dee2e6; margin-top:4px; padding-top:6px; }
.pos-pay { margin-top:12px; padding-top:12px; border-top:1px solid #dee2e6; }
.pos-methods { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }
.pos-methods button { flex:1 1 80px; padding:10px 6px; border:1px solid #1e3a5f; border-radius:4px; background:#fff;
                      color:#1e3a5f; font-weight:600; cursor:pointer; font:inherit; }
.pos-methods button.active { background:#1e3a5f; color:#fff; }
.pos-tender { display:flex; align-items:center; gap:10px; }
.pos-tender label { white-space:nowrap; }
.pos-tender input { font-size:1.2rem; text-align:right; }
.pos-quick { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; }
.pos-change { font-size:1.25rem; font-weight:700; }
.pos-change.short { color: var(--color-danger); }
.pos-checkout { width:100%; padding:16px; font-size:1.15rem; margin-top:8px; }
.pos-summary { background:#f4f6f9; border-radius:4px; padding:10px 12px; font-size:.9rem; }
.pos-summary .pos-trow strong { font-size:1.15rem; }
.pos-reason { white-space:pre-wrap; color:#721c24; background:#fdf3f3; border-left:4px solid var(--color-danger); padding:8px 10px; font-size:.85rem; }
.pos-done-amounts { text-align:center; }
.pos-done-amounts .big { font-size:2.2rem; font-weight:700; color:#1e3a5f; }
.pos-preview { width:100%; height:360px; border:1px solid #dee2e6; border-radius:4px; background:#fff; }
.pos-member-chip { display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:6px 10px; background:#eef6ee; border:1px solid #b7dfb9; border-radius:4px; margin-bottom:6px; }
.pos-member-row { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:8px 4px; border-bottom:1px solid #eee; }
.pos-hold-row { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:8px 0; border-bottom:1px solid #eee; }
</style>

<?php include __DIR__ . '/_printer.php'; ?>

<script>
(function () {
    'use strict';
    var CFG = <?= json_encode($posConfig, $jsFlags) ?>;
    var P = window.FuryoPrinter;
    var CART_KEY = 'furyo_pos_cart_v1_' + CFG.userKey;
    var HOLD_KEY = 'furyo_pos_holds_v1_' + CFG.userKey;
    var METHOD_LABELS = { cash: '現金', credit: 'クレジットカード', emoney: '電子マネー', qr: 'QRコード決済', other: 'その他' };

    var $ = function (id) { return document.getElementById(id); };
    var resultsBox = $('pos_results'), cartBox = $('pos_cart'), emptyMsg = $('pos_cart_empty');
    var searchIn = $('pos_search');

    /* ===== ユーティリティ ===== */
    function esc(t) {
        return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    // 全角数字・カンマ・円記号などを除いて半角数字だけにする（IME の全角入力対策）
    function digits(v) {
        return String(v == null ? '' : v).replace(/[０-９]/g, function (c) {
            return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
        }).replace(/[^0-9]/g, '').replace(/^0+(?=\d)/, '').slice(0, 12);
    }
    function yen(n) { return (n < 0 ? '-¥' : '¥') + Math.abs(n).toLocaleString('ja-JP'); }
    function idiv(a, b) { return (a - a % b) / b; } // 正の整数の切り捨て除算（浮動小数の誤差を避ける）
    function divRound(a, b, mode) {
        if (a <= 0) { return 0; }
        if (mode === 'ceil') { return idiv(a + b - 1, b); }
        if (mode === 'round') { return idiv(2 * a + b, 2 * b); }
        return idiv(a, b);
    }
    function uuid() {
        if (window.crypto && crypto.randomUUID) { return crypto.randomUUID(); }
        var b = new Uint8Array(16);
        (window.crypto || window.msCrypto).getRandomValues(b);
        b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
        var h = Array.prototype.map.call(b, function (x) { return ('0' + x.toString(16)).slice(-2); }).join('');
        return h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' + h.slice(16, 20) + '-' + h.slice(20);
    }
    function lsGet(k, def) { try { var v = JSON.parse(localStorage.getItem(k) || 'null'); return v == null ? def : v; } catch (e) { return def; } }
    function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 保存できなくても会計は可能 */ } }
    function openModal(id) { $(id).classList.add('active'); }
    function closeModal(id) { $(id).classList.remove('active'); }

    /* ===== 状態 ===== */
    function blankState() {
        // member: 選択した会員の会員番号 / memberName・memberId: 表示用
        return { lines: [], seq: 0, discType: 'none', discValue: '', method: 'cash', tendered: '', ref: '', member: '', memberName: '', memberId: 0, note: '', token: '' };
    }
    var state = blankState();
    var lastResults = {};    // ledger_id -> 検索結果
    var submitting = false;
    var lastPrinter = { connected: false };

    function persist() { lsSet(CART_KEY, state); }
    function invalidateToken() { state.token = ''; }

    /* ===== 金額計算（PosCalculator と同じ手順） ===== */
    function calc() {
        var r = { lines: [], count: 0, subtotal: 0, discount: 0, tax: 0, total: 0, errors: [] };
        state.lines.forEach(function (l, i) {
            var qty = parseInt(l.qty, 10) || 0;
            var price = l.price === '' ? null : parseInt(l.price, 10);
            var disc = l.disc === '' ? 0 : parseInt(l.disc, 10);
            var gross = price === null ? 0 : price * qty;
            var err = '';
            if (price === null) { err = 'price'; }
            else if (price > 999999999 || gross > 999999999) { err = 'price'; }
            else if (disc > gross) { err = 'disc'; }
            var amount = err ? 0 : gross - disc;
            r.lines.push({ amount: amount, err: err });
            if (err) { r.errors.push({ line: i, type: err }); }
            r.subtotal += amount;
            r.count += qty;
        });
        var dv = state.discValue === '' ? 0 : parseInt(state.discValue, 10);
        if (state.discType === 'amount') {
            if (dv > r.subtotal) { r.errors.push({ type: 'discount', msg: '値引額が小計を超えています。' }); }
            r.discount = Math.min(dv, r.subtotal);
        } else if (state.discType === 'percent') {
            if (dv > 100) { r.errors.push({ type: 'discount', msg: '値引率は0〜100%で入力してください。' }); dv = 100; }
            r.discount = idiv(r.subtotal * dv, 100);
        }
        var after = r.subtotal - r.discount;
        if (CFG.taxMode === 'exclusive') {
            r.tax = CFG.taxRate > 0 ? divRound(after * CFG.taxRate, 100, CFG.rounding) : 0;
            r.total = after + r.tax;
        } else {
            r.total = after;
            r.tax = CFG.taxRate > 0 ? divRound(r.total * CFG.taxRate, 100 + CFG.taxRate, CFG.rounding) : 0;
        }
        if (r.subtotal > 999999999) { r.errors.push({ type: 'limit', msg: '会計金額が上限（999,999,999円）を超えています。' }); }
        var t = state.tendered === '' ? null : parseInt(state.tendered, 10);
        r.tendered = state.method === 'cash' ? t : r.total;
        r.change = (state.method === 'cash' && t !== null) ? t - r.total : 0;
        return r;
    }

    /* ===== 表示 ===== */
    function renderTotals() {
        var r = calc();
        $('t_count').textContent = r.count;
        $('t_subtotal').textContent = yen(r.subtotal);
        $('t_discount').textContent = yen(-r.discount);
        if (CFG.taxRate > 0) {
            $('t_tax_row').style.display = '';
            $('t_tax_label').textContent = (CFG.taxMode === 'exclusive' ? '消費税等（外税' : '内消費税等（') + CFG.taxRate + '%）';
            $('t_tax').textContent = yen(r.tax);
        } else {
            $('t_tax_row').style.display = 'none';
        }
        $('t_total').textContent = yen(r.total);
        var ch = $('t_change');
        if (state.method === 'cash' && state.tendered !== '' && r.change < 0) {
            ch.textContent = '不足 ' + yen(-r.change);
            ch.parentNode.classList.add('short');
        } else {
            ch.textContent = yen(Math.max(0, r.change));
            ch.parentNode.classList.remove('short');
        }
        // 明細ごとの金額・エラー表示
        r.lines.forEach(function (lr, i) {
            var row = cartBox.querySelector('.pos-line[data-idx="' + i + '"]');
            if (!row) { return; }
            row.querySelector('.pos-line__amount').textContent = lr.err === 'price' ? '単価未入力' : yen(lr.amount);
            row.querySelector('.price').classList.toggle('is-invalid', lr.err === 'price');
            row.querySelector('.disc').classList.toggle('is-invalid', lr.err === 'disc');
        });
        $('pos_disc_value').classList.toggle('is-invalid', r.errors.some(function (e) { return e.type === 'discount'; }));
        return r;
    }

    function renderCart() {
        if (state.lines.length === 0) {
            cartBox.innerHTML = '';
            cartBox.appendChild(emptyMsg);
        } else {
            var html = '';
            state.lines.forEach(function (l, i) {
                html += '<div class="pos-line" data-idx="' + i + '">'
                    + '<div class="pos-line__name">' + esc(l.name)
                    + ' <span class="pos-item__sub">#' + esc(l.id) + (l.serial ? ' / SN: ' + esc(l.serial) : '') + ' / 残' + esc(l.remaining) + '</span></div>'
                    + '<div class="pos-line__ctrl">'
                    + '<button type="button" class="btn btn-secondary btn-sm" data-act="minus" aria-label="数量を減らす">−</button>'
                    + '<input type="text" class="form-control qty" inputmode="numeric" value="' + esc(l.qty) + '" data-act="qty" aria-label="数量">'
                    + '<button type="button" class="btn btn-secondary btn-sm" data-act="plus" aria-label="数量を増やす">＋</button>'
                    + '<span>×</span>'
                    + '<input type="text" class="form-control price" inputmode="numeric" placeholder="単価(円)" value="' + esc(l.price) + '" data-act="price" aria-label="単価">'
                    + '<input type="text" class="form-control disc" inputmode="numeric" placeholder="値引(円)" value="' + esc(l.disc) + '" data-act="disc" aria-label="単品値引">'
                    + '<span class="pos-line__amount"></span>'
                    + '<button type="button" class="btn btn-danger btn-sm" data-act="remove" aria-label="削除">×</button>'
                    + '</div></div>';
            });
            cartBox.innerHTML = html;
        }
        renderTotals();
    }

    function renderPayment() {
        Array.prototype.forEach.call($('pos_methods').querySelectorAll('button'), function (b) {
            b.classList.toggle('active', b.getAttribute('data-method') === state.method);
        });
        $('pos_cash_box').style.display = state.method === 'cash' ? '' : 'none';
        $('pos_ref_box').style.display = state.method === 'cash' ? 'none' : '';
        $('pos_disc_type').value = state.discType;
        $('pos_disc_value').disabled = state.discType === 'none';
        $('pos_disc_value').value = state.discValue;
        $('pos_tendered').value = state.tendered === '' ? '' : Number(state.tendered).toLocaleString('ja-JP');
        $('pos_ref').value = state.ref;
        renderMember();
        $('pos_note').value = state.note;
    }

    function renderAll() { renderPayment(); renderCart(); renderHoldCount(); }

    function showAlert(msg, retry) {
        var box = $('pos_alert');
        box.innerHTML = '';
        if (!msg) { box.style.display = 'none'; return; }
        var p = document.createElement('div');
        p.style.whiteSpace = 'pre-wrap';
        p.textContent = msg;
        box.appendChild(p);
        if (retry) {
            var b = document.createElement('button');
            b.type = 'button'; b.className = 'btn btn-danger btn-sm'; b.style.marginTop = '8px';
            b.textContent = '同じ会計を再送信する';
            b.addEventListener('click', function () { showAlert(''); submit(retry); });
            box.appendChild(b);
        }
        box.style.display = '';
        box.scrollIntoView({ block: 'nearest' });
    }
    function searchMsg(msg) { $('pos_search_msg').textContent = msg || ''; }

    /* ===== 在庫検索 ===== */
    var timer = null, searchSeq = 0;
    function fetchJson(url, opts) {
        return fetch(url, Object.assign({ credentials: 'same-origin', headers: { 'Accept': 'application/json' } }, opts || {}))
            .then(function (res) {
                return res.json().then(function (data) { return { status: res.status, data: data }; },
                    function () { return { status: res.status, data: null }; });
            });
    }
    function doSearch(exact) {
        var q = searchIn.value.trim();
        var my = ++searchSeq;
        return fetchJson('/index.php?page=pos.search&q=' + encodeURIComponent(q) + (exact ? '&exact=1' : ''))
            .then(function (r) {
                if (my !== searchSeq) { return null; } // 古い応答は捨てる（入力が速いと結果が前後するため）
                if (!r.data) { resultsBox.innerHTML = '<p class="text-muted">検索に失敗しました。</p>'; return null; }
                if (!r.data.ok) {
                    resultsBox.innerHTML = '<p class="text-muted" style="font-size:.85rem;">' + esc(r.data.error || '検索に失敗しました。') + '</p>';
                    return null;
                }
                var items = r.data.items || [];
                items.forEach(function (it) { lastResults[it.ledger_id] = it; });
                if (!exact || items.length !== 1) { renderResults(items); }
                return items;
            }, function () {
                if (my === searchSeq) { resultsBox.innerHTML = '<p class="text-muted">通信エラーで検索できませんでした。</p>'; }
                return null;
            });
    }
    function renderResults(items) {
        if (items.length === 0) {
            resultsBox.innerHTML = '<p class="text-muted" style="font-size:.85rem;">在庫のある商品が見つかりません。</p>';
            return;
        }
        var html = '';
        items.forEach(function (it) {
            html += '<button type="button" class="pos-item" data-id="' + esc(it.ledger_id) + '">'
                + '<span><span style="font-weight:600; display:block;">' + esc(it.item_name) + '</span>'
                + '<span class="pos-item__sub">#' + esc(it.ledger_id) + (it.serial_number ? ' / SN: ' + esc(it.serial_number) : '')
                + ' / 仕入日: ' + esc(it.purchase_date) + '</span></span>'
                + '<span>' + (it.pending ? '<span class="badge badge-warning" title="台帳が管理者の承認待ちです">承認待ち</span> ' : '')
                + (it.sale_price !== null && it.sale_price !== undefined ? '<span class="pos-item__price">¥' + Number(it.sale_price).toLocaleString('ja-JP') + '</span> ' : '')
                + '<span class="badge badge-primary">残' + esc(it.remaining) + '</span></span>'
                + '</button>';
        });
        resultsBox.innerHTML = html;
    }
    searchIn.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { doSearch(false); }, 300);
    });
    searchIn.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' || e.isComposing) { return; }
        e.preventDefault();
        clearTimeout(timer);
        var q = searchIn.value.trim();
        if (q === '') { doSearch(false); return; }
        // バーコード読取: シリアル番号の完全一致・台帳番号で1件に決まれば即追加
        doSearch(true).then(function (items) {
            if (items && items.length === 1) {
                addToCart(items[0]);
                searchIn.value = '';
                doSearch(false);
            } else if (items && items.length === 0 && RECEIPT_RE.test(q)) {
                // 在庫に該当せずレシート番号の形式なら、レシートのバーコードとして取引を呼び出す
                lookupReceipt(q, searchMsg).then(function (ok) { if (!ok) { doSearch(false); } });
            } else if (items && items.length === 0) {
                searchMsg('「' + q + '」に完全一致する在庫がありません。部分一致の候補を表示します。');
                doSearch(false);
            } else if (items) {
                searchMsg('複数の商品が該当しました。一覧から選択してください。');
            }
        });
    });
    resultsBox.addEventListener('click', function (e) {
        var el = e.target.closest ? e.target.closest('.pos-item') : null;
        if (!el) { return; }
        var it = lastResults[el.getAttribute('data-id')];
        if (it) { addToCart(it); }
    });

    /* ===== カート操作 ===== */
    function addToCart(it) {
        showAlert('');
        var id = String(it.ledger_id);
        var line = null;
        state.lines.forEach(function (l) { if (l.id === id) { line = l; } });
        if (line) {
            line.remaining = it.remaining;
            if (line.qty >= it.remaining) {
                searchMsg('「' + it.item_name + '」は在庫数（' + it.remaining + '点）を超えて追加できません。');
                return;
            }
            line.qty++;
        } else {
            // 台帳に販売予定価格があれば単価の初期値にする（変更可）
            var initPrice = (it.sale_price !== null && it.sale_price !== undefined && it.sale_price !== '') ? String(it.sale_price) : '';
            state.lines.push({ id: id, name: it.item_name, serial: it.serial_number || '', remaining: it.remaining, qty: 1, price: initPrice, disc: '' });
        }
        searchMsg('「' + it.item_name + '」を追加しました。');
        invalidateToken();
        persist();
        renderCart();
        // 追加した明細の単価欄へ
        var idx = state.lines.findIndex(function (l) { return l.id === id; });
        var row = cartBox.querySelector('.pos-line[data-idx="' + idx + '"] .price');
        if (row && state.lines[idx].price === '') { row.focus(); }
    }

    cartBox.addEventListener('click', function (e) {
        var btn = e.target.closest ? e.target.closest('button[data-act]') : null;
        if (!btn) { return; }
        var idx = parseInt(btn.closest('.pos-line').getAttribute('data-idx'), 10);
        var l = state.lines[idx];
        if (!l) { return; }
        var act = btn.getAttribute('data-act');
        if (act === 'plus') {
            if (l.qty < l.remaining) { l.qty++; } else { searchMsg('在庫数（' + l.remaining + '点）を超えて追加できません。'); }
        } else if (act === 'minus') {
            if (l.qty > 1) { l.qty--; } else { state.lines.splice(idx, 1); }
        } else if (act === 'remove') {
            state.lines.splice(idx, 1);
        }
        invalidateToken();
        persist();
        renderCart();
    });
    cartBox.addEventListener('input', function (e) {
        var act = e.target.getAttribute('data-act');
        if (!act) { return; }
        var idx = parseInt(e.target.closest('.pos-line').getAttribute('data-idx'), 10);
        var l = state.lines[idx];
        if (!l) { return; }
        var v = digits(e.target.value);
        if (act === 'qty') {
            var q = parseInt(v, 10) || 0;
            if (q > l.remaining) { q = l.remaining; searchMsg('在庫数（' + l.remaining + '点）までです。'); }
            l.qty = Math.max(1, q);
        } else if (act === 'price') {
            l.price = v;
        } else if (act === 'disc') {
            l.disc = v === '0' ? '' : v;
        }
        invalidateToken();
        persist();
        renderTotals();
    });
    // 入力確定時に表示を正規化（全角数字・カンマ等。入力中は IME を邪魔しないよう書き換えない）
    cartBox.addEventListener('change', function (e) {
        var act = e.target.getAttribute ? e.target.getAttribute('data-act') : null;
        var row = e.target.closest ? e.target.closest('.pos-line') : null;
        if (!act || !row) { return; }
        var l = state.lines[parseInt(row.getAttribute('data-idx'), 10)];
        if (!l) { return; }
        e.target.value = act === 'qty' ? l.qty : (act === 'price' ? l.price : l.disc);
    });

    $('pos_clear').addEventListener('click', function () {
        if (state.lines.length && !confirm('カートを空にしますか？')) { return; }
        state = blankState();
        persist();
        showAlert('');
        renderAll();
    });

    $('pos_disc_type').addEventListener('change', function () {
        state.discType = this.value;
        if (state.discType === 'none') { state.discValue = ''; }
        invalidateToken(); persist(); renderPayment(); renderTotals();
        if (state.discType !== 'none') { $('pos_disc_value').focus(); }
    });
    $('pos_disc_value').addEventListener('input', function () {
        state.discValue = digits(this.value); invalidateToken(); persist(); renderTotals();
    });
    $('pos_disc_value').addEventListener('change', function () { this.value = state.discValue; });

    $('pos_methods').addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('button[data-method]') : null;
        if (!b) { return; }
        state.method = b.getAttribute('data-method');
        invalidateToken(); persist(); renderPayment(); renderTotals();
    });
    $('pos_tendered').addEventListener('input', function () {
        state.tendered = digits(this.value); invalidateToken(); persist(); renderTotals();
    });
    $('pos_tendered').addEventListener('change', function () {
        this.value = state.tendered === '' ? '' : Number(state.tendered).toLocaleString('ja-JP');
    });
    document.querySelector('.pos-quick').addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('button[data-tender]') : null;
        if (!b) { return; }
        var v = b.getAttribute('data-tender'), r = calc();
        if (v === 'exact') { state.tendered = String(r.total); }
        else if (v === 'clear') { state.tendered = ''; }
        else { state.tendered = String((parseInt(state.tendered || '0', 10) || 0) + parseInt(v, 10)); }
        invalidateToken(); persist(); renderPayment(); renderTotals();
    });
    $('pos_ref').addEventListener('input', function () { state.ref = this.value; persist(); });
    $('pos_member_code').addEventListener('input', function () { $('pos_member_info').textContent = ''; });
    $('pos_member_code').addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); findMember(this.value.trim(), true); }
    });
    $('pos_note').addEventListener('input', function () { state.note = this.value; invalidateToken(); persist(); });

    /* ===== 会員 ===== */
    function renderMember() {
        var sel = !!state.member;
        $('pos_member_selected').style.display = sel ? '' : 'none';
        $('pos_member_input_row').style.display = sel ? 'none' : 'flex';
        if (sel) {
            $('pos_member_label').textContent = '✓ ' + state.member + (state.memberName ? '　' + state.memberName + ' 様' : '');
            $('pos_member_link').style.display = state.memberId ? '' : 'none';
            $('pos_member_link').href = '/index.php?page=member.show&id=' + encodeURIComponent(state.memberId || 0);
            $('pos_member_code').value = '';
        }
    }
    function selectMember(m) {
        state.member = m.member_code;
        state.memberName = m.name;
        state.memberId = m.id;
        invalidateToken(); persist(); renderMember();
        $('pos_member_info').textContent = m.visits ? '購入 ' + m.visits + '回・最終 ' + m.last_at : '';
        $('pos_member_info').style.color = '';
        closeModal('m_member');
    }
    function memberRows(list) {
        if (!list.length) { return '<p class="text-muted">該当する会員はいません。</p>'; }
        var html = '';
        list.forEach(function (m, i) {
            html += '<div class="pos-member-row"><div><div style="font-weight:600;">' + esc(m.member_code) + '　' + esc(m.name) + (m.corporate ? ' <span class="badge badge-secondary">法人</span>' : '') + '</div>'
                + '<div class="text-muted" style="font-size:.78rem;">' + (m.phone_tail ? '電話 ****' + esc(m.phone_tail) + '　' : '')
                + (m.visits ? '購入 ' + esc(m.visits) + '回・最終 ' + esc(m.last_at) : '購入履歴なし') + '</div></div>'
                + '<button type="button" class="btn btn-primary btn-sm" data-pick="' + i + '">選択</button></div>';
        });
        return html;
    }
    var memberResults = [];
    function searchMembers(q) {
        return fetchJson('/index.php?page=pos.member.search&q=' + encodeURIComponent(q)).then(function (r) {
            if (!r.data || !r.data.ok) { throw new Error((r.data && r.data.error) || '会員の検索に失敗しました。'); }
            memberResults = r.data.members || [];
            return memberResults;
        });
    }
    // 入力欄から検索: 会員番号が完全一致、または1件だけ該当すれば即選択。複数なら選択ダイアログ
    function findMember(q, auto) {
        var info = $('pos_member_info');
        if (q === '') { openMemberModal(''); return; }
        info.textContent = '検索中…'; info.style.color = '';
        searchMembers(q).then(function (list) {
            var exact = list.filter(function (m) { return m.member_code.toLowerCase() === q.toLowerCase(); });
            if (auto && exact.length === 1) { selectMember(exact[0]); return; }
            if (auto && list.length === 1) { selectMember(list[0]); return; }
            info.textContent = list.length ? '' : '該当する会員はいません。';
            if (list.length) { openMemberModal(q, list); }
        }, function (e) { info.textContent = e.message; info.style.color = '#721c24'; });
    }
    function openMemberModal(q, list) {
        $('m_member_q').value = q;
        $('m_member_list').innerHTML = list ? memberRows(list) : '<p class="text-muted">会員番号・氏名・電話番号で検索してください。</p>';
        openModal('m_member');
        $('m_member_q').focus();
    }
    $('pos_member_lookup').addEventListener('click', function () { findMember($('pos_member_code').value.trim(), true); });
    $('pos_member_clear').addEventListener('click', function () {
        state.member = ''; state.memberName = ''; state.memberId = 0;
        $('pos_member_info').textContent = '';
        invalidateToken(); persist(); renderMember();
        $('pos_member_code').focus();
    });
    function modalSearch() {
        var q = $('m_member_q').value.trim();
        if (q === '') { return; }
        $('m_member_list').innerHTML = '<p class="text-muted">検索中…</p>';
        searchMembers(q).then(function (list) { $('m_member_list').innerHTML = memberRows(list); },
            function (e) { $('m_member_list').innerHTML = '<p class="text-danger">' + esc(e.message) + '</p>'; });
    }
    $('m_member_go').addEventListener('click', modalSearch);
    $('m_member_q').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); modalSearch(); } });
    $('m_member_list').addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('[data-pick]') : null;
        if (b && memberResults[parseInt(b.getAttribute('data-pick'), 10)]) { selectMember(memberResults[parseInt(b.getAttribute('data-pick'), 10)]); }
    });

    /* ===== レシート番号で呼出（明細表示・再印刷へ） ===== */
    var RECEIPT_RE = /^(?:No\.?)?\s*\d{8}-?\d{4,6}$/i;
    function lookupReceipt(no, msgFn) {
        msgFn('呼び出し中…');
        return fetchJson('/index.php?page=pos.lookup&format=json&no=' + encodeURIComponent(no)).then(function (r) {
            if (r.data && r.data.ok) {
                msgFn('No.' + r.data.receipt_no + ' を開きます…');
                persist();
                location.href = r.data.url;
                return true;
            }
            msgFn((r.data && r.data.error) || '呼び出しに失敗しました。');
            return false;
        }, function () { msgFn('通信エラーで呼び出せませんでした。'); return false; });
    }
    $('pos_lookup_btn').addEventListener('click', function () {
        $('m_lookup_no').value = '';
        $('m_lookup_msg').textContent = '';
        openModal('m_lookup');
        $('m_lookup_no').focus();
    });
    function lookupFromModal() {
        var no = $('m_lookup_no').value.trim();
        if (no === '') { return; }
        lookupReceipt(no, function (m) { $('m_lookup_msg').textContent = m; });
    }
    $('m_lookup_go').addEventListener('click', lookupFromModal);
    $('m_lookup_no').addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); lookupFromModal(); } });

    /* ===== 保留・呼出 ===== */
    function holds() { var h = lsGet(HOLD_KEY, []); return Array.isArray(h) ? h : []; }
    function renderHoldCount() {
        var n = holds().length, el = $('pos_hold_count');
        el.textContent = n; el.style.display = n ? '' : 'none';
    }
    $('pos_hold_btn').addEventListener('click', function () {
        if (state.lines.length === 0) { alert('保留するカートがありません。'); return; }
        var h = holds();
        if (h.length >= 10) { alert('保留できるのは10件までです。呼び出して会計するか削除してください。'); return; }
        var copy = JSON.parse(JSON.stringify(state)); copy.token = '';
        h.push({ at: Date.now(), state: copy, total: calc().total });
        lsSet(HOLD_KEY, h);
        state = blankState(); persist(); showAlert(''); renderAll();
        searchMsg('カートを保留しました。「呼出」から再開できます。');
    });
    $('pos_recall_btn').addEventListener('click', function () {
        var h = holds(), body = $('m_holds_body');
        if (h.length === 0) { body.innerHTML = '<p class="text-muted">保留中のカートはありません。</p>'; openModal('m_holds'); return; }
        var html = '';
        h.forEach(function (x, i) {
            var d = new Date(x.at), names = (x.state.lines || []).map(function (l) { return l.name; });
            html += '<div class="pos-hold-row"><div><div style="font-weight:600;">' + esc(names.slice(0, 2).join('、') + (names.length > 2 ? ' ほか' + (names.length - 2) + '件' : ''))
                + '</div><div class="text-muted" style="font-size:.78rem;">' + esc(d.toLocaleString('ja-JP')) + ' / ' + esc(yen(x.total || 0)) + '</div></div>'
                + '<div style="display:flex; gap:6px;"><button type="button" class="btn btn-primary btn-sm" data-recall="' + i + '">呼び出す</button>'
                + '<button type="button" class="btn btn-secondary btn-sm" data-drop="' + i + '">削除</button></div></div>';
        });
        body.innerHTML = html;
        openModal('m_holds');
    });
    $('m_holds_body').addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('button') : null;
        if (!b) { return; }
        var h = holds();
        if (b.hasAttribute('data-drop')) {
            if (!confirm('この保留を削除しますか？')) { return; }
            h.splice(parseInt(b.getAttribute('data-drop'), 10), 1);
            lsSet(HOLD_KEY, h);
            closeModal('m_holds'); renderHoldCount();
            $('pos_recall_btn').click();
            return;
        }
        var i = parseInt(b.getAttribute('data-recall'), 10), x = h[i];
        if (!x) { return; }
        h.splice(i, 1);
        if (state.lines.length > 0) {
            if (!confirm('現在のカートを保留して、選択したカートを呼び出しますか？')) { return; }
            var copy = JSON.parse(JSON.stringify(state)); copy.token = '';
            h.push({ at: Date.now(), state: copy, total: calc().total });
        }
        lsSet(HOLD_KEY, h);
        state = Object.assign(blankState(), x.state, { token: '' });
        persist(); closeModal('m_holds'); showAlert(''); renderAll();
        searchMsg('保留したカートを呼び出しました。在庫は会計時に再確認されます。');
    });

    /* ===== プリンタ状態 ===== */
    function refreshPrinter() {
        var badge = $('pos_printer_status');
        return P.check().then(function (st) {
            lastPrinter = st;
            var cfg = P.load();
            badge.classList.remove('ok', 'ng', 'info');
            if (st.connected && cfg.mode === 'browser') {
                badge.classList.add('info'); badge.textContent = '🖨 ブラウザ印刷';
            } else if (st.connected) {
                badge.classList.add('ok'); badge.textContent = '🖨 接続中: ' + (st.label || 'プリンタ');
            } else {
                badge.classList.add('ng'); badge.textContent = '🖨 プリンタ未接続';
            }
            badge.title = st.reason || st.label || '';
            return st;
        });
    }
    P.onChange(function () { refreshPrinter(); });

    /* ===== 会計 ===== */
    function validate(r) {
        if (state.lines.length === 0) { return 'カートが空です。商品を追加してください。'; }
        if (!state.member && $('pos_member_code').value.trim() !== '') {
            return '会員欄に入力がありますが、会員が選択されていません。「検索」で会員を選択するか、入力欄を空にしてください。';
        }
        for (var i = 0; i < r.errors.length; i++) {
            var e = r.errors[i];
            if (e.type === 'price') { return '「' + state.lines[e.line].name + '」の単価を入力してください（0円の場合は 0）。'; }
            if (e.type === 'disc') { return '「' + state.lines[e.line].name + '」の値引が明細金額を超えています。'; }
            if (e.msg) { return e.msg; }
        }
        if (state.method === 'cash') {
            if (state.tendered === '') { return 'お預り金額を入力してください（ちょうどの場合は「ちょうど」）。'; }
            if (r.change < 0) { return 'お預り金額が合計に ' + yen(-r.change) + ' 足りません。'; }
        }
        return '';
    }
    function summaryHtml(r) {
        var h = '<div class="pos-trow"><span>合計（' + r.count + '点）</span><strong>' + esc(yen(r.total)) + '</strong></div>'
              + (state.member ? '<div class="pos-trow"><span>会員</span><span>' + esc(state.member + (state.memberName ? ' ' + state.memberName + ' 様' : '')) + '</span></div>' : '')
              + '<div class="pos-trow"><span>支払方法</span><span>' + esc(METHOD_LABELS[state.method]) + '</span></div>';
        if (state.method === 'cash') {
            h += '<div class="pos-trow"><span>お預り</span><span>' + esc(yen(r.tendered)) + '</span></div>'
               + '<div class="pos-trow"><span>お釣り</span><strong>' + esc(yen(r.change)) + '</strong></div>';
        }
        return h;
    }

    $('pos_checkout').addEventListener('click', function () {
        if (submitting) { return; }
        var r = renderTotals();
        var err = validate(r);
        if (err) { showAlert(err); return; }
        showAlert('');
        var btn = this;
        btn.disabled = true;
        btn.textContent = 'プリンタを確認中…';
        refreshPrinter().then(function (st) {
            btn.disabled = false;
            btn.textContent = '会計を確定する';
            if (st.connected) {
                $('m_confirm_summary').innerHTML = summaryHtml(r);
                $('m_confirm_printer').textContent = '決済後、レシートを「' + (st.label || 'プリンタ') + '」で印刷します。';
                openModal('m_confirm');
                $('m_confirm_ok').focus();
            } else {
                // プリンタ未接続: 許可を得てから決済 → レシートは画面に発行
                $('m_noprinter_reason').textContent = st.reason || 'レシートプリンタが見つかりません。';
                $('m_noprinter_summary').innerHTML = summaryHtml(r);
                openModal('m_noprinter');
                $('m_noprinter_allow').focus();
            }
        }, function () {
            btn.disabled = false;
            btn.textContent = '会計を確定する';
        });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-pos-cancel]'), function (b) {
        b.addEventListener('click', function () { closeModal('m_confirm'); closeModal('m_noprinter'); });
    });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape' || submitting) { return; }
        ['m_confirm', 'm_noprinter', 'm_holds', 'm_ryoshu', 'm_member', 'm_lookup'].forEach(closeModal);
    });
    $('m_confirm_ok').addEventListener('click', function () { submit('print'); });
    $('m_noprinter_allow').addEventListener('click', function () { submit('unprinted'); });

    function setSubmitting(on) {
        submitting = on;
        ['m_confirm_ok', 'm_noprinter_allow', 'pos_checkout'].forEach(function (id) { $(id).disabled = on; });
        $('m_confirm_ok').textContent = on ? '処理中…' : '決済を確定する';
        $('m_noprinter_allow').textContent = on ? '処理中…' : '許可して決済する';
    }

    function submit(mode) {
        if (submitting) { return; }
        var r = calc();
        var err = validate(r);
        if (err) { closeModal('m_confirm'); closeModal('m_noprinter'); showAlert(err); return; }
        if (!state.token) { state.token = uuid(); persist(); }
        setSubmitting(true);

        var payload = {
            client_token: state.token,
            items: state.lines.map(function (l) {
                return { ledger_id: parseInt(l.id, 10), quantity: l.qty, unit_price: parseInt(l.price, 10), line_discount: l.disc === '' ? 0 : parseInt(l.disc, 10) };
            }),
            discount: { type: state.discType, value: state.discValue === '' ? 0 : parseInt(state.discValue, 10) },
            payment: { method: state.method, tendered: state.method === 'cash' ? parseInt(state.tendered, 10) : null, ref: state.ref },
            member_code: state.member.trim(),
            register_no: P.load().registerNo,
            note: state.note.trim(),
            receipt_mode: mode,
            expected_total: r.total
        };
        var body = new URLSearchParams();
        body.append('_csrf_token', CFG.csrf);
        body.append('payload', JSON.stringify(payload));

        fetchJson('/index.php?page=pos.checkout', { method: 'POST', body: body }).then(function (res) {
            setSubmitting(false);
            closeModal('m_confirm'); closeModal('m_noprinter');
            var d = res.data;
            if (!d) {
                showAlert('サーバーの応答を読み取れませんでした（HTTP ' + res.status + '）。決済が完了したか不明です。\n取引履歴を確認するか、下のボタンで同じ会計を再送信してください（二重には登録されません）。', mode);
                return;
            }
            if (!d.ok) {
                showAlert(d.error || '会計できませんでした。');
                if (d.code === 'stock') { doSearch(false); }
                return;
            }
            completed(d, mode, r);
        }, function () {
            setSubmitting(false);
            closeModal('m_confirm'); closeModal('m_noprinter');
            showAlert('通信エラーが発生しました。決済が完了したか不明です。\n下のボタンで同じ会計を再送信してください（完了済みの場合も二重には登録されません）。', mode);
        });
    }

    /* ===== 決済完了 → レシート発行 ===== */
    var doneTx = null;
    function reportPrinted(id, doc, result) {
        var body = new URLSearchParams();
        body.append('_csrf_token', CFG.csrf);
        body.append('id', id);
        body.append('doc', doc);
        body.append('result', result);
        return fetchJson('/index.php?page=pos.printed', { method: 'POST', body: body }).catch(function () { return null; });
    }
    function doneStatus(msg, kind) {
        var el = $('m_done_status');
        el.className = 'alert alert-' + (kind || 'info');
        el.textContent = msg;
    }
    function showPreview(url) {
        $('m_done_preview').src = P.withParam(url, { embed: 1, w: P.load().paper });
        $('m_done_preview_wrap').style.display = '';
    }
    function printReceipt(tx, isFirst) {
        doneStatus('レシートを印刷しています…');
        var cfg = P.load();
        return P.printUrl('/index.php?page=pos.receipt&id=' + tx.id, { drawer: isFirst && cfg.drawer && tx.payment_method === 'cash' })
            .then(function () {
                reportPrinted(tx.id, 'receipt', 'printed');
                doneStatus(cfg.mode === 'browser' ? '✓ レシートを印刷に送りました。' : '✓ レシートを印刷しました。', 'success');
            }, function (e) {
                reportPrinted(tx.id, 'receipt', 'failed');
                doneStatus('レシートの印刷に失敗しました（決済は完了しています）。\n' + (e && e.message ? e.message : '') + '\n「レシートを印刷」で再試行できます。', 'danger');
                showPreview('/index.php?page=pos.receipt&id=' + tx.id);
            });
    }

    function completed(d, mode, r) {
        var tx = d.transaction;
        doneTx = tx;
        // カートを空にして在庫一覧を更新
        state = blankState();
        persist();
        showAlert('');
        renderAll();
        doSearch(false);

        $('m_done_no').textContent = (tx.register_no ? P.registerLabel(tx.register_no) + '　' : '') + 'No.' + tx.receipt_no;
        $('m_done_show').href = d.show_url;
        var amounts = tx.payment_method === 'cash'
            ? '<div class="text-muted">お釣り</div><div class="big">' + esc(yen(tx.change)) + '</div>'
              + '<div class="text-muted" style="font-size:.85rem;">合計 ' + esc(yen(tx.total)) + ' ／ お預り ' + esc(yen(tx.tendered)) + '</div>'
            : '<div class="text-muted">' + esc(METHOD_LABELS[tx.payment_method] || '') + '</div><div class="big">' + esc(yen(tx.total)) + '</div>';
        if (tx.member_name) {
            amounts += '<div style="font-size:.85rem; margin-top:6px;">会員: ' + esc(tx.member_name) + ' 様</div>';
        }
        if (d.duplicate) {
            amounts += '<div class="text-muted" style="font-size:.8rem; margin-top:6px;">（通信のやり直しを検出しました。この会計は1回だけ登録されています）</div>';
        }
        $('m_done_amounts').innerHTML = amounts;
        $('m_done_preview_wrap').style.display = 'none';
        $('m_done_preview').removeAttribute('src');
        openModal('m_done');
        $('m_done_next').focus();

        if (mode === 'print') {
            printReceipt(tx, true);
        } else {
            doneStatus('レシートを画面に発行しました（プリンタ未接続のため未印刷）。必要に応じてお客様に画面をご提示ください。プリンタ接続後は「レシートを印刷」または取引履歴から印刷できます。', 'warning');
            showPreview(d.receipt_url);
        }
    }

    $('m_done_print').addEventListener('click', function () {
        if (!doneTx) { return; }
        refreshPrinter().then(function (st) {
            if (!st.connected) {
                doneStatus('レシートプリンタが接続されていません。\n' + (st.reason || ''), 'danger');
                showPreview('/index.php?page=pos.receipt&id=' + doneTx.id);
                return;
            }
            printReceipt(doneTx, false);
        });
    });
    $('m_done_next').addEventListener('click', function () {
        closeModal('m_done');
        // 次の会計で前回の表示が残らないよう完了ダイアログを初期化
        doneStatus('');
        $('m_done_preview_wrap').style.display = 'none';
        $('m_done_preview').removeAttribute('src');
        searchIn.focus();
    });
    $('m_done_ryoshu').addEventListener('click', function () {
        // 会員の会計なら宛名に会員名を入れておく（変更可）
        if (doneTx && window.PosRyoshu) { window.PosRyoshu.open(doneTx.id, CFG.tadashi, doneTx.member_name || ''); }
    });

    /* ===== 起動 ===== */
    var saved = lsGet(CART_KEY, null);
    if (saved && Array.isArray(saved.lines)) {
        state = Object.assign(blankState(), saved);
        if (state.lines.length) { searchMsg('前回のカートを復元しました。'); }
    }
    renderAll();
    $('pos_register_badge').textContent = P.registerLabel();
    refreshPrinter();
    doSearch(false);
}());
</script>

<?php
$content = ob_get_clean();
include __DIR__ . '/../layouts/main.php';
