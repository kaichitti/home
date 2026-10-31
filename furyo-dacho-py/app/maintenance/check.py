"""
環境診断（check.cgi）。動作確認が済んだらサーバーから削除すること。

本番稼働中（config/.env がある）の環境では、診断情報（DBホスト・テナント/ユーザー件数・
サーバーの実パス等）が漏れないよう、システム管理者としてログインしている場合のみ表示する。
未セットアップ（config/.env が無い）の場合は、パスの確認・動作確認のためにそのまま表示する。
"""
import importlib
import os
import sys

from .. import config, paths
from ..core import response as resp
from ..db import Database
from ..helpers import crypto, passwords
from ..util import html_escape
from .common import admin_logged_in, run

COOKIE = 'FURYO_ADMIN_SESS'


def _lines():
    out = []
    out.append('Python Version: %d.%d.%d' % sys.version_info[:3])
    out.append('Python >= 3.6: ' + ('OK' if sys.version_info >= (3, 6) else 'NG'))
    out.append('Python の場所: ' + sys.executable)

    # 必要な部品
    try:
        import pymysql
        out.append('PyMySQL（同梱）: OK (%s)' % getattr(pymysql, 'VERSION_STRING', '?'))
    except Exception as e:
        out.append('PyMySQL（同梱）: MISSING (%s)' % e)
    try:
        crypto.engine()
        out.append('暗号化 AES-256-GCM（OpenSSL）: OK')
    except Exception as e:
        out.append('暗号化 AES-256-GCM（OpenSSL）: MISSING (%s)' % e)
    out.append('パスワード照合 bcrypt: ' + ('OK' if passwords.bcrypt_backend() is not None else 'MISSING'))

    out.append('APP_DIR: ' + paths.APP_DIR)
    env_file = os.path.join(paths.APP_DIR, 'config', '.env')
    out.append('config/.env: ' + ('EXISTS' if os.path.isfile(env_file) else 'MISSING'))

    # DB テスト
    try:
        cfg = config.database()
        out.append('DB_HOST: ' + str(cfg.get('host') or 'N/A'))
        db = Database(cfg)
        try:
            db.connection()
            out.append('DB接続: OK')
            out.append('テナント数: %s' % db.value('SELECT COUNT(*) FROM tenants'))
            out.append('ユーザー数: %s' % db.value('SELECT COUNT(*) FROM users'))
        finally:
            db.close()
    except Exception as e:
        out.append('DB接続エラー: %s' % e)

    # プログラムの読み込みテスト
    for mod in ('app.wsgi', 'app.core.auth', 'app.models.ledger'):
        try:
            importlib.import_module(mod)
            out.append('module %s: OK' % mod)
        except Exception as e:
            out.append('module %s: LOAD_ERROR (%s)' % (mod, e))

    # セッション・アップロード先の書き込みテスト
    cfg = config.get()
    sdir = cfg['session_dir']
    out.append('SESSION_DIR (%s): %s' % (sdir, 'writable' if os.path.isdir(sdir) and os.access(sdir, os.W_OK)
                                          else 'NOT writable'))
    udir = cfg['upload_dir']
    out.append('UPLOAD_DIR (%s): %s' % (udir, 'writable' if os.path.isdir(udir) and os.access(udir, os.W_OK)
                                         else 'NOT writable'))
    return out


def handle(page):
    if config.env_exists():
        logged_in, must_change = admin_logged_in(page)
        if not logged_in or must_change:
            return resp.html('このシステムは稼働中です。診断を表示するには /admin/ からシステム管理者としてログインしてください'
                             '（初期パスワードのままの場合は先に変更が必要です）。'
                             ' なお、この check.cgi は確認後すぐに削除してください。', 403)
    body = ('<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><title>環境診断</title></head><body><pre>'
            + '\n'.join(html_escape(l) for l in _lines()) + '\n</pre>'
            '<b style="color:green">診断完了。このファイルは確認後すぐに削除してください。</b></body></html>')
    return resp.html(body)


def application(environ, start_response):
    return run(handle, environ, start_response, COOKIE)
