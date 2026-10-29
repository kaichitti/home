"""
ファイルアップロード

- ファイルの種類は、利用者が付けた拡張子やブラウザの申告ではなく「ファイルの中身（先頭のバイト列）」で判定する
  （拡張子を偽装したファイルを受け付けない）。
- 保存名はランダムな UUID にし、利用者が付けたファイル名はサーバーのパスに使わない。
- 保存時に AES-256-GCM で暗号化する（平文はディスクに残さない）。
"""
import os
import re
import uuid

from .. import config
from ..core.request import UPLOAD_ERR_OK
from .crypto import Crypto

ALLOWED_EXTENSIONS = ('jpg', 'jpeg', 'png', 'gif', 'webp', 'pdf')
_HTML_TAG = re.compile(rb'<(script|html|head|title|body|iframe|h1|style|table|div|font|br|p>|b>|a\s+href)', re.I)


def detect_mime(path):
    """ファイルの中身から種類（MIME タイプ）を判定する（PHP の finfo と同じ名前を返す）"""
    try:
        with open(path, 'rb') as f:
            head = f.read(4096)
    except OSError:
        return 'application/octet-stream'
    return detect_mime_bytes(head)


def detect_mime_bytes(head):
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head.startswith(b'GIF87a') or head.startswith(b'GIF89a'):
        return 'image/gif'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    if head.startswith(b'%PDF-'):
        return 'application/pdf'
    if head[:4] == b'RIFF' and head[8:12] == b'WAVE':
        return 'audio/x-wav'
    if head.startswith(b'PK\x03\x04'):
        return 'application/zip'
    if head[4:12] in (b'ftypheic', b'ftypheix', b'ftypmif1', b'ftypmsf1'):
        return 'image/heic'
    if head.startswith(b'BM'):
        return 'image/bmp'
    if head.startswith(b'II*\x00') or head.startswith(b'MM\x00*'):
        return 'image/tiff'
    if head == b'':
        return 'application/x-empty'
    stripped = head.lstrip()
    if stripped[:5].lower() == b'<?xml' or stripped[:4].lower() == b'<svg':
        return 'image/svg+xml' if b'<svg' in head.lower() else 'text/xml'
    if stripped[:14].lower() == b'<!doctype html' or stripped[:5].lower() == b'<html':
        return 'text/html'
    try:
        head.decode('utf-8')
        is_text = b'\x00' not in head
    except UnicodeDecodeError as e:
        # 4096バイトの境目で文字が切れた場合はテキストとみなす
        is_text = e.start >= len(head) - 3 and b'\x00' not in head
    if is_text and _HTML_TAG.search(head):
        return 'text/html'
    return 'text/plain' if is_text else 'application/octet-stream'


def extension(filename):
    """ファイル名から拡張子（許可したものだけ。それ以外は bin）"""
    base = os.path.basename((filename or '').replace('\\', '/'))
    ext = base.rsplit('.', 1)[1].lower() if '.' in base else ''
    return ext if ext in ALLOWED_EXTENSIONS else 'bin'


class UploadError(RuntimeError):
    pass


class FileUpload:
    def __init__(self):
        cfg = config.get()
        self.upload_dir = cfg['upload_dir'].rstrip('/')
        self.allowed = cfg['allowed_mime_types']
        self.max_size = cfg['max_file_size']

    def save(self, file, tenant_id, ledger_id, file_type):
        """検証して暗号化保存し、DB に記録する情報を返す（失敗時は UploadError）"""
        self.validate(file)
        stored = str(uuid.uuid4()) + '.' + extension(file.filename)
        dest_dir = os.path.join(self.upload_dir, str(int(tenant_id)), str(int(ledger_id)))
        try:
            os.makedirs(dest_dir, mode=0o700, exist_ok=True)
        except OSError:
            raise UploadError('アップロードディレクトリの作成に失敗しました: %s' % dest_dir) from None
        mime = detect_mime(file.path)
        iv = Crypto().encrypt_file(file.path, os.path.join(dest_dir, stored))
        try:
            os.unlink(file.path)
        except OSError:
            pass
        return {
            'stored_filename': stored,
            'file_path': '%d/%d/%s' % (int(tenant_id), int(ledger_id), stored),
            'iv': iv,
            'original_filename': os.path.basename(file.filename.replace('\\', '/')),
            'file_size': file.size,
            'mime_type': mime,
        }

    def delete(self, relative_path):
        full = os.path.join(self.upload_dir, relative_path)
        if not os.path.exists(full):
            return False
        os.unlink(full)
        return True

    def validate(self, file):
        if file is None or file.error != UPLOAD_ERR_OK or not file.path:
            raise UploadError('ファイルのアップロードに失敗しました。エラーコード: %s'
                              % (file.error if file is not None else 'unknown'))
        if file.size > self.max_size:
            mb = round(self.max_size / 1048576, 1)
            raise UploadError('ファイルサイズが上限（%sMB）を超えています。' % _php_round_str(mb))
        mime = detect_mime(file.path)
        if mime not in self.allowed:
            raise UploadError('許可されていないファイル形式です。（%s）' % mime)


def _php_round_str(v):
    return str(int(v)) if float(v).is_integer() else str(v)
