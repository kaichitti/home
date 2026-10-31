"""
パスワードのハッシュ化と照合

- PHP版で保存した bcrypt（$2y$...）のハッシュをそのまま照合できる。
- 新しく保存するハッシュも bcrypt（コスト12）。PHP版の password_verify でも照合できるため、
  万一 PHP版に戻す場合もパスワードはそのまま使える。
- bcrypt の計算はサーバーに元からあるライブラリで行う（追加インストール不要）。
  OS の暗号ライブラリ（libcrypt）が bcrypt に対応していない古いサーバー（CentOS 7 等）では、
  Web サーバー（Apache）に必ず付属している apr-util ライブラリの bcrypt を使う。
  どちらも無いサーバーでは、新しいパスワードを Python 標準の PBKDF2-SHA256（60万回）で保存する。
"""
import base64
import ctypes
import ctypes.util
import hashlib
import hmac
import re
import secrets
import warnings

DEFAULT_PASSWORD = 'Admin7777'   # 公開されている初期パスワード（そのままの利用は認めない）
BCRYPT_COST = 12
PBKDF2_ITERATIONS = 600000

# 動作確認用（パスワード "selftest"・コスト4）
_SELFTEST_HASH = '$2y$04$Ir9P1sX0nIS.l2/Oh33Nj.F8wBlGxKxEISQ7GV5ARiAi5rRSz9Rzq'
# 存在しないアカウントへの試行でも、実在アカウントと同じ時間をかけるためのダミー（コスト12）
_DUMMY_BCRYPT = '$2y$12$.5Ru9KcZkaqSGXVtpIfXku74emfoYJgnHpRR4NhUe4A2zuhgtDeo2'
_DUMMY_PBKDF2 = 'pbkdf2_sha256$600000$ZHVtbXlzYWx0ZHVtbXk=$EGzDYQYzH0Q+gXkV6Yu9z1Yk2N8cqtJ1x0Q7J8a9b0c='

_BCRYPT_RE = re.compile(r'^\$2[abxy]\$(\d\d)\$[./A-Za-z0-9]{53}$')
_B64 = './ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'


def _bcrypt_b64(data):
    """bcrypt 独自の base64 で符号化する（塩 16 バイト → 22 文字）"""
    out = []
    i = 0
    while i < len(data):
        c1 = data[i]
        i += 1
        out.append(_B64[c1 >> 2])
        c1 = (c1 & 0x03) << 4
        if i >= len(data):
            out.append(_B64[c1])
            break
        c2 = data[i]
        i += 1
        c1 |= c2 >> 4
        out.append(_B64[c1])
        c1 = (c2 & 0x0f) << 2
        if i >= len(data):
            out.append(_B64[c1])
            break
        c2 = data[i]
        i += 1
        c1 |= c2 >> 6
        out.append(_B64[c1])
        out.append(_B64[c2 & 0x3f])
    return ''.join(out)


def _bcrypt_b64_decode(text, size=16):
    """bcrypt 独自の base64 を復号する（塩 22 文字 → 16 バイト）"""
    bits, nbits, out = 0, 0, bytearray()
    for ch in text:
        bits = (bits << 6) | _B64.index(ch)
        nbits += 6
        if nbits >= 8:
            nbits -= 8
            out.append((bits >> nbits) & 0xff)
            if len(out) == size:
                break
    return bytes(out)


# ---------------------------------------------------------------------------
# bcrypt の計算方法を選ぶ（使えるものを1つ）
# ---------------------------------------------------------------------------

def _backend_bcrypt_module():
    import bcrypt  # 任意（pip で入っている場合のみ）

    def run(password_bytes, setting):
        setting_b = setting.encode('ascii')
        if setting_b.startswith(b'$2y$'):
            setting_b = b'$2b$' + setting_b[4:]
        out = bcrypt.hashpw(password_bytes[:72], setting_b).decode('ascii')
        return '$2y$' + out[4:] if setting.startswith('$2y$') else out
    return run


def _backend_crypt_module():
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        import crypt  # Python 3.12 まで標準

    def run(password_bytes, setting):
        return crypt.crypt(password_bytes.decode('utf-8', 'surrogateescape'), setting)
    return run


def _backend_libcrypt():
    path = ctypes.util.find_library('crypt') or 'libcrypt.so.1'
    lib = ctypes.CDLL(path)
    fn = lib.crypt
    fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    fn.restype = ctypes.c_char_p

    def run(password_bytes, setting):
        r = fn(password_bytes, setting.encode('ascii'))
        return r.decode('ascii', 'replace') if r else None
    return run


def _backend_aprutil():
    """Apache の apr-util（libaprutil-1）の bcrypt を使う（CentOS 7 等の古いサーバー向け）"""
    candidates = [ctypes.util.find_library('aprutil-1'), 'libaprutil-1.so.0', 'libaprutil-1.so',
                  '/usr/lib64/libaprutil-1.so.0', '/usr/lib/x86_64-linux-gnu/libaprutil-1.so.0',
                  '/usr/local/apache2/lib/libaprutil-1.so.0', '/usr/local/lib/libaprutil-1.so.0']
    lib = None
    for name in candidates:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if lib is None:
        raise OSError('libaprutil-1 not found')
    fn = lib.apr_bcrypt_encode
    fn.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p,
                   ctypes.c_size_t]
    fn.restype = ctypes.c_int

    def run(password_bytes, setting):
        m = re.match(r'^\$2([abxy])\$(\d\d)\$([./A-Za-z0-9]{22})', setting)
        if not m:
            return None
        salt = _bcrypt_b64_decode(m.group(3))
        out = ctypes.create_string_buffer(64)
        if fn(password_bytes, int(m.group(2)), salt, len(salt), out, len(out)) != 0:
            return None
        result = out.value.decode('ascii', 'replace')
        # apr-util は常に $2y$ で返す（72バイト以内のパスワードでは $2b$ と同じ計算）
        return '$2' + m.group(1) + result[3:] if result.startswith('$2y$') else result
    return run


_backend = None
_backend_checked = False


def bcrypt_backend():
    """bcrypt を計算できる関数（使えなければ None）"""
    global _backend, _backend_checked
    if _backend_checked:
        return _backend
    _backend_checked = True
    for factory in (_backend_bcrypt_module, _backend_crypt_module, _backend_libcrypt, _backend_aprutil):
        try:
            fn = factory()
            if fn(b'selftest', _SELFTEST_HASH) == _SELFTEST_HASH:
                _backend = fn
                break
        except Exception:
            continue
    return _backend


# ---------------------------------------------------------------------------
# ハッシュ化・照合
# ---------------------------------------------------------------------------

def hash_password(password):
    pw = password.encode('utf-8')
    if b'\0' in pw:
        raise ValueError('password contains NUL')
    backend = bcrypt_backend()
    if backend is not None:
        setting = '$2y$%02d$%s' % (BCRYPT_COST, _bcrypt_b64(secrets.token_bytes(16)))
        result = backend(pw, setting)
        if result and _BCRYPT_RE.match(result):
            return result
    salt = base64.b64encode(secrets.token_bytes(16)).decode('ascii')
    dk = hashlib.pbkdf2_hmac('sha256', pw, salt.encode('ascii'), PBKDF2_ITERATIONS)
    return 'pbkdf2_sha256$%d$%s$%s' % (PBKDF2_ITERATIONS, salt, base64.b64encode(dk).decode('ascii'))


def verify(password, stored):
    """パスワードがハッシュと一致するか（時間差で推測されないよう一定時間で比較する）"""
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    pw = password.encode('utf-8')
    if b'\0' in pw:
        dummy_verify(password.replace('\0', ''))
        return False
    if _BCRYPT_RE.match(stored):
        backend = bcrypt_backend()
        if backend is None:
            raise RuntimeError('このサーバーでは bcrypt のパスワードを照合できません（libcrypt・libaprutil-1 のどちらも bcrypt に対応していません）')
        result = backend(pw, stored)
        return bool(result) and hmac.compare_digest(result, stored)
    if stored.startswith('pbkdf2_sha256$'):
        parts = stored.split('$')
        if len(parts) != 4:
            return False
        try:
            iterations = int(parts[1])
            expected = base64.b64decode(parts[3])
        except (ValueError, TypeError):
            return False
        if iterations < 1 or iterations > 10000000:
            return False
        dk = hashlib.pbkdf2_hmac('sha256', pw, parts[2].encode('ascii'), iterations)
        return hmac.compare_digest(dk, expected)
    return False


def dummy_verify(password):
    """存在しないアカウント等でも、本物の照合と同じだけ時間をかける"""
    try:
        if bcrypt_backend() is not None:
            verify(password, _DUMMY_BCRYPT)
        else:
            verify(password, _DUMMY_PBKDF2)
    except Exception:
        pass
    return False


def needs_rehash(stored):
    """今の方式（bcrypt コスト12 など）で保存し直すべきか"""
    m = _BCRYPT_RE.match(stored or '')
    if bcrypt_backend() is not None:
        return not (m and stored.startswith('$2y$') and int(m.group(1)) == BCRYPT_COST)
    if stored.startswith('pbkdf2_sha256$'):
        parts = stored.split('$')
        return len(parts) != 4 or parts[1] != str(PBKDF2_ITERATIONS)
    return False  # bcrypt を照合できない環境では書き換えない


def policy_error(password, min_length=8):
    """パスワードポリシー違反のメッセージ（問題なければ None）
    規則: 最小文字数以上・英字と数字を1文字以上・72バイト以内・公開されている初期パスワードは不可"""
    if not isinstance(password, str) or password == '':
        return 'パスワードを入力してください。'
    if '\0' in password:
        return 'パスワードに使用できない文字が含まれています。'
    if len(password.encode('utf-8')) > 72:
        # bcrypt は72バイトを超える部分を無視するため上限を設ける
        return 'パスワードは72バイト（半角72文字）以内で入力してください。'
    if len(password) < min_length or not is_alpha_numeric(password):
        return 'パスワードは%d文字以上で、英字・数字をそれぞれ1文字以上含めてください。' % min_length
    if hmac.compare_digest(DEFAULT_PASSWORD.encode('utf-8'), password.encode('utf-8')):
        return '初期パスワード（公開されている値）は使用できません。別のパスワードを設定してください。'
    return None


def is_alpha_numeric(value):
    return re.search(r'[a-zA-Z]', value) is not None and re.search(r'[0-9]', value) is not None


def equals(a, b):
    """文字列の一定時間比較（hash_equals 相当）"""
    return hmac.compare_digest(a.encode('utf-8'), b.encode('utf-8'))
