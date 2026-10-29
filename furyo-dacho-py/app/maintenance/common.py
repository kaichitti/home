"""保守用画面の共通部分（リクエスト・セッション・画面の描画・応答の送信）"""
import os
import time

from .. import config, paths
from ..core import response as resp
from ..core import template
from ..core.request import Request
from ..core.response import ResponseDone
from ..core.session import Session
from ..logger import log_error
from ..util import html_escape, is_empty


class Page:
    """1回のリクエスト（cookie_name のセッションを使う）"""

    def __init__(self, environ, cookie_name):
        self.environ = environ
        self.cfg = config.get()
        self.request = Request(environ, self.cfg, os.path.join(paths.APP_DIR, 'storage', 'tmp'))
        self.session = Session(self.cfg['session_dir'], cookie_name, self.request.is_https())
        self.session.start(self.request.cookies.get(cookie_name))

    def render(self, view, data, status=200):
        r = template.Renderer({'h': html_escape, 'raw': template.raw, 'has': lambda v: not is_empty(v)})
        return resp.html(r.render(view, data), status)

    def finish(self, result, start_response):
        try:
            self.session.save()
        except Exception as e:
            log_error('maintenance session save failed: %s' % e)
        cookie = self.session.cookie_header()
        if cookie:
            result.add_header('Set-Cookie', cookie)
        self.request.cleanup()
        headers = list(result.headers)
        names = {k.lower() for k, _ in headers}
        for k, v in resp.SECURITY_HEADERS:
            if k.lower() not in names:
                headers.append((k, v))
        headers.append(('Cache-Control', 'no-store, no-cache, must-revalidate'))
        start_response(result.status_line(), headers)
        return [result.body]


def simple_page(status, title, body_html):
    """短いお知らせの画面"""
    page = ('<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>%s</title></head><body style="font-family:sans-serif;'
            'background:#f4f5f7;color:#333;display:flex;min-height:100vh;align-items:center;'
            'justify-content:center;padding:24px;">'
            '<div style="background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);'
            'max-width:520px;padding:28px 24px;">%s</div></body></html>') % (html_escape(title), body_html)
    return resp.html(page, status)


def run(app_func, environ, start_response, cookie_name):
    """保守用画面を実行する（予期しないエラーは記録してエラー画面）"""
    page = None
    try:
        page = Page(environ, cookie_name)
        try:
            result = app_func(page)
        except ResponseDone as done:
            result = done.response
        return page.finish(result, start_response)
    except Exception as e:
        import traceback
        log_error('maintenance error: %s\n%s' % (e, traceback.format_exc()))
        msg = '処理中に予期しないエラーが発生しました。'
        try:
            if config.is_debug():
                msg += '\n\n[DEBUG] %s: %s' % (type(e).__name__, e)
        except Exception:
            pass
        r = resp.error_page(500, 'システムエラーが発生しました', msg)
        start_response(r.status_line(), r.headers)
        return [r.body]


def admin_logged_in(page):
    """システム管理者としてログインしているか（初期パスワードのままの場合は (True, True)）"""
    s = page.session
    last = s.get('_last_activity')
    try:
        valid = last is not None and int(time.time()) - int(last) <= page.cfg['session_timeout']
    except (TypeError, ValueError):
        valid = False
    logged_in = valid and s.get('admin_id') is not None
    if logged_in:
        s.set('_last_activity', int(time.time()))
    return logged_in, logged_in and bool(s.get('admin_must_change_password', False))
