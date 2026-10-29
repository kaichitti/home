"""
リクエストの受付から応答までの流れ（PHP版 public/index.php + Router + ErrorHandler に相当）

  1. 設定を読み、セッションを開始する
  2. ?page= に対応するコントローラーの処理を呼ぶ（ログイン・権限の確認を含む）
  3. 予期しないエラーは、アプリと同じデザインのエラー画面で返す（詳細はログへ）
  4. セッションを保存し、セキュリティヘッダを付けて送信する
"""
import datetime
import importlib
import os
import sys
import time
import traceback

from . import config
from .core import response as resp
from .core.auth import Auth
from .core.request import Request
from .core.response import ResponseDone
from .core.session import Session
from .db import Database
from .logger import log_error
from .routes import ADMIN_ROUTES, TENANT_ROUTES


class Context:
    """1回のリクエストで使うもの一式"""

    def __init__(self, environ, area):
        self.area = area  # 'tenant' または 'admin'
        self.environ = environ
        self.cfg = config.get()
        tmp_dir = os.path.join(self.cfg['session_dir'], '..', 'tmp')
        self.request = Request(environ, self.cfg, os.path.normpath(tmp_dir))
        name = self.cfg['admin_session_name'] if area == 'admin' else self.cfg['session_name']
        self.session = Session(self.cfg['session_dir'], name, self.request.is_https(), self.cfg['session_timeout'])
        self._db = None
        self.auth = Auth(self)

    @property
    def db(self):
        if self._db is None:
            self._db = Database()
        return self._db

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None


def _controller(path, ctx):
    module_name, class_name = path.rsplit('.', 1)
    module = importlib.import_module('app.controllers.' + module_name)
    return getattr(module, class_name)(ctx)


def dispatch_tenant(ctx):
    page = ctx.request.page()
    route = TENANT_ROUTES.get(page)
    if route is None:
        return resp.error_page(404, 'ページが見つかりません', 'ページが見つかりません。')
    controller_path, action, require_auth, role = route
    if require_auth:
        ctx.auth.require_login()
        # 初回パスワード変更が終わるまで、他の画面は使わせない（URL直打ちでも回避できない）
        if ctx.auth.must_change_password() and page not in ('change_password', 'logout'):
            return resp.redirect('/index.cgi?page=change_password')
    if role == 'admin':
        ctx.auth.require_admin_role()
    controller = _controller(controller_path, ctx)
    return getattr(controller, action)()


def dispatch_admin(ctx):
    page = ctx.request.page()
    route = ADMIN_ROUTES.get(page)
    if route is None:
        return resp.error_page(404, 'ページが見つかりません', 'ページが見つかりません。', True)
    controller_path, action, require_auth = route
    if require_auth:
        ctx.auth.require_system_admin()
        # 初期パスワード（公開値）のままの間は、パスワード変更以外の管理画面を使わせない
        if ctx.auth.admin_must_change_password() and page not in ('password', 'logout'):
            return resp.redirect('/admin/index.cgi?page=password')
    controller = _controller(controller_path, ctx)
    return getattr(controller, action)()


def _error_response(ctx, exc, environ, area):
    debug = config.is_debug()
    where = ''
    try:
        from .core.template import describe_error
        where = describe_error(exc)
    except Exception:
        pass
    log_error('Uncaught %s: %s %s\n%s' % (type(exc).__name__, exc, where, traceback.format_exc()))
    # 型の誤り（?page[]=x のような配列の送信など）は利用者側の入力不備として 400 にする
    bad_request = isinstance(exc, (TypeError, ValueError)) and not isinstance(exc, UnicodeError)
    status = 400 if bad_request else 500
    title = 'リクエストの形式が正しくありません' if bad_request else 'システムエラーが発生しました'
    message = ('入力内容の形式が正しくありません。ページを再読み込みして、もう一度お試しください。' if bad_request
               else '処理中に予期しないエラーが発生しました。\nしばらく待ってからもう一度お試しください。解決しない場合は管理者に連絡してください。')
    if debug:
        message += '\n\n[DEBUG] %s: %s\n%s' % (type(exc).__name__, exc, where or _last_frame(exc))
    if 'application/json' in environ.get('HTTP_ACCEPT', ''):
        r = resp.json_response({'ok': False, 'code': 'server', 'error': title + '。' + message.split('\n')[0]},
                               status, no_store=True)
        return r
    return resp.error_page(status, title, message, area == 'admin')


def _last_frame(exc):
    tb = traceback.extract_tb(exc.__traceback__)
    if not tb:
        return ''
    f = tb[-1]
    return '%s:%s' % (f.filename, f.lineno)


def handle(environ, area):
    """リクエストを処理して Response を返す"""
    ctx = None
    try:
        ctx = Context(environ, area)
        ctx.session.start(ctx.request.cookies.get(ctx.session.cookie_name))
        if ctx.session.get('_last_activity') is None:
            ctx.session.set('_last_activity', int(time.time()))
        try:
            result = dispatch_admin(ctx) if area == 'admin' else dispatch_tenant(ctx)
            if result is None:
                result = resp.html('')
        except ResponseDone as done:
            result = done.response
        except config.ConfigError as e:
            log_error('Config error: %s' % e)
            msg = 'サーバーの設定が完了していません。config/.env を確認してください。'
            if config.is_debug():
                msg += '\n\n[DEBUG] %s' % e
            result = resp.error_page(500, 'システムエラーが発生しました', msg, area == 'admin')
        except Exception as e:
            if ctx._db is not None and ctx._db.in_transaction:
                ctx._db.rollback()
            result = _error_response(ctx, e, environ, area)
        try:
            ctx.session.save()
        except Exception as e:
            log_error('session save failed: %s' % e)
        cookie = ctx.session.cookie_header()
        if cookie:
            result.add_header('Set-Cookie', cookie)
        return result
    except Exception as e:  # 設定読み込み・セッション開始の失敗など
        log_error('Fatal: %s\n%s' % (e, traceback.format_exc()))
        msg = '処理中に予期しないエラーが発生しました。\nしばらく待ってからもう一度お試しください。'
        try:
            if config.is_debug():
                msg += '\n\n[DEBUG] %s: %s' % (type(e).__name__, e)
        except Exception:
            pass
        return resp.error_page(500, 'システムエラーが発生しました', msg, area == 'admin')
    finally:
        if ctx is not None:
            ctx.close()
            ctx.request.cleanup()


def _finalize_headers(result):
    names = {k.lower() for k, _ in result.headers}
    headers = list(result.headers)
    for k, v in resp.SECURITY_HEADERS:
        if k.lower() not in names:
            headers.append((k, v))
    # 画面は個人情報を含むため、ブラウザ・プロキシに保存させない（PHP のセッション既定と同じ）
    if 'cache-control' not in names:
        headers.append(('Cache-Control', 'no-store, no-cache, must-revalidate'))
        headers.append(('Pragma', 'no-cache'))
        headers.append(('Expires', 'Thu, 19 Nov 1981 08:52:00 GMT'))
    return headers


def make_app(area):
    def app(environ, start_response):
        result = handle(environ, area)
        start_response(result.status_line(), _finalize_headers(result))
        body = result.body
        if isinstance(body, (bytes, bytearray)):
            if environ.get('REQUEST_METHOD') == 'HEAD':
                return [b'']
            return [bytes(body)]
        return body
    return app


tenant_app = make_app('tenant')
admin_app = make_app('admin')


def run_cgi(area):
    """CGI として実行する（public/index.cgi から呼ぶ）"""
    from wsgiref.handlers import CGIHandler
    CGIHandler().run(admin_app if area == 'admin' else tenant_app)
