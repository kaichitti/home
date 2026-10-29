"""
添付ファイル等の暗号化（AES-256-GCM・改ざん検知付き）

PHP版と同じ形式・同じ鍵の作り方なので、PHP版で暗号化したファイルもそのまま復号できる。
  - 鍵     : SHA-256(ENCRYPTION_KEY) の 32 バイト
  - ファイル: 暗号文だけをファイルに保存し、"IVの16進:認証タグの16進" を DB の iv 列に保存
  - 文字列  : base64( "FDC1" + IV(12) + タグ(16) + 暗号文 )
  - 旧形式  : 旧バージョンの AES-256-CBC（認証なし）も復号のみ対応

暗号の計算は、サーバーの OS が持つ OpenSSL（libcrypto）で行う（Python の hashlib 等と同じもの。
追加インストール不要）。cryptography パッケージが入っている環境ではそちらを使う。
"""
import base64
import ctypes
import ctypes.util
import hashlib
import os
import re
import secrets

from .. import config

GCM_IV_LENGTH = 12
GCM_TAG_LENGTH = 16
CBC_IV_LENGTH = 16
MAGIC = b'FDC1'


class CryptoError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 暗号エンジン（OpenSSL を ctypes で呼ぶ / cryptography パッケージ）
# ---------------------------------------------------------------------------

class _OpenSSL:
    EVP_CTRL_GCM_SET_IVLEN = 0x9
    EVP_CTRL_GCM_GET_TAG = 0x10
    EVP_CTRL_GCM_SET_TAG = 0x11

    def __init__(self):
        lib = None
        names = [ctypes.util.find_library('crypto'), 'libcrypto.so.3', 'libcrypto.so.1.1',
                 'libcrypto.so.10', 'libcrypto.so']
        for name in names:
            if not name:
                continue
            try:
                lib = ctypes.CDLL(name)
                break
            except OSError:
                continue
        if lib is None:
            raise CryptoError('OpenSSL（libcrypto）が見つかりません。')
        vp, cp, ci = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
        lib.EVP_CIPHER_CTX_new.restype = vp
        lib.EVP_CIPHER_CTX_new.argtypes = []
        lib.EVP_CIPHER_CTX_free.argtypes = [vp]
        lib.EVP_CIPHER_CTX_free.restype = None
        lib.EVP_aes_256_gcm.restype = vp
        lib.EVP_aes_256_cbc.restype = vp
        for fn in (lib.EVP_EncryptInit_ex, lib.EVP_DecryptInit_ex):
            fn.argtypes = [vp, vp, vp, cp, cp]
            fn.restype = ci
        for fn in (lib.EVP_EncryptUpdate, lib.EVP_DecryptUpdate):
            fn.argtypes = [vp, cp, ctypes.POINTER(ci), cp, ci]
            fn.restype = ci
        for fn in (lib.EVP_EncryptFinal_ex, lib.EVP_DecryptFinal_ex):
            fn.argtypes = [vp, cp, ctypes.POINTER(ci)]
            fn.restype = ci
        lib.EVP_CIPHER_CTX_ctrl.argtypes = [vp, ci, ci, vp]
        lib.EVP_CIPHER_CTX_ctrl.restype = ci
        self.lib = lib

    def _run(self, encrypt, cipher, key, iv, data, tag=None):
        lib = self.lib
        ctx = lib.EVP_CIPHER_CTX_new()
        if not ctx:
            raise CryptoError('暗号化の準備に失敗しました。')
        try:
            init = lib.EVP_EncryptInit_ex if encrypt else lib.EVP_DecryptInit_ex
            update = lib.EVP_EncryptUpdate if encrypt else lib.EVP_DecryptUpdate
            final = lib.EVP_EncryptFinal_ex if encrypt else lib.EVP_DecryptFinal_ex
            gcm = cipher == 'gcm'
            evp = lib.EVP_aes_256_gcm() if gcm else lib.EVP_aes_256_cbc()
            if init(ctx, evp, None, None, None) != 1:
                raise CryptoError('暗号化の準備に失敗しました。')
            if gcm and lib.EVP_CIPHER_CTX_ctrl(ctx, self.EVP_CTRL_GCM_SET_IVLEN, len(iv), None) != 1:
                raise CryptoError('暗号化の準備に失敗しました。')
            if init(ctx, None, None, key, iv) != 1:
                raise CryptoError('暗号化の準備に失敗しました。')
            out = ctypes.create_string_buffer(len(data) + 32)
            outl = ctypes.c_int(0)
            if update(ctx, out, ctypes.byref(outl), data, len(data)) != 1:
                raise CryptoError('暗号化・復号に失敗しました。')
            total = outl.value
            if gcm and not encrypt:
                tag_buf = ctypes.create_string_buffer(tag, len(tag))
                if lib.EVP_CIPHER_CTX_ctrl(ctx, self.EVP_CTRL_GCM_SET_TAG, len(tag),
                                           ctypes.cast(tag_buf, ctypes.c_void_p)) != 1:
                    raise CryptoError('復号に失敗しました。')
            fin = ctypes.create_string_buffer(32)
            finl = ctypes.c_int(0)
            if final(ctx, fin, ctypes.byref(finl)) != 1:
                raise CryptoError('復号に失敗しました（データが壊れているか、鍵が違います）。')
            result = out.raw[:total] + fin.raw[:finl.value]
            if gcm and encrypt:
                tag_buf = ctypes.create_string_buffer(GCM_TAG_LENGTH)
                if lib.EVP_CIPHER_CTX_ctrl(ctx, self.EVP_CTRL_GCM_GET_TAG, GCM_TAG_LENGTH,
                                           ctypes.cast(tag_buf, ctypes.c_void_p)) != 1:
                    raise CryptoError('暗号化に失敗しました。')
                return result, tag_buf.raw
            return result, None
        finally:
            lib.EVP_CIPHER_CTX_free(ctx)

    def gcm_encrypt(self, key, iv, data):
        return self._run(True, 'gcm', key, iv, data)

    def gcm_decrypt(self, key, iv, data, tag):
        return self._run(False, 'gcm', key, iv, data, tag)[0]

    def cbc_decrypt(self, key, iv, data):
        return self._run(False, 'cbc', key, iv, data)[0]


class _Cryptography:
    def __init__(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives import padding
        self.Cipher, self.algorithms, self.modes, self.AESGCM, self.padding = Cipher, algorithms, modes, AESGCM, padding

    def gcm_encrypt(self, key, iv, data):
        out = self.AESGCM(key).encrypt(iv, data, None)
        return out[:-GCM_TAG_LENGTH], out[-GCM_TAG_LENGTH:]

    def gcm_decrypt(self, key, iv, data, tag):
        try:
            return self.AESGCM(key).decrypt(iv, data + tag, None)
        except Exception:
            raise CryptoError('復号に失敗しました（データが壊れているか、鍵が違います）。') from None

    def cbc_decrypt(self, key, iv, data):
        try:
            d = self.Cipher(self.algorithms.AES(key), self.modes.CBC(iv)).decryptor()
            padded = d.update(data) + d.finalize()
            u = self.padding.PKCS7(128).unpadder()
            return u.update(padded) + u.finalize()
        except Exception:
            raise CryptoError('復号に失敗しました。') from None


_engine = None


def engine():
    global _engine
    if _engine is None:
        try:
            _engine = _Cryptography()
        except Exception:
            _engine = _OpenSSL()
    return _engine


# ---------------------------------------------------------------------------
# 暗号化・復号
# ---------------------------------------------------------------------------

class Crypto:
    def __init__(self, key=None):
        k = key if key is not None else config.get()['encryption_key']
        if not k:
            raise CryptoError('暗号化キーが設定されていません。環境変数 ENCRYPTION_KEY を設定してください。')
        self.key = hashlib.sha256(k.encode('utf-8')).digest()

    def encrypt(self, plain_text):
        iv = secrets.token_bytes(GCM_IV_LENGTH)
        enc, tag = engine().gcm_encrypt(self.key, iv, plain_text.encode('utf-8'))
        return base64.b64encode(MAGIC + iv + tag + enc).decode('ascii')

    def decrypt(self, cipher_text):
        try:
            raw = base64.b64decode(cipher_text, validate=True)
        except Exception:
            raise CryptoError('暗号文のフォーマットが不正です。') from None
        if raw.startswith(MAGIC):
            iv = raw[4:4 + GCM_IV_LENGTH]
            tag = raw[4 + GCM_IV_LENGTH:4 + GCM_IV_LENGTH + GCM_TAG_LENGTH]
            enc = raw[4 + GCM_IV_LENGTH + GCM_TAG_LENGTH:]
            if len(iv) != GCM_IV_LENGTH or len(tag) != GCM_TAG_LENGTH:
                raise CryptoError('暗号文のフォーマットが不正です。')
            plain = engine().gcm_decrypt(self.key, iv, enc, tag)
        else:
            if len(raw) < CBC_IV_LENGTH:
                raise CryptoError('暗号文のフォーマットが不正です。')
            plain = engine().cbc_decrypt(self.key, raw[:CBC_IV_LENGTH], raw[CBC_IV_LENGTH:])
        return plain.decode('utf-8', 'replace')

    def encrypt_file(self, source_path, dest_path):
        """ファイルを暗号化して保存し、DB に保存する "ivhex:taghex" を返す"""
        with open(source_path, 'rb') as f:
            data = f.read()
        iv = secrets.token_bytes(GCM_IV_LENGTH)
        enc, tag = engine().gcm_encrypt(self.key, iv, data)
        fd = os.open(dest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(enc)
        return iv.hex() + ':' + tag.hex()

    def decrypt_file(self, encrypted_path, iv_value):
        """暗号化ファイルを復号して中身（bytes）を返す（平文を一時ファイルに書き出さない）"""
        with open(encrypted_path, 'rb') as f:
            data = f.read()
        iv_value = iv_value or ''
        if ':' in iv_value:
            iv_hex, tag_hex = iv_value.split(':', 1)
            if not re.fullmatch(r'[0-9a-fA-F]{24}', iv_hex) or not re.fullmatch(r'[0-9a-fA-F]{32}', tag_hex):
                raise CryptoError('IV のフォーマットが不正です。')
            return engine().gcm_decrypt(self.key, bytes.fromhex(iv_hex), data, bytes.fromhex(tag_hex))
        if not re.fullmatch(r'[0-9a-fA-F]{32}', iv_value):
            raise CryptoError('IV のフォーマットが不正です。')
        return engine().cbc_decrypt(self.key, bytes.fromhex(iv_value), data)


def generate_key():
    return secrets.token_hex(32)
