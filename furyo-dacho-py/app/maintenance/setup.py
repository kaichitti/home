"""
初回セットアップウィザード（setup.cgi）

  Step 1 環境チェック → Step 2 DB接続テスト → Step 3 DB初期化（database/schema.sql）
  → Step 4 設定ファイル（config/.env）の作成 → Step 5 完了（初回ログイン情報）

!!! セットアップが終わったら setup.cgi を必ずサーバーから削除すること !!!
config/.env が既にある（＝セットアップ済み）場合は、何もせずに停止する
（消し忘れた setup.cgi から暗号化キーを作り直されたり、設定を上書きされたりしないように）。
"""
import os
import re
import secrets
import sys
import time

from .. import paths
from ..core import response as resp
from ..core.response import ResponseDone
from ..db import Database
from ..helpers import crypto, passwords
from ..util import trim
from .common import run, simple_page

SCHEMA_FILE = os.path.join(paths.DATABASE_DIR, 'schema.sql')
ENV_FILE = os.path.join(paths.APP_DIR, 'config', '.env')
COOKIE = 'FURYO_SETUP_SESS'
# database/schema.sql に書かれている初期管理者のパスワード（Admin7777）の bcrypt ハッシュ
SEED_PASSWORD_HASH = '$2y$12$BfMvXseqjMK3KL2Ig4ZYaeA27DCcSKu08wa4cGwwFGxsTg1pw7PJu'
STEP_TITLES = {1: '環境チェック', 2: 'DB接続テスト', 3: 'DB初期化', 4: '設定ファイル生成', 5: '完了'}
_CTRL = re.compile(r'[\x00-\x1F\x7F]')

LOCKED_HTML = (
    '<h1 style="font-size:1.1rem;color:#1e3a5f;margin:0 0 12px;">このシステムはセットアップ済みです</h1>'
    '<p style="font-size:.9rem;line-height:1.8;color:#555;margin:0 0 12px;">'
    '設定ファイル（config/.env）が既に存在するため、セキュリティのためインストーラは'
    '停止しました。セットアップ済みの環境で再実行すると、暗号化キーの再生成により'
    '既存の暗号化データが復号できなくなる恐れがあります。</p>'
    '<p style="font-size:.9rem;line-height:1.8;color:#c0392b;margin:0;">'
    '<strong>この setup.cgi は直ちにサーバーから削除してください。</strong><br>'
    'どうしても再セットアップが必要な場合のみ、先に config/.env を削除してください。'
    '（初回ログイン情報は DEPLOY.md に記載しています）</p>')


def _sget(page, key, default=None):
    v = (page.session.get('setup') or {}).get(key)
    return default if v is None else v


def _sset(page, key, value):
    data = dict(page.session.get('setup') or {})
    data[key] = value
    page.session.set('setup', data)


def _redirect(step):
    raise ResponseDone(resp.redirect('?step=%d' % step))


def _env_checks():
    """Step 1: このサーバーで動かせるか確認する"""
    checks = []
    ok = sys.version_info >= (3, 6)
    checks.append({'label': 'Python バージョン (%d.%d.%d)' % sys.version_info[:3], 'ok': ok,
                   'note': '' if ok else 'Python 3.6 以上が必要です'})
    try:
        import pymysql  # noqa: F401  （lib/ に同梱）
        ok, note = True, ''
    except Exception as e:  # pragma: no cover
        ok, note = False, 'lib/pymysql が読み込めません: %s' % e
    checks.append({'label': 'MySQL 接続ライブラリ（PyMySQL・同梱）', 'ok': ok, 'note': note})
    try:
        crypto.engine()
        ok, note = True, ''
    except Exception as e:
        ok, note = False, '暗号ライブラリ（OpenSSL の libcrypto）が見つかりません: %s' % e
    checks.append({'label': '暗号化（AES-256-GCM）', 'ok': ok, 'note': note})
    # bcrypt が無いサーバーでも PBKDF2-SHA256 で保存して動かせる（初期パスワードは Step 3 で保存し直す）
    checks.append({'label': 'パスワードの保存方式', 'ok': True,
                   'note': '' if passwords.bcrypt_backend() is not None else
                   'bcrypt が使えないため PBKDF2-SHA256 で保存します（新規導入は問題ありません。'
                   'PHP版から移行する場合は、PHP版で設定したパスワードを照合できません）'})

    # storage/uploads/・storage/sessions/（無ければ作り、外部から読めないよう .htaccess も置く）
    for sub, label in (('uploads', 'storage/uploads/ 書き込み権限'), ('sessions', 'storage/sessions/ 書き込み権限'),
                       ('logs', 'storage/logs/ 書き込み権限'), ('tmp', 'storage/tmp/ 書き込み権限')):
        d = os.path.join(paths.APP_DIR, 'storage', sub)
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            ht = os.path.join(d, '.htaccess')
            if not os.path.isfile(ht):
                with open(ht, 'w', encoding='utf-8') as f:
                    f.write('Require all denied\n')
        except OSError:
            pass
        ok = os.path.isdir(d) and os.access(d, os.W_OK)
        checks.append({'label': label, 'ok': ok, 'note': '' if ok else 'ディレクトリが存在しないか、書き込み不可です'})
    d = os.path.join(paths.APP_DIR, 'config')
    ok = os.path.isdir(d) and os.access(d, os.W_OK)
    checks.append({'label': 'config/ 書き込み権限', 'ok': ok,
                   'note': '' if ok else 'config/ ディレクトリへの書き込みが必要です'})
    return checks


def _connect(page, host, name, user, password):
    cfg = {'host': host, 'port': 3306, 'socket': '', 'dbname': name, 'username': user, 'password': password,
           'charset': 'utf8mb4'}
    db = Database(cfg)
    db.connection()
    return db


def _handle_post(page, step, errors, success):
    req = page.request
    token = req.raw_post('_csrf_token')
    if token == '' or not secrets.compare_digest(str(page.session.get('_csrf_token') or ''), token):
        errors.append('セッションの有効期限が切れたか、不正なリクエストです。ページを再読み込みしてもう一度お試しください。')
        return

    if step == 2 and req.post('test_connection') is not None:
        host, name, user = trim(req.post_str('db_host')), trim(req.post_str('db_name')), trim(req.post_str('db_user'))
        password = req.raw_post('db_pass')
        if host == '' or name == '' or user == '':
            errors.append('ホスト・データベース名・ユーザー名は必須です。')
        else:
            try:
                db = _connect(page, host, name, user, password)
                db.value('SELECT 1')
                db.close()
                for k, v in (('db_host', host), ('db_name', name), ('db_user', user), ('db_pass', password),
                             ('db_ok', True)):
                    _sset(page, k, v)
                success.append('データベース接続に成功しました。')
            except Exception as e:
                errors.append('DB接続エラー: %s' % e)
                _sset(page, 'db_ok', False)

    if step == 2 and req.post('next_to_step3') is not None:
        if not _sget(page, 'db_ok'):
            errors.append('先にDB接続テストを成功させてください。')
        else:
            _redirect(3)

    if step == 3 and req.post('run_init') is not None:
        if not _sget(page, 'db_ok'):
            errors.append('DB設定が未確認です。Step 2からやり直してください。')
        elif not os.path.isfile(SCHEMA_FILE):
            errors.append('schema.sql が見つかりません: ' + SCHEMA_FILE)
        else:
            try:
                db = _connect(page, _sget(page, 'db_host'), _sget(page, 'db_name'), _sget(page, 'db_user'),
                              _sget(page, 'db_pass', ''))
                with open(SCHEMA_FILE, encoding='utf-8') as f:
                    sql = f.read()
                executed = 0
                # セミコロンで文に分け、注釈だけの文は飛ばして順に実行する（PHP版と同じ）
                for statement in (s.strip() for s in sql.split(';')):
                    if statement == '' or re.sub(r'--[^\n]*\n?', '', statement).strip() == '':
                        continue
                    db.execute_raw(statement)
                    executed += 1
                if passwords.bcrypt_backend() is None:
                    # bcrypt を照合できないサーバーでは、初期管理者のパスワード（初期値）を PBKDF2 で保存し直す
                    new_hash = passwords.hash_password(passwords.DEFAULT_PASSWORD)
                    for table in ('system_admins', 'users'):
                        db.execute('UPDATE `%s` SET `password_hash` = ? WHERE `password_hash` = ?' % table,
                                   (new_hash, SEED_PASSWORD_HASH))
                db.close()
                _sset(page, 'encryption_key', crypto.generate_key())
                _sset(page, 'db_init_ok', True)
                success.append('DBの初期化が完了しました（%d ステートメントを実行）。' % executed)
                success.append('暗号化キーを自動生成しました。')
            except Exception as e:
                errors.append('DB初期化エラー: %s' % e)
                _sset(page, 'db_init_ok', False)

    if step == 3 and req.post('next_to_step4') is not None:
        if not _sget(page, 'db_init_ok'):
            errors.append('先にDB初期化を実行してください。')
        else:
            _redirect(4)

    if step == 4 and req.post('generate_env') is not None:
        _generate_env(page, errors, success)

    if step == 4 and req.post('next_to_step5') is not None:
        if not _sget(page, 'env_ok'):
            errors.append('先に設定ファイルを生成してください。')
        else:
            _redirect(5)


def _generate_env(page, errors, success):
    req = page.request
    if not _sget(page, 'db_init_ok'):
        errors.append('DB初期化が完了していません。')
        return
    app_url = trim(req.raw_post('app_url')).rstrip('/')
    app_env = trim(req.raw_post('app_env')) or 'production'
    app_debug = 'true' if req.post('app_debug') is not None else 'false'
    upload_dir = trim(req.raw_post('upload_dir'))
    if app_url == '':
        errors.append('アプリケーションURLは必須です。')
        return
    if _CTRL.search(app_url) or not re.match(r'(?i)https?://[^\s/?#]+[^\s]*$', app_url):
        # 改行などを含む値は .env への設定行の注入につながるため受け付けない
        errors.append('アプリケーションURLは http:// または https:// から始まる正しいURLで入力してください。')
        return
    if upload_dir == '':
        errors.append('アップロードディレクトリは必須です。')
        return
    if _CTRL.search(upload_dir) or not os.path.isabs(upload_dir):
        errors.append('アップロードディレクトリに使用できない文字が含まれています。' if _CTRL.search(upload_dir)
                      else 'アップロードディレクトリは / から始まる絶対パスで入力してください。')
        return
    try:
        os.makedirs(upload_dir, mode=0o700, exist_ok=True)
    except OSError:
        errors.append('アップロードディレクトリを作成できませんでした。パスと書き込み権限を確認してください: ' + upload_dir)
        return
    if not os.access(upload_dir, os.W_OK):
        errors.append('アップロードディレクトリに書き込めません。権限を確認してください: ' + upload_dir)
        return

    def safe(v):
        # .env は1行1設定のため、改行・制御文字を取り除く（任意の設定行を注入させない）
        return _CTRL.sub('', str(v or ''))

    app_env = app_env if app_env in ('production', 'development') else 'production'
    content = '\n'.join([
        '# アプリケーション設定',
        'APP_ENV=' + app_env,
        'APP_URL=' + safe(app_url),
        'APP_DEBUG=' + app_debug,
        '',
        '# 暗号化キー（自動生成 - 絶対に外部に漏洩させないこと）',
        'ENCRYPTION_KEY=' + safe(_sget(page, 'encryption_key', '')),
        '',
        '# データベース設定',
        'DB_HOST=' + safe(_sget(page, 'db_host')),
        'DB_NAME=' + safe(_sget(page, 'db_name')),
        'DB_USER=' + safe(_sget(page, 'db_user')),
        'DB_PASS=' + safe(_sget(page, 'db_pass', '')),
        '',
        '# アップロードディレクトリ（絶対パス・webroot外）',
        'UPLOAD_DIR=' + safe(upload_dir),
    ])
    try:
        os.makedirs(os.path.dirname(ENV_FILE), mode=0o755, exist_ok=True)
        # 既にある場合は上書きしない（同時に2回送信された場合など）
        fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
    except OSError:
        errors.append('config/.env の書き込みに失敗しました。config/ ディレクトリの書き込み権限を確認してください。')
        return
    _sset(page, 'env_ok', True)
    _sset(page, 'app_url', app_url)
    _sset(page, 'app_env', app_env)
    _sset(page, 'app_debug', app_debug == 'true')
    _sset(page, 'upload_dir', upload_dir)
    # このセッションでセットアップを完了した印（完了画面の表示だけを許可するため）
    page.session.regenerate()
    _sset(page, 'install_completed', True)
    _sset(page, 'install_completed_at', int(time.time()))
    # .env へ書き込んだ機密情報はセッションに残さない
    data = dict(page.session.get('setup') or {})
    data.pop('db_pass', None)
    data.pop('encryption_key', None)
    page.session.set('setup', data)
    success.append('config/.env を生成しました。')
    success.append('ファイルパーミッションを 0600 に設定しました。')


def handle(page):
    req = page.request
    try:
        step = int(req.get_str('step', '1') or 1)
    except ValueError:
        step = 1
    if os.path.isfile(ENV_FILE):
        completed_at = int(_sget(page, 'install_completed_at', 0) or 0)
        just = _sget(page, 'install_completed') is True and completed_at > 0 and time.time() - completed_at < 1800
        if just and req.is_post() and step == 4 and req.post('next_to_step5') is not None:
            _redirect(5)
        if not (just and not req.is_post() and step == 5):
            return simple_page(403, 'セットアップ済み', LOCKED_HTML)

    if not page.session.get('_csrf_token'):
        page.session.set('_csrf_token', secrets.token_hex(32))
    errors, success = [], []
    if req.is_post():
        _handle_post(page, step, errors, success)

    checks = _env_checks() if step == 1 else []
    return page.render('maintenance/setup', {
        'step': step,
        'stepTitles': STEP_TITLES,
        'errors': errors,
        'success': success,
        'envChecks': checks,
        'allOk': all(c['ok'] for c in checks),
        's': dict(page.session.get('setup') or {}),
        'csrf_token': page.session.get('_csrf_token'),
        'default_upload_dir': os.path.join(paths.APP_DIR, 'storage', 'uploads'),
    })


def application(environ, start_response):
    return run(handle, environ, start_response, COOKIE)
