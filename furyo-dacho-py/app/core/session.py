"""
セッション（ログイン状態・CSRFトークン・フラッシュメッセージの保存）

- サーバー側のファイル（storage/sessions/）に JSON で保存する。Cookie にはランダムなIDだけを入れる。
  （JSON は読み込んでもプログラムが実行されない形式のため安全）
- 同じセッションへの同時リクエストは、ファイルロックで1件ずつ処理する（PHP のセッションと同じ）。
- 知らないIDが送られてきても採用しない（新しいIDを発行する＝セッション固定化攻撃の対策）。
- Cookie は HttpOnly・SameSite=Lax・（HTTPS時）Secure。
"""
import errno
import fcntl
import json
import os
import random
import re
import secrets
import time

_ID_RE = re.compile(r'^[0-9a-f]{64}$')

# 最後の操作からこの秒数が過ぎたセッションファイルは削除する（PHP の既定 1440 秒と同じ）
GC_MAX_LIFETIME = 1440
GC_PROBABILITY = 100  # 100回に1回、古いファイルを掃除する


class Session:
    def __init__(self, directory, cookie_name, secure, timeout=0):
        self.directory = directory
        # 自動ログアウトの時間（SESSION_TIMEOUT）より先に掃除で消さない
        self.gc_lifetime = max(GC_MAX_LIFETIME, int(timeout or 0))
        self.cookie_name = cookie_name
        self.secure = secure
        self.id = None
        self.data = {}
        self._fh = None
        self._dirty_cookie = False   # Cookie を送り直す必要があるか
        self._delete_cookie = False
        self._destroyed = False

    # -- 開始・保存 ---------------------------------------------------------
    def start(self, cookie_value):
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        sid = cookie_value if isinstance(cookie_value, str) and _ID_RE.match(cookie_value) else None
        if sid is not None and not os.path.isfile(self._path(sid)):
            sid = None  # 知らないIDは採用しない
        if sid is None:
            sid = self._new_id()
            self._dirty_cookie = True
        self._open(sid)
        if random.randrange(GC_PROBABILITY) == 0:
            self._gc()

    def _new_id(self):
        return secrets.token_hex(32)

    def _path(self, sid):
        return os.path.join(self.directory, 'sess_' + sid)

    def _open(self, sid):
        path = self._path(sid)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        fh = os.fdopen(fd, 'r+', encoding='utf-8')
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            content = fh.read()
            data = json.loads(content) if content.strip() else {}
            if not isinstance(data, dict):
                data = {}
        except ValueError:
            data = {}
        self.id = sid
        self.data = data
        self._fh = fh

    def save(self):
        """内容を書き込んでロックを解除する（リクエストの最後に必ず呼ぶ）"""
        fh = self._fh
        if fh is None:
            return
        self._fh = None
        try:
            if not self._destroyed:
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps(self.data, ensure_ascii=False))
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()

    def _gc(self):
        limit = time.time() - self.gc_lifetime
        try:
            names = os.listdir(self.directory)
        except OSError:
            return
        for name in names:
            if not name.startswith('sess_') or name == 'sess_' + str(self.id):
                continue
            p = os.path.join(self.directory, name)
            try:
                if os.path.getmtime(p) < limit:
                    os.unlink(p)
            except OSError:
                pass

    # -- 操作 ---------------------------------------------------------------
    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.restart_if_destroyed()
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)

    def __contains__(self, key):
        return key in self.data

    def regenerate(self):
        """IDを新しくする（ログイン時。古いファイルは削除）"""
        old_fh, old_id = self._fh, self.id
        data = self.data
        new_id = self._new_id()
        self._fh = None
        self._open(new_id)
        self.data = data
        if old_fh is not None:
            try:
                fcntl.flock(old_fh.fileno(), fcntl.LOCK_UN)
            finally:
                old_fh.close()
            try:
                os.unlink(self._path(old_id))
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
        self._dirty_cookie = True
        self._destroyed = False

    def destroy(self):
        """セッションを破棄する（ログアウト・タイムアウト時）"""
        self.data = {}
        self._destroyed = True
        self._delete_cookie = True
        if self._fh is not None:
            fh = self._fh
            self._fh = None
            try:
                os.unlink(self._path(self.id))
            except OSError:
                pass
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()

    def restart_if_destroyed(self):
        """破棄した後に再び書き込む場合（例: タイムアウト後のフラッシュメッセージ）は新しいIDで開始する"""
        if self._destroyed:
            self._destroyed = False
            self._delete_cookie = False
            self._open(self._new_id())
            self._dirty_cookie = True

    # -- フラッシュメッセージ（次の画面で1回だけ表示） -----------------------------
    def set_flash(self, key, message):
        self.restart_if_destroyed()
        self.data['_flash_' + key] = str(message)

    def pop_flash(self, key):
        return self.data.pop('_flash_' + key, None)

    # -- Cookie -------------------------------------------------------------
    def cookie_header(self):
        """送る Set-Cookie ヘッダの値（不要なら None）"""
        attrs = '; Path=/; HttpOnly; SameSite=Lax' + ('; Secure' if self.secure else '')
        if self._delete_cookie and self._destroyed:
            return '%s=deleted; Expires=Thu, 01 Jan 1970 00:00:01 GMT; Max-Age=0%s' % (self.cookie_name, attrs)
        if self._dirty_cookie and self.id:
            return '%s=%s%s' % (self.cookie_name, self.id, attrs)
        return None
