<?php
/**
 * レシート再印刷ボタンの共通処理（取引履歴・レジ明細検索・取引詳細）
 *
 * data-reprint="取引ID" を付けたボタンを押すと、この端末のプリンタでレシートを印刷する。
 * プリンタ未接続の場合は理由を表示し、レシートを別画面で表示する（画面で提示・ブラウザ印刷用）。
 * 印刷できた場合は印刷回数を記録する（2回目以降は「再発行」と印字、監査ログに記録）。
 * ※ views/pos/_printer.php を先に読み込むこと
 */
?>
<div id="pos_reprint_status" class="alert" role="status" aria-live="polite"
     data-csrf="<?= htmlspecialchars($csrf_token ?? '', ENT_QUOTES, 'UTF-8') ?>"
     style="display:none; position:fixed; right:16px; bottom:16px; z-index:2100; max-width:420px; white-space:pre-wrap; box-shadow:0 4px 16px rgba(0,0,0,.2);"></div>
<script>
(function () {
    'use strict';
    if (window.PosReprint) { return; }
    var box = document.getElementById('pos_reprint_status');
    var timer = null;
    function status(msg, kind, sticky) {
        clearTimeout(timer);
        box.className = 'alert alert-' + (kind || 'info');
        box.textContent = msg;
        box.style.display = msg ? '' : 'none';
        if (msg && !sticky) { timer = setTimeout(function () { box.style.display = 'none'; }, 6000); }
    }
    function record(id) {
        var body = new URLSearchParams();
        body.append('_csrf_token', box.getAttribute('data-csrf'));
        body.append('id', id);
        body.append('doc', 'receipt');
        body.append('result', 'printed');
        return fetch('/index.php?page=pos.printed', { method: 'POST', body: body, credentials: 'same-origin' }).catch(function () {});
    }
    function reprint(id, btn) {
        var P = window.FuryoPrinter;
        var url = '/index.php?page=pos.receipt&id=' + encodeURIComponent(id);
        if (btn) { btn.disabled = true; }
        status('プリンタを確認しています…', 'info', true);
        return P.check().then(function (st) {
            if (!st.connected) {
                status('レシートプリンタが接続されていません。レシートを別画面で表示します。\n' + (st.reason || ''), 'warning');
                window.open(P.withParam(url, { w: P.load().paper }), '_blank', 'noopener');
                return false;
            }
            status('印刷しています…', 'info', true);
            return P.printUrl(url).then(function () {
                return record(id).then(function () {
                    status('✓ レシートを印刷しました（2回目以降は「再発行」と印字されます）。', 'success');
                    return true;
                });
            }, function (e) {
                status('印刷に失敗しました。' + (e && e.message ? '\n' + e.message : ''), 'danger');
                return false;
            });
        }).then(function (ok) {
            if (btn) { btn.disabled = false; }
            return ok;
        });
    }
    document.addEventListener('click', function (e) {
        var b = e.target.closest ? e.target.closest('[data-reprint]') : null;
        if (!b) { return; }
        e.preventDefault();
        reprint(b.getAttribute('data-reprint'), b);
    });
    window.PosReprint = { print: reprint, status: status };
}());
</script>
