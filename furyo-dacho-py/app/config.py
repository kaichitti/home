"""
設定の読み込み

config/.env（1行1設定・「キー=値」）を読み、環境変数より優先して使う。
機密情報（DBパスワード・暗号化キー）は .env にだけ書く。
"""
import os

from . import paths

_ENV = None
_TRIM = ' \t\n\r\0\x0b'  # PHP の trim() が取り除く文字


def load_env(path):
    """PHP版 config/env.php と同じ規則で .env を読む（# で始まる行は注釈）"""
    values = {}
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            lines = f.read().splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip(_TRIM)
        if line == '' or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[7:].strip(_TRIM)
        key, value = line.split('=', 1)
        key, value = key.strip(_TRIM), value.strip(_TRIM)
        if key == '':
            continue
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        values[key] = value
    return values


def env_values():
    global _ENV
    if _ENV is None:
        _ENV = load_env(os.path.join(paths.APP_DIR, 'config', '.env'))
    return _ENV


def env(key, default=None):
    """設定値（.env → 環境変数 → REDIRECT_付きの環境変数 の順。空文字は未設定扱い）"""
    v = env_values().get(key)
    if v not in (None, ''):
        return v
    v = os.environ.get(key)
    if v not in (None, ''):
        return v
    v = os.environ.get('REDIRECT_' + key)
    if v not in (None, ''):
        return v
    return default


def env_exists():
    return os.path.isfile(os.path.join(paths.APP_DIR, 'config', '.env'))


def _int_env(key, default):
    try:
        return int(env(key, str(default)))
    except (TypeError, ValueError):
        return default


def get():
    """アプリ全体の設定（PHP版 config/config.php と同じ項目）"""
    storage = os.path.join(paths.APP_DIR, 'storage')
    return {
        'app_name': '古物台帳管理システム',
        'app_url': env('APP_URL', 'http://localhost'),
        'app_env': env('APP_ENV', 'production'),
        'debug': env('APP_DEBUG', 'false') == 'true',
        'session_timeout': _int_env('SESSION_TIMEOUT', 900),  # 15分
        'session_name': 'FURYO_SESS',
        'admin_session_name': 'FURYO_ADMIN_SESS',
        'upload_dir': env('UPLOAD_DIR', os.path.join(storage, 'uploads')),
        'session_dir': env('SESSION_DIR', os.path.join(storage, 'sessions')),
        'log_dir': env('LOG_DIR', os.path.join(storage, 'logs')),
        'max_file_size': _int_env('MAX_FILE_SIZE', 52428800),  # 50MB（本人確認書類・受付表）
        'max_post_size': _int_env('MAX_POST_SIZE', 134217728),  # 128MB（1回の送信全体）
        'allowed_mime_types': ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf'],
        'encryption_key': env('ENCRYPTION_KEY', ''),
        'timezone': 'Asia/Tokyo',
    }


def is_debug():
    c = get()
    return c['app_env'] == 'development' or c['debug']


class ConfigError(RuntimeError):
    pass


def database():
    """DB接続設定（PHP版 config/database.php と同じ確認を行う）"""
    host = env('DB_HOST')
    name = env('DB_NAME')
    user = env('DB_USER')
    password = env('DB_PASS', '')
    missing = [k for k, v in (('DB_HOST', host), ('DB_NAME', name), ('DB_USER', user)) if not v]
    if user == 'root' and env('ALLOW_ROOT_DB', 'false') != 'true':
        raise ConfigError('DB_USER is set to root. Set the hosting MySQL user in config/.env, '
                          'or set ALLOW_ROOT_DB=true only for local development.')
    if missing:
        raise ConfigError('Database config is incomplete. Missing: ' + ', '.join(missing)
                          + '. Create config/.env with DB_HOST, DB_NAME, DB_USER, and DB_PASS.')
    return {
        'host': host,
        'port': _int_env('DB_PORT', 3306),
        'socket': env('DB_SOCKET', ''),
        'dbname': name,
        'username': user,
        'password': password or '',
        'charset': env('DB_CHARSET', 'utf8mb4'),
    }
