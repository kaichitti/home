"""
ログイン試行制限（総当たり対策 + アカウントロックによる締め出し対策）

login_attempts テーブルに「失敗」と「成功」を記録し、次の3つで判定する（PHP版と同じ）。
 1. IP単位      : 同じIPからの失敗が15分間に30回を超えたら、そのIPを一時拒否
 2. アカウント×IP : 同じIPから同じアカウントへの失敗が30分間に5回を超えたら、その組合せを拒否
 3. アカウント単位 : 失敗が一定数に達したらロック（判定は呼び出し側）。ただし過去にログイン成功した
                   「信頼済みIP」からはロック中でも照合する（第三者による故意の締め出しを防ぐ）
同時に大量のリクエストを送られても上限を超えないよう、照合の「前」に失敗行を予約する。
アカウントの識別子は SHA-256 で保存し、メールアドレス等の平文は残さない。
"""
import hashlib
import random
import sys

from ..db import DBError, ER_NO_SUCH_TABLE
from . import client_ip
from ..util import trim

IP_MAX_FAILURES = 30
IP_WINDOW_MIN = 15
PAIR_MAX_FAILURES = 5
PAIR_WINDOW_MIN = 30
ACCOUNT_MAX_FAILURES = 5
ACCOUNT_WINDOW_MIN = 30
TRUSTED_IP_DAYS = 30

CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS `login_attempts` (
            `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            `ip`           VARCHAR(45)     NOT NULL COMMENT '試行元IPアドレス',
            `account_hash` CHAR(64)        NOT NULL COMMENT 'アカウント識別子のSHA-256（平文は保存しない）',
            `success`      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '0=失敗, 1=成功（信頼済みIPの判定に使用）, 2=照合せず拒否（ロック中・組合せ単位の制限。IP単位の制限のみに数える）',
            `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`),
            INDEX `idx_login_attempts_ip`      (`ip`, `success`, `created_at`),
            INDEX `idx_login_attempts_account` (`account_hash`, `ip`, `success`, `created_at`),
            INDEX `idx_login_attempts_created` (`created_at`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
          COMMENT='ログイン試行履歴（ブルートフォース・アカウントロックDoS対策）'"""


def account_key(scope, *parts):
    """アカウント識別キー（例: tenant|uid:12, admin|id:1）"""
    return scope + '|' + '|'.join(trim(p).lower() for p in parts)  # PHP: mb_strtolower(trim($p))


def _hash(key):
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def _log(msg):
    sys.stderr.write('[furyo-dacho] %s\n' % msg)


class LoginThrottle:
    def __init__(self, db):
        self.db = db

    def _with_table(self, fn):
        try:
            return fn()
        except DBError as e:
            if e.code == ER_NO_SUCH_TABLE:
                self.db.execute(CREATE_TABLE_SQL)
                return fn()
            raise

    def reserve(self, key, ip):
        """照合前に試行を予約する。拒否なら None、記録先が使えない場合は 0（制限なしで続行）"""
        def run():
            b = client_ip.bucket(ip)
            h = _hash(key)
            rid = self.db.insert("INSERT INTO `login_attempts` (`ip`, `account_hash`, `success`) VALUES (?, ?, 0)",
                                 (b, h))
            cnt = int(self.db.value(
                """SELECT COUNT(*) FROM `login_attempts`
                     WHERE `ip` = ? AND `success` IN (0, 2)
                       AND `created_at` >= DATE_SUB(NOW(), INTERVAL ? MINUTE)""", (b, IP_WINDOW_MIN)) or 0)
            if cnt > IP_MAX_FAILURES:
                self.release(rid)  # IP単位で拒否した試行は記録しない（拒否中の再試行で期間を延ばさない）
                self._maybe_purge()
                return None
            cnt = int(self.db.value(
                """SELECT COUNT(*) FROM `login_attempts`
                     WHERE `account_hash` = ? AND `ip` = ? AND `success` = 0
                       AND `created_at` >= DATE_SUB(NOW(), INTERVAL ? MINUTE)""", (h, b, PAIR_WINDOW_MIN)) or 0)
            if cnt > PAIR_MAX_FAILURES:
                self.mark_refused(rid)
                self._maybe_purge()
                return None
            self._maybe_purge()
            return rid
        try:
            return self._with_table(run)
        except Exception as e:
            _log('LoginThrottle.reserve failed: %s' % e)
            return 0

    def mark_refused(self, rid):
        """照合せずに拒否した試行（success=2）として記録し直す"""
        if not rid or rid <= 0:
            return
        try:
            self.db.execute("UPDATE `login_attempts` SET `success` = 2 WHERE `id` = ? AND `success` = 0", (rid,))
        except Exception:
            pass

    def release(self, rid):
        if not rid or rid <= 0:
            return
        try:
            self.db.execute("DELETE FROM `login_attempts` WHERE `id` = ?", (rid,))
        except Exception:
            pass

    def is_account_locked(self, key, exclude_id=0):
        """アカウント単位の失敗数がロック基準に達しているか（システム管理者用）"""
        def run():
            cnt = int(self.db.value(
                """SELECT COUNT(*) FROM `login_attempts`
                     WHERE `account_hash` = ? AND `success` = 0 AND `id` <> ?
                       AND `created_at` >= DATE_SUB(NOW(), INTERVAL ? MINUTE)""",
                (_hash(key), int(exclude_id or 0), ACCOUNT_WINDOW_MIN)) or 0)
            return cnt >= ACCOUNT_MAX_FAILURES
        try:
            return self._with_table(run)
        except Exception:
            return False

    def is_trusted_ip(self, key, ip):
        """このIPが、このアカウントで過去にログイン成功したことのある「信頼済みIP」か"""
        def run():
            row = self.db.value(
                """SELECT 1 FROM `login_attempts`
                     WHERE `account_hash` = ? AND `ip` = ? AND `success` = 1
                       AND `created_at` >= DATE_SUB(NOW(), INTERVAL ? DAY)
                     LIMIT 1""", (_hash(key), client_ip.bucket(ip), TRUSTED_IP_DAYS))
            return row is not None
        try:
            return self._with_table(run)
        except Exception:
            return False

    def clear_failures(self, key):
        """失敗記録を消す（管理者によるロック解除・パスワード再設定時。信頼済みIPは残す）"""
        try:
            self._with_table(lambda: self.db.execute(
                "DELETE FROM `login_attempts` WHERE `account_hash` = ? AND `success` <> 1", (_hash(key),)))
        except Exception as e:
            _log('login attempts clear failed: %s' % e)

    def record_success(self, key, ip):
        """ログイン成功を記録（この組合せの失敗記録を消し、信頼済みIPとして1件だけ残す）"""
        def run():
            h, b = _hash(key), client_ip.bucket(ip)
            self.db.execute("DELETE FROM `login_attempts` WHERE `account_hash` = ? AND `ip` = ?", (h, b))
            self.db.execute("INSERT INTO `login_attempts` (`ip`, `account_hash`, `success`) VALUES (?, ?, 1)", (b, h))
        try:
            self._with_table(run)
        except Exception:
            pass

    def _maybe_purge(self):
        """古い記録を間引く（およそ20回に1回）"""
        if random.randint(1, 20) != 1:
            return
        try:
            self.db.execute(
                """DELETE FROM `login_attempts`
                 WHERE (`success` IN (0, 2) AND `created_at` < DATE_SUB(NOW(), INTERVAL 1 DAY))
                    OR (`success` = 1 AND `created_at` < DATE_SUB(NOW(), INTERVAL ? DAY))""", (TRUSTED_IP_DAYS,))
        except Exception:
            pass
