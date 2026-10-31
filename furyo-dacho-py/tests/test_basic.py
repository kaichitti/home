"""
基本部品の自動テスト（DB不要・標準ライブラリだけで動く）

  python3 -m unittest discover -s tests -v

期待値の多くは PHP版で実際に計算した結果。PHP版と同じ表示・計算になっているかを確かめる。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402,F401  （lib/ を読み込めるようにする）
from app import util  # noqa: E402
from app.core import template  # noqa: E402
from app.helpers import code128, crypto, csv_writer, passwords, pos_calculator  # noqa: E402


class UtilTest(unittest.TestCase):
    """PHP の関数と同じ結果になること"""

    def test_number_format(self):
        self.assertEqual(util.number_format(1234567.5), '1,234,568')
        self.assertEqual(util.number_format(-0.5), '-1')
        self.assertEqual(util.number_format(2.5), '3')
        self.assertEqual(util.number_format(1234.565, 2), '1,234.57')

    def test_round(self):
        self.assertEqual(util.php_round(2.5), 3)
        self.assertEqual(util.php_round(-2.5), -3)

    def test_strimwidth(self):
        self.assertEqual(util.mb_strimwidth('あいうえおかきくけこ', 10), 'あいうえ…')
        self.assertEqual(util.mb_strimwidth('abcdefghij', 8), 'abcdefg…')

    def test_escape(self):
        self.assertEqual(util.html_escape('<a href="x">&\'</a>'),
                         '&lt;a href=&quot;x&quot;&gt;&amp;&#039;&lt;/a&gt;')

    def test_json_for_script(self):
        self.assertEqual(util.json_for_script({'a': '</script>', 'b': '日本', 'c': 'x"y'}),
                         '{"a":"\\u003C\\/script\\u003E","b":"日本","c":"x\\u0022y"}')

    def test_http_build_query(self):
        self.assertEqual(util.http_build_query({'page': 'pos', 'q': 'a b&c', 'list': [1, 2], 'n': None, 't': True}),
                         'page=pos&q=a+b%26c&list%5B0%5D=1&list%5B1%5D=2&t=1')

    def test_trim_and_kana(self):
        self.assertEqual(util.trim(' \t\n\r\0\x0babc \x0b'), 'abc')
        self.assertEqual(util.trim('　abc　'), '　abc　')  # 全角スペースは残す（PHP と同じ）
        self.assertEqual(util.mb_convert_kana_a('ＡＢＣ１２３'), 'ABC123')
        self.assertEqual(util.mb_convert_kana_n('１２３ＡＢ'), '123ＡＢ')

    def test_to_int_like_php(self):
        # PHP の (int) と同じ結果（PHP 8.3 で確認した値）
        cases = {'12abc': 12, ' 12': 12, '\u3000 12': 0, '１２': 0, '1e3': 1000, '1.5e2': 150, '1e-3': 0,
                 '0x1A': 0, '1.9': 1, '-1.9': -1, '9999999999999999999999': 9223372036854775807,
                 '1e30': 9223372036854775807, '1e999': 0, '': 0, 'abc': 0}
        for s, expected in cases.items():
            self.assertEqual(util.to_int(s), expected, repr(s))
        self.assertEqual(util.to_int({0: 'a'}), 1)   # 空でない配列は 1
        self.assertEqual(util.to_int({}), 0)
        self.assertEqual(util.to_int(1e19), -8446744073709551616)  # 範囲外の小数は 64 ビットで折り返す

    def test_numeric_ascii_only(self):
        self.assertTrue(util.is_numeric(' 1e3 '))
        self.assertFalse(util.is_numeric('１２３'))
        self.assertIsNone(util.parse_date('２０２６-１０-２９'))

    def test_filter_int(self):
        from app.helpers.validator import _filter_int
        for s in ('0', '-0', '+5', ' 1', '1 ', '\n1\n', '9223372036854775807'):
            self.assertTrue(_filter_int(s), repr(s))
        for s in ('00', '012', '1.0', '\f1', '9223372036854775808', '', ' ', '１', '\u30001'):
            self.assertFalse(_filter_int(s), repr(s))

    def test_is_empty(self):
        for v in (None, '', '0', 0, 0.0, [], {}, False):
            self.assertTrue(util.is_empty(v), repr(v))
        for v in ('a', '0.0', ' ', 1, [0]):
            self.assertFalse(util.is_empty(v), repr(v))


class TemplateTest(unittest.TestCase):
    def test_autoescape_and_raw(self):
        from app import paths
        saved = paths.VIEWS_DIR
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'unittest_tpl.html'), 'w', encoding='utf-8') as f:
                f.write('{{ v }}|{{ raw(v) }}|{% if n > 1 %}多{% else %}少{% endif %}'
                        '|{% for x in xs %}{{ x }},{% endfor %}')
            paths.VIEWS_DIR = d
            try:
                out = template.Renderer({'raw': template.raw}).render('unittest_tpl', {'v': '<b>"&', 'n': 2, 'xs': [1, 2]})
            finally:
                paths.VIEWS_DIR = saved
                template._CACHE.pop('unittest_tpl', None)
        self.assertEqual(out, '&lt;b&gt;&quot;&amp;|<b>"&|多|1,2,')


class PasswordTest(unittest.TestCase):
    # PHP の password_hash('Passw0rd!xyz', PASSWORD_BCRYPT, ['cost' => 4]) の結果
    PHP_HASH = '$2y$04$pFHFSrE85O4huSjmHfKdluAo04cbpMfqc76Ny3VOyK47fLRLB5cvC'

    @unittest.skipIf(passwords.bcrypt_backend() is None, 'このサーバーでは bcrypt を使えない')
    def test_php_hash(self):
        self.assertTrue(passwords.verify('Passw0rd!xyz', self.PHP_HASH))
        self.assertFalse(passwords.verify('passw0rd!xyz', self.PHP_HASH))

    def test_roundtrip(self):
        h = passwords.hash_password('Abcdef123456')
        self.assertTrue(passwords.verify('Abcdef123456', h))
        self.assertFalse(passwords.verify('Abcdef1234567', h))
        self.assertFalse(passwords.verify('Abc\0def', h))

    def test_pbkdf2(self):
        import base64
        import hashlib
        salt = 'c2FsdHNhbHQ='
        dk = hashlib.pbkdf2_hmac('sha256', b'Secret123', salt.encode('ascii'), 1000)
        stored = 'pbkdf2_sha256$1000$%s$%s' % (salt, base64.b64encode(dk).decode('ascii'))
        self.assertTrue(passwords.verify('Secret123', stored))
        self.assertFalse(passwords.verify('Secret124', stored))

    def test_policy(self):
        self.assertIsNotNone(passwords.policy_error('short1'))
        self.assertIsNotNone(passwords.policy_error('abcdefghij'))      # 数字なし
        self.assertIsNotNone(passwords.policy_error('Admin7777'))       # 公開されている初期パスワード
        self.assertIsNone(passwords.policy_error('Abcdef123456'))

    def test_b64(self):
        raw = bytes(range(16))
        self.assertEqual(passwords._bcrypt_b64_decode(passwords._bcrypt_b64(raw)), raw)


class CryptoTest(unittest.TestCase):
    # PHP版の Crypto('unit-test-key-0123456789')->encrypt('古物台帳テスト ABC-123') の結果
    PHP_CIPHER = 'RkRDMV7wWWnlOiy8D8d+AX+4eLURUkWI2MfvK53KFh6gx2X2BvmtAVCyoQgDocyrehIiurw5bbnNPAtndA=='

    def test_decrypt_php(self):
        c = crypto.Crypto('unit-test-key-0123456789')
        self.assertEqual(c.decrypt(self.PHP_CIPHER), '古物台帳テスト ABC-123')

    def test_wrong_key(self):
        with self.assertRaises(crypto.CryptoError):
            crypto.Crypto('another-key').decrypt(self.PHP_CIPHER)

    def test_roundtrip(self):
        c = crypto.Crypto('k' * 64)
        self.assertEqual(c.decrypt(c.encrypt('あいう')), 'あいう')


class PosTest(unittest.TestCase):
    def test_inclusive_tax(self):
        r = pos_calculator.calculate(
            [{'quantity': 2, 'unit_price': 1980, 'line_discount': 0},
             {'quantity': 1, 'unit_price': 550, 'line_discount': 50}],
            {'type': 'percent', 'value': 10}, {'rate': 10, 'mode': 'inclusive', 'rounding': 'floor'})
        self.assertEqual((r['subtotal'], r['discount_amount'], r['total'], r['tax_amount']), (4460, 446, 4014, 364))
        self.assertEqual(sum(l['allocated'] for l in r['lines']), r['total'])

    def test_exclusive_tax(self):
        r = pos_calculator.calculate([{'quantity': 3, 'unit_price': 333}], {'type': 'none'},
                                     {'rate': 8, 'mode': 'exclusive', 'rounding': 'ceil'})
        self.assertEqual((r['subtotal'], r['tax_amount'], r['total']), (999, 80, 1079))

    def test_errors(self):
        with self.assertRaises(pos_calculator.CalcError):
            pos_calculator.calculate([], {}, {})
        with self.assertRaises(pos_calculator.CalcError):
            pos_calculator.payment('cash', 1000, 999)
        self.assertEqual(pos_calculator.payment('cash', 1000, 5000)['change'], 4000)


class RequestTest(unittest.TestCase):
    def _req(self, body, ctype='application/x-www-form-urlencoded', query=''):
        import io
        from app.core.request import Request
        environ = {'REQUEST_METHOD': 'POST', 'QUERY_STRING': query, 'CONTENT_TYPE': ctype,
                   'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
        cfg = {'max_post_size': 134217728, 'max_file_size': 52428800}
        return Request(environ, cfg, tempfile.gettempdir())

    def test_php_style_arrays(self):
        r = self._req(b'a=1&b[]=x&b[]=y&c[k]=v&d=%20t%0D%0A')
        self.assertEqual(r.post('a'), '1')
        self.assertEqual(r.post('b'), {0: 'x', 1: 'y'})
        self.assertEqual(r.post('c'), {'k': 'v'})
        self.assertEqual(r.post('d'), 't')
        self.assertEqual(r.post_str('b'), '')  # 配列は文字列として扱わない

    def test_too_large_is_drained(self):
        # CGI では送信内容を読み切らないと応答が届かないため、受け取らない場合も最後まで読む
        import io
        from app.core import request as rq
        body = b'a=' + b'x' * (rq.MAX_FORM_BYTES + 10)
        stream = io.BytesIO(body)
        environ = {'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': 'application/x-www-form-urlencoded',
                   'CONTENT_LENGTH': str(len(body)), 'wsgi.input': stream}
        r = rq.Request(environ, {'max_post_size': 134217728, 'max_file_size': 52428800}, tempfile.gettempdir())
        self.assertTrue(r.too_large)
        self.assertEqual(stream.tell(), len(body))

    def test_nesting_limit(self):
        r = self._req(b'x' + b'[]' * 65 + b'=1&ok' + b'[]' * 64 + b'=1')
        self.assertIsNone(r.post('x'))
        self.assertIsNotNone(r.post('ok'))

    def test_multipart(self):
        body = (b'--BND\r\nContent-Disposition: form-data; name="t"\r\n\r\n\xe5\x80\xa4\r\n'
                b'--BND\r\nContent-Disposition: form-data; name="f"; filename="..\\\\a.png"\r\n'
                b'Content-Type: image/png\r\n\r\n\x89PNG\r\n\x1a\nxx\r\n--BND--\r\n')
        r = self._req(body, 'multipart/form-data; boundary=BND')
        try:
            self.assertEqual(r.post('t'), '値')
            f = r.file('f')
            self.assertEqual(f.filename, 'a.png')  # パスは取り除く
            self.assertEqual(f.size, 10)
        finally:
            r.cleanup()


class ResponseTest(unittest.TestCase):
    def test_header_injection(self):
        from app.core.response import redirect
        r = redirect('/index.cgi?page=x\r\nSet-Cookie: a=b')
        self.assertEqual(dict(r.headers)['Location'], '/index.cgi?page=xSet-Cookie: a=b')


class MiscTest(unittest.TestCase):
    def test_csv_formula_injection(self):
        self.assertEqual(csv_writer.safe('=SUM(A1)'), "'=SUM(A1)")
        self.assertEqual(csv_writer.safe('普通'), '普通')

    def test_code128(self):
        m = code128.modules('12345')
        self.assertEqual(sum(m) % 11, 2)  # 各記号 11 モジュール + 終了記号 13 モジュール
        with self.assertRaises(ValueError):
            code128.modules('日本')


if __name__ == '__main__':
    unittest.main()
