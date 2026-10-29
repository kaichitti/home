"""
HTTP リクエスト（URLのパラメータ・フォーム・アップロードファイル）

- 「名前[]」「名前[キー]」形式の項目は PHP と同じく配列（dict）として受け取る。
  画面の項目はすべて1つの値なので、配列が送られてきたら各処理で「不正な入力」として扱う。
- get()/post() の値は前後の空白と制御文字（改行・タブ以外）を取り除く。
  パスワードのように加工してはいけない値は raw_post() で受け取る。
- アップロードファイルはメモリに溜めず、一時ファイルへ少しずつ書き出す。
  大きさの上限を超えたファイル・送信全体が大きすぎる場合は受け取らない。
"""
import os
import re
import tempfile
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl

from ..helpers import client_ip
from ..util import strip_controls

MAX_INPUT_VARS = 1000     # 項目数の上限（PHP の max_input_vars と同じ）
MAX_FILE_UPLOADS = 25     # 1回の送信で受け取るファイル数の上限
MAX_FIELD_BYTES = 8 * 1024 * 1024
MAX_HEADER_BYTES = 16 * 1024

UPLOAD_ERR_OK = 0
UPLOAD_ERR_INI_SIZE = 1
UPLOAD_ERR_PARTIAL = 3
UPLOAD_ERR_NO_FILE = 4

_KEY_RE = re.compile(r'^([^\[\]]+)((?:\[[^\[\]]*\])+)$')
_SUB_RE = re.compile(r'\[([^\[\]]*)\]')


class UploadedFile:
    """アップロードされた1ファイル（PHP の $_FILES の1件に相当）"""

    def __init__(self, filename, content_type, path, size, error):
        self.filename = filename        # 利用者のPCでのファイル名
        self.content_type = content_type  # ブラウザが申告した種類（信用しない）
        self.path = path                # 一時ファイルのパス
        self.size = size
        self.error = error


def _assign(result, key, value):
    """PHP と同じ規則で「名前[キー]」を配列（dict）にまとめる"""
    m = _KEY_RE.match(key)
    if not m:
        result[key] = value
        return
    base, subs = m.group(1), _SUB_RE.findall(m.group(2))
    cur = result.get(base)
    if not isinstance(cur, dict):
        cur = {}
        result[base] = cur
    for i, sub in enumerate(subs):
        last = i == len(subs) - 1
        if sub == '':
            sub = len([k for k in cur if isinstance(k, int)])
            while sub in cur:
                sub += 1
        if last:
            cur[sub] = value
        else:
            nxt = cur.get(sub)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[sub] = nxt
            cur = nxt


def _parse_pairs(pairs):
    result = {}
    for i, (k, v) in enumerate(pairs):
        if i >= MAX_INPUT_VARS:
            break
        _assign(result, k, v)
    return result


def _sanitize(value):
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, str):
        # PHP の trim() と同じ文字だけを取り除く（全角スペースなどは残す）
        return strip_controls(value).strip(' \t\n\r\0\x0b')
    return value


def _header_params(value):
    """Content-Disposition 等の「; 名前="値"」を辞書にする"""
    params = {}
    for m in re.finditer(r';\s*([A-Za-z0-9_*.-]+)\s*=\s*("((?:\\.|[^"\\])*)"|[^;]*)', value):
        name = m.group(1).lower()
        v = m.group(3) if m.group(3) is not None else m.group(2).strip()
        if m.group(3) is not None:
            v = re.sub(r'\\(.)', r'\1', v)
        params[name] = v
    return params


class _Stream:
    def __init__(self, stream, length):
        self.stream = stream
        self.remaining = length
        self.buf = b''

    def fill(self):
        if self.remaining <= 0:
            return False
        chunk = self.stream.read(min(65536, self.remaining))
        if not chunk:
            self.remaining = 0
            return False
        self.remaining -= len(chunk)
        self.buf += chunk
        return True


def parse_multipart(stream, length, boundary, tmp_dir, max_file_size):
    """multipart/form-data を読み、(項目のリスト, ファイルのリスト) を返す"""
    fields, files = [], []
    s = _Stream(stream, length)
    delim = b'--' + boundary
    sep = b'\r\n' + delim
    # 最初の区切りまで読み飛ばす
    while True:
        i = s.buf.find(delim)
        if i >= 0:
            s.buf = s.buf[i + len(delim):]
            break
        if len(s.buf) > len(delim):
            s.buf = s.buf[-len(delim):]
        if not s.fill():
            return fields, files
    count = 0
    while True:
        while len(s.buf) < 2 and s.fill():
            pass
        if s.buf[:2] == b'--' or len(s.buf) < 2:
            break  # 終端
        if s.buf[:2] != b'\r\n':
            break  # 形式が不正
        s.buf = s.buf[2:]
        # ヘッダ
        while True:
            j = s.buf.find(b'\r\n\r\n')
            if j >= 0:
                break
            if len(s.buf) > MAX_HEADER_BYTES or not s.fill():
                return fields, files
        raw_headers = s.buf[:j].decode('utf-8', 'replace')
        s.buf = s.buf[j + 4:]
        headers = {}
        for line in raw_headers.split('\r\n'):
            if ':' in line:
                hk, hv = line.split(':', 1)
                headers[hk.strip().lower()] = hv.strip()
        disp = headers.get('content-disposition', '')
        params = _header_params(disp)
        name = params.get('name')
        is_file = 'filename' in params or 'filename*' in params
        count += 1

        # 本文を読み、区切りが来るまで書き出す
        sink_file = None
        sink_path = None
        size = 0
        too_large = False
        data = bytearray()
        accept = name is not None and count <= MAX_INPUT_VARS
        if is_file and accept and params.get('filename', '') != '' and \
                len([f for f in files if f[1].error != UPLOAD_ERR_NO_FILE]) < MAX_FILE_UPLOADS:
            fd, sink_path = tempfile.mkstemp(prefix='up_', dir=tmp_dir)
            sink_file = os.fdopen(fd, 'wb')

        def write(chunk):
            nonlocal size, too_large
            size += len(chunk)
            if sink_file is not None:
                if size > max_file_size:
                    too_large = True
                elif not too_large:
                    sink_file.write(chunk)
            elif not is_file and accept and len(data) < MAX_FIELD_BYTES:
                data.extend(chunk[:MAX_FIELD_BYTES - len(data)])

        finished = False
        while True:
            k = s.buf.find(sep)
            if k >= 0:
                write(s.buf[:k])
                s.buf = s.buf[k + len(sep):]
                finished = True
                break
            keep = len(sep) - 1
            if len(s.buf) > keep:
                write(s.buf[:-keep])
                s.buf = s.buf[-keep:]
            if not s.fill():
                break
        if sink_file is not None:
            sink_file.close()
        if is_file and accept:
            filename = params.get('filename', '')
            if sink_path is None:
                files.append((name, UploadedFile(filename, headers.get('content-type', ''), None, 0,
                                                 UPLOAD_ERR_NO_FILE if filename == '' else UPLOAD_ERR_INI_SIZE)))
            else:
                error = UPLOAD_ERR_OK
                if too_large:
                    error = UPLOAD_ERR_INI_SIZE
                elif not finished:
                    error = UPLOAD_ERR_PARTIAL
                if error != UPLOAD_ERR_OK:
                    try:
                        os.unlink(sink_path)
                    except OSError:
                        pass
                    sink_path = None
                files.append((name, UploadedFile(os.path.basename(filename.replace('\\', '/')),
                                                 headers.get('content-type', ''), sink_path,
                                                 size if error == UPLOAD_ERR_OK else 0, error)))
        elif accept and not is_file:
            fields.append((name, bytes(data).decode('utf-8', 'replace')))
        if not finished:
            break
    return fields, files


class Request:
    def __init__(self, environ, cfg, tmp_dir):
        self.environ = environ
        self.cfg = cfg
        self.method = environ.get('REQUEST_METHOD', 'GET').upper()
        self.query = _parse_pairs(parse_qsl(environ.get('QUERY_STRING', ''), keep_blank_values=True))
        self.form = {}
        self.files = {}
        self.too_large = False
        self._temp_paths = []
        if self.method == 'POST':
            self._parse_body(tmp_dir)
        self.cookies = {}
        try:
            c = SimpleCookie()
            c.load(environ.get('HTTP_COOKIE', ''))
            self.cookies = {k: m.value for k, m in c.items()}
        except Exception:
            self.cookies = {}

    def _parse_body(self, tmp_dir):
        try:
            length = int(self.environ.get('CONTENT_LENGTH') or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return
        stream = self.environ['wsgi.input']
        if length > self.cfg['max_post_size']:
            # PHP の post_max_size 超過と同じく、送信内容は受け取らない
            self.too_large = True
            return
        ctype = self.environ.get('CONTENT_TYPE', '')
        if ctype.lower().startswith('multipart/form-data'):
            boundary = _header_params(ctype).get('boundary', '')
            if not boundary or len(boundary) > 200:
                return
            os.makedirs(tmp_dir, mode=0o700, exist_ok=True)
            fields, files = parse_multipart(stream, length, boundary.encode('latin-1', 'replace'),
                                            tmp_dir, self.cfg['max_file_size'])
            self.form = _parse_pairs(fields)
            for name, f in files:
                if f.path:
                    self._temp_paths.append(f.path)
                _assign(self.files, name, f)
        elif ctype.lower().startswith('application/x-www-form-urlencoded') or ctype == '':
            body = stream.read(length)
            self.form = _parse_pairs(parse_qsl(body.decode('latin-1'), keep_blank_values=True,
                                               encoding='utf-8', errors='replace'))

    def cleanup(self):
        """受け取った一時ファイルを削除する（保存済みのものは移動・暗号化済み）"""
        for p in self._temp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    # -- 値の取得 -------------------------------------------------------------
    def get(self, key, default=None):
        if key not in self.query:
            return default
        return _sanitize(self.query[key])

    def post(self, key, default=None):
        if key not in self.form:
            return default
        return _sanitize(self.form[key])

    def raw_post(self, key):
        """加工しない値（パスワード用）。文字列でなければ空文字"""
        v = self.form.get(key)
        return v if isinstance(v, str) else ''

    def all(self):
        return {k: _sanitize(v) for k, v in self.form.items()}

    def get_str(self, key, default=''):
        v = self.get(key, default)
        return v if isinstance(v, str) else default

    def post_str(self, key, default=''):
        v = self.post(key, default)
        return v if isinstance(v, str) else default

    def file(self, key):
        f = self.files.get(key)
        return f if isinstance(f, UploadedFile) else None

    def file_list(self, key):
        v = self.files.get(key)
        if isinstance(v, dict):
            return [x for x in v.values() if isinstance(x, UploadedFile)]
        return []

    def is_post(self):
        return self.method == 'POST'

    def page(self):
        p = self.get('page', 'dashboard')
        return p if isinstance(p, str) else ''

    def header(self, name):
        return self.environ.get('HTTP_' + name.upper().replace('-', '_'), '')

    def is_https(self):
        https = self.environ.get('HTTPS', '')
        return (https != '' and https.lower() != 'off') or self.environ.get('wsgi.url_scheme') == 'https'

    def ip(self):
        return client_ip.resolve(self.environ)

    def script_name(self):
        return self.environ.get('SCRIPT_NAME', '')
