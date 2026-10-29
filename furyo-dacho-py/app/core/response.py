"""
HTTP レスポンス

画面を返す・リダイレクトする・JSON を返すときは、その場で処理を終えるために
ResponseDone 例外を投げる（PHP 版の exit と同じ使い方）。最上位（wsgi.py）が受け取って送信する。
"""
import json

from .template import escape

STATUS_TEXT = {
    200: 'OK', 302: 'Found', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
    404: 'Not Found', 405: 'Method Not Allowed', 409: 'Conflict', 413: 'Payload Too Large',
    429: 'Too Many Requests', 500: 'Internal Server Error',
}

# どの画面にも付けるセキュリティヘッダ（PHP版 .htaccess と同じ内容。mod_headers が無くても効くように）
SECURITY_HEADERS = [
    ('X-Content-Type-Options', 'nosniff'),
    ('X-Frame-Options', 'SAMEORIGIN'),
    ('X-XSS-Protection', '0'),
    ('Referrer-Policy', 'strict-origin-when-cross-origin'),
    ('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
                                "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"),
]


class Response:
    def __init__(self, body=b'', status=200, content_type='text/html; charset=UTF-8', headers=None):
        self.status = status
        self.headers = [('Content-Type', content_type)] if content_type else []
        if headers:
            self.headers.extend(headers)
        self.body = body          # bytes または bytes を返すイテレータ（ファイル送信）
        self.cleanup = []         # 送信後に呼ぶ関数（一時ファイルの削除など）

    def add_header(self, name, value):
        self.headers.append((name, value))

    def status_line(self):
        return '%d %s' % (self.status, STATUS_TEXT.get(self.status, 'OK'))


class ResponseDone(Exception):
    """処理を終えてこのレスポンスを返す"""

    def __init__(self, response):
        super().__init__('response')
        self.response = response


def html(text, status=200):
    return Response(str(text).encode('utf-8'), status)


def redirect(url):
    r = Response(b'', 302, content_type=None)
    r.add_header('Location', url)
    return r


def json_response(data, status=200, no_store=False):
    # PHP版の json_encode(…, JSON_UNESCAPED_UNICODE) と同じ書式
    body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('/', '\\/')
    r = Response(body.encode('utf-8'), status, 'application/json; charset=UTF-8')
    if no_store:
        r.add_header('Cache-Control', 'no-store')
    return r


def text(message, status=200):
    return Response(str(message).encode('utf-8'), status, 'text/plain; charset=UTF-8')


def error_page(status, title, message, is_admin=False):
    """アプリ本体のデザインに合わせたエラー画面（PHP版 Response::errorPage と同じ見た目）"""
    home_url = '/admin/index.cgi?page=dashboard' if is_admin else '/index.cgi?page=dashboard'
    home_label = '管理画面トップ' if is_admin else 'ダッシュボード'
    page = ERROR_TEMPLATE.format(title=escape(title), message=escape(message), status=int(status),
                                 home_url=home_url, home_label=home_label)
    return html(page, status)


ERROR_TEMPLATE = '''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - 古物台帳管理システム</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    font-family: -apple-system, "Segoe UI", "Hiragino Kaku Gothic ProN", Meiryo, sans-serif;
    background: #f4f5f7; color: #333;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 24px;
}}
.error-card {{
    background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.12);
    max-width: 480px; width: 100%; overflow: hidden;
}}
.error-card__header {{
    background: #1e3a5f; color: #fff; padding: 14px 20px;
    font-size: .95rem; font-weight: 600;
}}
.error-card__body {{ padding: 28px 24px; text-align: center; }}
.error-card__code {{
    font-size: 2.6rem; font-weight: 700; color: #1e3a5f; margin-bottom: 4px;
}}
.error-card__title {{ font-size: 1.05rem; font-weight: 600; margin-bottom: 12px; }}
.error-card__message {{
    font-size: .875rem; color: #666; line-height: 1.7; margin-bottom: 22px;
    white-space: pre-wrap; word-break: break-word;
}}
.btn {{
    display: inline-block; background: #1e3a5f; color: #fff; text-decoration: none;
    border: none; border-radius: 6px; padding: 10px 24px; font-size: .9rem; cursor: pointer;
}}
.btn:hover {{ background: #2a4e7f; }}
.btn-secondary {{ background: #eef1f5; color: #333; margin-left: 8px; }}
@media (max-width: 420px) {{ .btn {{ display: block; margin: 8px 0 0 !important; }} }}
.btn-secondary:hover {{ background: #dfe4ea; }}
</style>
</head>
<body>
<div class="error-card">
    <div class="error-card__header">古物台帳管理システム</div>
    <div class="error-card__body">
        <div class="error-card__code">{status}</div>
        <div class="error-card__title">{title}</div>
        <div class="error-card__message">{message}</div>
        <a href="javascript:history.back()" class="btn">前のページに戻る</a>
        <a href="{home_url}" class="btn btn-secondary">{home_label}</a>
    </div>
</div>
</body>
</html>'''
