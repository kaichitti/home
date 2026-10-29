"""
添付ファイルのダウンロード

暗号化して保存したファイルは Web から直接開けない。この処理でテナントを確認してから復号して返す。
"""
import os
import re

from ..core.controller import BaseController
from ..core.response import Response, ResponseDone
from ..helpers.crypto import Crypto, CryptoError
from ..models.audit_log import AuditLog
from ..models.ledger_file import LedgerFile
from ..util import rawurlencode
from ..logger import log_error


class FileController(BaseController):
    def download(self):
        """index.cgi?page=file.download&id=台帳ID&type=種別（type 無しは ledger_files.id として扱う）"""
        self.auth.require_login()
        tenant_id = self.auth.tenant_id()
        user_id = self.auth.user_id()
        file_id = self.get_int('id')
        ftype = self.request.get('type', '')
        ftype = ftype if isinstance(ftype, str) else ''
        if file_id <= 0:
            self.not_found('ファイル ID が不正です。')

        model = LedgerFile(self.db)
        if ftype != '':
            # 旧リンクの 'receipt_form' は 'purchase_receipt' として扱う
            file_type = 'purchase_receipt' if ftype == 'receipt_form' else ftype
            if file_type not in ('id_document', 'purchase_receipt', 'item_photo'):
                self.not_found('ファイル種別が不正です。')
            record = model.find_latest_by_ledger_and_type(file_id, tenant_id, file_type)
        else:
            record = model.find_by_id(file_id, tenant_id)
        if record is None or int(record['tenant_id']) != tenant_id:
            self.not_found('ファイルが見つかりません。')

        upload_dir = self.cfg['upload_dir'].rstrip('/')
        path = os.path.join(upload_dir, record['file_path'])
        if not os.path.isfile(path):
            self.not_found('ファイルが見つかりません。')
        try:
            data = Crypto().decrypt_file(path, record['iv'])
        except (CryptoError, OSError):
            self.text('ファイルの復号に失敗しました。', 500)

        # ファイル名（ヘッダーインジェクション対策。日本語名は filename* で渡す）
        original = str(record['original_filename'] or '')
        ascii_name = re.sub(r'[^A-Za-z0-9_.\-]', '_', original) or 'download'
        utf8_name = rawurlencode(original.replace('\r', '').replace('\n', '').replace('"', ''))
        mime = record['mime_type'] or 'application/octet-stream'
        # inline=1 かつ画像の場合はブラウザ内で表示（商品画像のプレビュー）
        inline = self.request.get('inline') == '1' and str(record['mime_type'] or '').startswith('image/')
        resp = Response(data, 200, mime, [
            ('Content-Disposition', '%s; filename="%s"; filename*=UTF-8\'\'%s'
             % ('inline' if inline else 'attachment', ascii_name, utf8_name)),
            ('Content-Length', str(len(data))),
            ('Cache-Control', 'no-store, no-cache, must-revalidate'),
            ('Pragma', 'no-cache'),
            ('X-Content-Type-Options', 'nosniff'),
        ])
        try:
            AuditLog(self.db).log(tenant_id, user_id, self.user_name(), None, 'export', file_id, None,
                                  {'file_type': record['file_type'], 'original_filename': record['original_filename']},
                                  self.request.ip())
        except Exception as e:
            log_error('AuditLog 書き込みエラー: %s' % e)
        raise ResponseDone(resp)
