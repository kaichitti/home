"""エラーの記録"""
import datetime
import os
import sys

from . import config


def log_error(message):
    """エラーをサーバーのエラーログと storage/logs/error.log に記録する"""
    line = '[%s] [furyo-dacho] %s\n' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), message)
    try:
        sys.stderr.write(line)
    except Exception:
        pass
    try:
        log_dir = config.get()['log_dir']
        os.makedirs(log_dir, mode=0o700, exist_ok=True)
        path = os.path.join(log_dir, 'error.log')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass
