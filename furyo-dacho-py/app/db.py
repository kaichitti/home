"""
データベース（MySQL / MariaDB）への接続と実行

- SQL はPHP版と同じく「?」を値の置き場所（プレースホルダ）にして書く。
  値はすべてドライバ（PyMySQL）がエスケープして埋め込むため、SQL に値を直接つなげない。
- 取得結果は {列名: 値} の辞書。日付・日時は 'YYYY-MM-DD HH:MM:SS' の文字列、
  DECIMAL(12,0) の金額は整数で返す（PHP版と同じ扱いにするため）。
- 接続時にタイムゾーンを日本時間（+09:00）にそろえる。
"""
import os

import pymysql
from pymysql.constants import FIELD_TYPE
from pymysql.converters import conversions as _base_conversions
from pymysql.cursors import DictCursor

from . import config


class DBError(Exception):
    """SQL の実行エラー。code は MySQL のエラー番号（例: 1062 = 一意制約違反）"""

    def __init__(self, code, message):
        super().__init__('SQL error %s: %s' % (code, message))
        self.code = code
        self.message = message


# よく使うエラー番号
ER_DUP_ENTRY = 1062        # 一意制約違反
ER_NO_SUCH_TABLE = 1146    # テーブルが無い
ER_BAD_FIELD = 1054        # 列が無い
ER_DUP_FIELDNAME = 1060    # 列が既にある
ER_DUP_KEYNAME = 1061      # 索引が既にある
ER_ROW_IS_REFERENCED = 1451  # 外部キーで参照されている
ER_LOCK_WAIT_TIMEOUT = 1205
ER_LOCK_DEADLOCK = 1213


def _decimal(value):
    return int(value) if '.' not in value else float(value)


_CONV = dict(_base_conversions)
for _t in (FIELD_TYPE.DATETIME, FIELD_TYPE.TIMESTAMP, FIELD_TYPE.DATE, FIELD_TYPE.TIME):
    _CONV[_t] = str
_CONV[FIELD_TYPE.DECIMAL] = _decimal
_CONV[FIELD_TYPE.NEWDECIMAL] = _decimal

_SOCKET_CANDIDATES = (
    '/var/lib/mysql/mysql.sock',
    '/var/run/mysqld/mysqld.sock',
    '/run/mysqld/mysqld.sock',
    '/tmp/mysql.sock',
)

_SQL_CACHE = {}


def to_pyformat(sql):
    """「?」を PyMySQL の「%s」に置き換える（文字列リテラル内の ? はそのまま。% は %% にする）"""
    cached = _SQL_CACHE.get(sql)
    if cached is not None:
        return cached
    out = []
    quote = None
    count = 0
    for ch in sql:
        if quote:
            if ch == quote:
                quote = None
            out.append('%%' if ch == '%' else ch)
        elif ch in ("'", '"', '`'):
            quote = ch
            out.append(ch)
        elif ch == '?':
            out.append('%s')
            count += 1
        elif ch == '%':
            out.append('%%')
        else:
            out.append(ch)
    result = (''.join(out), count)
    _SQL_CACHE[sql] = result
    return result


class Database:
    """1リクエストにつき1接続（最初に使うときに接続する）"""

    def __init__(self, cfg=None):
        self._cfg = cfg
        self._conn = None
        self.in_transaction = False

    # -- 接続 ---------------------------------------------------------------
    def connection(self):
        if self._conn is None:
            cfg = self._cfg or config.database()
            kwargs = {
                'user': cfg['username'],
                'password': cfg['password'],
                'database': cfg['dbname'],
                'charset': cfg.get('charset') or 'utf8mb4',
                'autocommit': True,
                'cursorclass': DictCursor,
                'conv': _CONV,
                'connect_timeout': 10,
            }
            socket = cfg.get('socket') or ''
            if not socket and cfg['host'] == 'localhost':
                # PHP（libmysqlclient）と同じく、localhost はソケットファイルで接続する
                socket = next((p for p in _SOCKET_CANDIDATES if os.path.exists(p)), '')
            if socket:
                kwargs['unix_socket'] = socket
            else:
                kwargs['host'] = '127.0.0.1' if cfg['host'] == 'localhost' else cfg['host']
                kwargs['port'] = int(cfg.get('port') or 3306)
            try:
                self._conn = pymysql.connect(**kwargs)
            except pymysql.err.MySQLError as e:
                raise RuntimeError('DB connection failed. host=%s db=%s user=%s / %s'
                                   % (cfg['host'], cfg['dbname'], cfg['username'], e)) from None
            try:
                # 日時の基準を日本時間にそろえる（NOW() や created_at の既定値がずれないように）
                with self._conn.cursor() as cur:
                    cur.execute("SET time_zone = '+09:00'")
            except pymysql.err.MySQLError:
                pass
        return self._conn

    def close(self):
        if self._conn is not None:
            try:
                if self.in_transaction:
                    self._conn.rollback()
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self.in_transaction = False

    # -- 実行 ---------------------------------------------------------------
    def _run(self, sql, params):
        q, count = to_pyformat(sql)
        params = tuple(params or ())
        if count != len(params):
            raise ValueError('placeholder count mismatch (%d != %d): %s' % (count, len(params), sql[:200]))
        cur = self.connection().cursor()
        try:
            cur.execute(q, params)
        except pymysql.err.MySQLError as e:
            cur.close()
            code = e.args[0] if e.args and isinstance(e.args[0], int) else 0
            msg = e.args[1] if len(e.args) > 1 else str(e)
            raise DBError(code, msg) from None
        return cur

    def query(self, sql, params=()):
        """全行を辞書のリストで返す"""
        cur = self._run(sql, params)
        try:
            return list(cur.fetchall())
        finally:
            cur.close()

    def query_one(self, sql, params=()):
        """最初の1行（無ければ None）"""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def value(self, sql, params=()):
        """最初の行の最初の列（無ければ None）"""
        row = self.query_one(sql, params)
        if row is None:
            return None
        return next(iter(row.values()))

    def column(self, sql, params=()):
        """各行の最初の列のリスト"""
        return [next(iter(r.values())) for r in self.query(sql, params)]

    def execute(self, sql, params=()):
        """INSERT/UPDATE/DELETE/DDL を実行し、変更した行数を返す"""
        cur = self._run(sql, params)
        try:
            return cur.rowcount
        finally:
            cur.close()

    def execute_raw(self, sql):
        """値を埋め込まない SQL（schema.sql の各文など）をそのまま実行する"""
        cur = self.connection().cursor()
        try:
            cur.execute(sql)
            return cur.rowcount
        except pymysql.err.MySQLError as e:
            code = e.args[0] if e.args and isinstance(e.args[0], int) else 0
            msg = e.args[1] if len(e.args) > 1 else str(e)
            raise DBError(code, msg) from None
        finally:
            cur.close()

    def insert(self, sql, params=()):
        """INSERT を実行し、追加した行の ID を返す"""
        cur = self._run(sql, params)
        try:
            return int(cur.lastrowid or 0)
        finally:
            cur.close()

    # -- トランザクション ------------------------------------------------------
    def begin(self):
        self.connection().begin()
        self.in_transaction = True

    def commit(self):
        try:
            self.connection().commit()
        finally:
            self.in_transaction = False

    def rollback(self):
        try:
            if self._conn is not None:
                self._conn.rollback()
        finally:
            self.in_transaction = False
