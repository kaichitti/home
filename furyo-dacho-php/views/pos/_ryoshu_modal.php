<?php
/**
 * 領収書の発行ダイアログ（POSレジ・取引詳細で共用）
 *
 * window.PosRyoshu.open(取引ID, 既定の但し書き, 既定の宛名) で開く（会員の会計では会員名を宛名に入れる）。
 * プリンタ接続時は印刷、未接続時は画面に表示する。印刷した場合は発行回数を記録する
 * （2回目以降は「再発行」と印字され、監査ログに残る）。
 * ※ views/pos/_printer.php を先に読み込むこと
 */
?>
<div class="modal-overlay" data-no-esc id="m_ryoshu" role="dialog" aria-modal="true" aria-labelledby="m_ryoshu_title"
     data-csrf="<?= htmlspecialchars($csrf_token ?? '', ENT_QUOTES, 'UTF-8') ?>">
    <div class="modal" style="max-width:520px;">
        <div class="modal__header">
            <span class="modal__title" id="m_ryoshu_title">領収書の発行</span>
            <button type="button" class="modal__close" data-modal-close aria-label="閉じる">×</button>
        </div>
        <div class="modal__body">
            <div class="form-group">
                <label class="form-label" for="ryoshu_to">宛名（任意）</label>
                <input type="text" id="ryoshu_to" class="form-control" maxlength="40" placeholder="例：株式会社〇〇（空欄の場合は宛名欄を空けて印字）">
            </div>
            <div class="form-group">
                <label class="form-label" for="ryoshu_tadashi">但し書き</label>
                <input type="text" id="ryoshu_tadashi" class="form-control" maxlength="50" placeholder="お品代">
                <div class="form-hint">「但し ○○ として」と印字されます。現金で税抜5万円以上の場合は収入印紙欄が付きます。</div>
            </div>
            <div id="ryoshu_status" class="alert alert-info" style="display:none;"></div>
            <div id="ryoshu_preview_wrap" style="display:none;">
                <iframe id="ryoshu_preview" title="領収書" style="width:100%; height:340px; border:1px solid #dee2e6; border-radius:4px;"></iframe>
            </div>
        </div>
        <div class="modal__footer">
            <button type="button" class="btn btn-secondary" id="ryoshu_show">画面に表示</button>
            <button type="button" class="btn btn-primary" id="ryoshu_print">印刷する</button>
        </div>
    </div>
</div>
<script>
(function () {
    'use strict';
    var modal = document.getElementById('m_ryoshu');
    if (!modal || window.PosRyoshu) { return; }
    var txId = 0;

    function url() {
        return '/index.php?page=pos.receipt&doc=ryoshu&id=' + encodeURIComponent(txId)
            + '&to=' + encodeURIComponent(document.getElementById('ryoshu_to').value.trim())
            + '&tadashi=' + encodeURIComponent(document.getElementById('ryoshu_tadashi').value.trim());
    }
    function status(msg, kind) {
        var el = document.getElementById('ryoshu_status');
        el.className = 'alert alert-' + (kind || 'info');
        el.style.whiteSpace = 'pre-wrap';
        el.textContent = msg;
        el.style.display = msg ? '' : 'none';
    }
    function preview() {
        document.getElementById('ryoshu_preview').src = window.FuryoPrinter.withParam(url(), { embed: 1, w: window.FuryoPrinter.load().paper });
        document.getElementById('ryoshu_preview_wrap').style.display = '';
    }

    document.getElementById('ryoshu_show').addEventListener('click', function () { status(''); preview(); });
    document.getElementById('ryoshu_print').addEventListener('click', function () {
        var P = window.FuryoPrinter, btn = this;
        btn.disabled = true;
        P.check().then(function (st) {
            if (!st.connected) {
                status('レシートプリンタが接続されていません。領収書を画面に表示しました。\n' + (st.reason || ''), 'warning');
                preview();
                btn.disabled = false;
                return;
            }
            status('印刷しています…');
            return P.printUrl(url()).then(function () {
                var body = new URLSearchParams();
                body.append('_csrf_token', modal.getAttribute('data-csrf'));
                body.append('id', txId);
                body.append('doc', 'ryoshu');
                body.append('result', 'printed');
                fetch('/index.php?page=pos.printed', { method: 'POST', body: body, credentials: 'same-origin' }).catch(function () {});
                status('✓ 領収書を印刷しました。', 'success');
            }, function (e) {
                status('印刷に失敗しました。' + (e && e.message ? '\n' + e.message : ''), 'danger');
                preview();
            }).then(function () { btn.disabled = false; });
        });
    });

    window.PosRyoshu = {
        open: function (id, tadashi, addressee) {
            txId = id;
            document.getElementById('ryoshu_to').value = addressee || '';
            document.getElementById('ryoshu_tadashi').value = tadashi || '';
            document.getElementById('ryoshu_preview_wrap').style.display = 'none';
            status('');
            modal.classList.add('active');
            document.getElementById('ryoshu_to').focus();
        }
    };
}());
</script>
