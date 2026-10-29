"""
DBマイグレーション（migrate.cgi）

アプリを新しいバージョンに更新したとき、DB に足りないテーブル・列を見つけて追加する。
何度実行しても安全（適用済みの項目は飛ばす）。システム管理者としてログインしている場合のみ実行できる。

!!! 完了したら migrate.cgi を必ずサーバーから削除すること !!!
"""
import secrets

from .. import config
from ..db import Database
from ..models import ledger_schema, pos_schema
from ..models.sale import MEMBER_CODE_COLUMN_DDL
from .common import admin_logged_in, run, simple_page

COOKIE = 'FURYO_ADMIN_SESS'


def _count(db, sql, params=()):
    return int(db.value(sql, params) or 0)


def _has_column(db, name, table, column):
    return _count(db, """SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND COLUMN_NAME = ?""", (name, table, column)) > 0


def _has_table(db, name, table):
    return _count(db, """SELECT COUNT(*) FROM information_schema.TABLES
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?""", (name, table)) > 0


def _has_index(db, name, table, index):
    return _count(db, """SELECT COUNT(*) FROM information_schema.STATISTICS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND INDEX_NAME = ?""", (name, table, index)) > 0


def migrations(db, name):
    """マイグレーションの一覧: (説明, 適用が必要か調べる関数, 適用する関数)"""
    m = []

    def item_category_type():
        t = db.value("""SELECT DATA_TYPE FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = 'item_category'""", (name,))
        return t is not None and str(t).lower() != 'varchar'
    m.append(('ledgers.item_category を ENUM から VARCHAR(100) に変更（その他・独自区分対応）', item_category_type,
              lambda: db.execute_raw("""ALTER TABLE `ledgers`
                     MODIFY `item_category` VARCHAR(100) NOT NULL
                     COMMENT '古物の区分（法定13区分コード / other / テナント独自区分名）'""")))

    m.append(('ledgers.item_category_note カラムを追加（その他の自由記述）',
              lambda: not _has_column(db, name, 'ledgers', 'item_category_note'),
              lambda: db.execute_raw("""ALTER TABLE `ledgers`
                     ADD COLUMN `item_category_note` VARCHAR(255) NULL DEFAULT NULL
                     COMMENT 'item_category=other の場合の自由記述'
                     AFTER `item_category`""")))

    from ..models.item_category import CREATE_TABLE_SQL as ITEM_CATEGORIES_SQL
    m.append(('item_categories テーブルを作成（テナント独自の古物区分）',
              lambda: not _has_table(db, name, 'item_categories'),
              lambda: db.execute_raw(ITEM_CATEGORIES_SQL)))

    ledger_cols = [
        ('serial_number', "ADD COLUMN `serial_number` VARCHAR(100) NULL DEFAULT NULL COMMENT 'シリアル番号・製造番号（任意）' AFTER `item_name`"),
        ('member_code', "ADD COLUMN `member_code` VARCHAR(50) NULL DEFAULT NULL COMMENT '会員番号（任意）' AFTER `transaction_amount`"),
        ('counterpart_type', "ADD COLUMN `counterpart_type` ENUM('individual','corporate') NOT NULL DEFAULT 'individual' COMMENT '相手方区分' AFTER `member_code`"),
        ('counterpart_contact_name', "ADD COLUMN `counterpart_contact_name` VARCHAR(255) NULL DEFAULT NULL COMMENT '担当者名（法人の場合は必須）' AFTER `counterpart_phone`"),
        ('counterpart_account', "ADD COLUMN `counterpart_account` VARCHAR(255) NULL DEFAULT NULL COMMENT '取引アカウント（任意）' AFTER `counterpart_contact_name`"),
        ('counterpart_note', "ADD COLUMN `counterpart_note` TEXT NULL DEFAULT NULL COMMENT '相手方に関する備考（任意）' AFTER `counterpart_account`"),
    ]

    def ledger_cols_needed():
        return _count(db, """SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers'
                       AND COLUMN_NAME IN ('member_code','serial_number','counterpart_type','counterpart_contact_name','counterpart_account','counterpart_note')""",
                      (name,)) < 6

    def ledger_cols_apply():
        for col, ddl in ledger_cols:
            if not _has_column(db, name, 'ledgers', col):
                db.execute_raw("ALTER TABLE `ledgers` " + ddl)
        # シリアル番号検索用の索引
        if not _has_index(db, name, 'ledgers', 'idx_ledgers_serial_number'):
            db.execute_raw("ALTER TABLE `ledgers` ADD INDEX `idx_ledgers_serial_number` (`serial_number`)")
    m.append(('ledgers に会員番号・シリアル番号・相手方区分等のカラムを追加（2026-07-09）', ledger_cols_needed, ledger_cols_apply))

    m.append(('ledgers.id_document_type を任意（NULL許可）に変更（マイナンバー等の記載省略対応）',
              lambda: str(db.value("""SELECT IS_NULLABLE FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledgers' AND COLUMN_NAME = 'id_document_type'""",
                                   (name,)) or '').upper() == 'NO',
              lambda: db.execute_raw("""ALTER TABLE `ledgers`
                     MODIFY `id_document_type` ENUM('driver_license','my_number','passport','health_insurance','residence_card','residence_status','special_permanent','other')
                     NULL DEFAULT NULL COMMENT '本人確認書類種別（未登録可・未登録時はアラート表示）'""")))

    from ..models.member import CREATE_TABLE_SQL as MEMBERS_SQL
    m.append(('members テーブルを作成（会員番号による相手方情報の紐付け・引用）',
              lambda: not _has_table(db, name, 'members'),
              lambda: db.execute_raw(MEMBERS_SQL)))

    def is_main_apply():
        db.execute_raw("""ALTER TABLE `branches`
                     ADD COLUMN `is_main` TINYINT(1) NOT NULL DEFAULT 0
                     COMMENT '主拠点フラグ（1=主拠点・削除不可、名称変更のみ）' AFTER `name`""")
        # 各テナントの最初の拠点（最小ID）を主拠点にする
        db.execute_raw("""UPDATE `branches` b
                     JOIN (SELECT `tenant_id`, MIN(`id`) AS min_id FROM `branches` GROUP BY `tenant_id`) t
                       ON b.`tenant_id` = t.`tenant_id` AND b.`id` = t.min_id
                     SET b.`is_main` = 1""")
    m.append(('branches に主拠点フラグを追加し、各テナントの最初の拠点を主拠点に設定（2026-07-09）',
              lambda: not _has_column(db, name, 'branches', 'is_main'), is_main_apply))

    def is_owner_apply():
        db.execute_raw("""ALTER TABLE `users`
                     ADD COLUMN `is_owner` TINYINT(1) NOT NULL DEFAULT 0
                     COMMENT 'オーナーフラグ（1=テナント作成時の初期管理者・削除/無効化不可）' AFTER `role`""")
        # 各テナントの管理者のうち、有効な管理者を優先して最小IDをオーナーにする
        db.execute_raw("""UPDATE `users` u
                     JOIN (SELECT `tenant_id`,
                                  COALESCE(MIN(CASE WHEN `is_active` = 1 THEN `id` END), MIN(`id`)) AS min_id
                           FROM `users` WHERE `role` = 'admin' GROUP BY `tenant_id`) t
                       ON u.`tenant_id` = t.`tenant_id` AND u.`id` = t.min_id
                     SET u.`is_owner` = 1""")
    m.append(('users にオーナーフラグを追加し、各テナントの有効な管理者（いなければ最初の管理者）をオーナーに設定',
              lambda: not _has_column(db, name, 'users', 'is_owner'), is_owner_apply))

    m.append(('ledger_files.file_type に商品画像（item_photo）を追加',
              lambda: 'item_photo' not in str(db.value("""SELECT COLUMN_TYPE FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'ledger_files' AND COLUMN_NAME = 'file_type'""",
                                                        (name,)) or ''),
              lambda: db.execute_raw("""ALTER TABLE `ledger_files`
                     MODIFY `file_type` ENUM('id_document','purchase_receipt','item_photo') NOT NULL
                     COMMENT 'id_document=本人確認書類, purchase_receipt=購入証明, item_photo=商品画像'""")))

    m.append(('ledgers に承認状態カラムを追加（本人確認スキップ+未認証相手の管理者承認フロー）',
              lambda: not _has_column(db, name, 'ledgers', 'approval_status'),
              lambda: db.execute_raw("""ALTER TABLE `ledgers`
                     ADD COLUMN `approval_status` ENUM('none','pending','approved') NOT NULL DEFAULT 'none'
                       COMMENT '承認状態（pending=本人確認スキップ+未認証相手のため管理者確認待ち）' AFTER `id_document_number`,
                     ADD COLUMN `approved_by` INT UNSIGNED NULL DEFAULT NULL COMMENT '承認者 users.id' AFTER `approval_status`,
                     ADD COLUMN `approved_at` DATETIME NULL DEFAULT NULL COMMENT '承認日時' AFTER `approved_by`""")))

    m.append(('sales テーブルを作成（在庫管理・販売記録・POS連携）',
              lambda: not _has_table(db, name, 'sales'),
              lambda: db.execute_raw("""CREATE TABLE IF NOT EXISTS `sales` (
                        `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        `tenant_id`   INT UNSIGNED    NOT NULL,
                        `ledger_id`   BIGINT UNSIGNED NOT NULL COMMENT '対象の台帳（仕入記録）',
                        `member_code` VARCHAR(50)     NULL DEFAULT NULL COMMENT '販売先の会員番号（任意）',
                        `quantity`    INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '販売個数',
                        `sale_amount` DECIMAL(12,0)   NULL DEFAULT NULL COMMENT '販売金額（この販売の合計・円）',
                        `sold_at`     DATETIME        NOT NULL COMMENT '販売日時',
                        `note`        VARCHAR(512)    NULL DEFAULT NULL COMMENT '備考（販売先・チャネル等）',
                        `created_by`  INT UNSIGNED    NULL DEFAULT NULL COMMENT '記録者 users.id',
                        `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (`id`),
                        INDEX `idx_sales_tenant_sold` (`tenant_id`, `sold_at`),
                        INDEX `idx_sales_ledger_id`   (`ledger_id`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                      COMMENT='販売記録（在庫管理）'""")))

    # sales テーブル自体が無い場合は前の項目で作成される（member_code 入り）ため対象外
    m.append(('sales に販売先の会員番号カラムを追加（2026-07-10）',
              lambda: _has_table(db, name, 'sales') and not _has_column(db, name, 'sales', 'member_code'),
              lambda: db.execute_raw(MEMBER_CODE_COLUMN_DDL)))

    def login_code_apply():
        db.execute_raw("""ALTER TABLE `branches`
                     ADD COLUMN `login_code` VARCHAR(50) NULL DEFAULT NULL
                     COMMENT '拠点ログインコード（テナント内一意）' AFTER `is_main`""")
        if not _has_index(db, name, 'branches', 'uq_branches_login_code'):
            db.execute_raw("ALTER TABLE `branches` ADD UNIQUE INDEX `uq_branches_login_code` (`tenant_id`, `login_code`)")
    m.append(('branches に拠点ログインコードを追加（拠点別ログイン対応・2026-07-10）',
              lambda: not _has_column(db, name, 'branches', 'login_code'), login_code_apply))

    from ..helpers.login_throttle import CREATE_TABLE_SQL as LOGIN_ATTEMPTS_SQL
    m.append(('login_attempts テーブルを作成（ログイン試行制限・アカウントロックDoS対策・2026-10）',
              lambda: not _has_table(db, name, 'login_attempts'),
              lambda: db.execute_raw(LOGIN_ATTEMPTS_SQL)))

    def owner_fix_needed():
        # 列自体が無い場合は前の項目で追加・設定されるため対象外
        if _count(db, """SELECT COUNT(*) FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = ?
                       AND ((TABLE_NAME = 'branches' AND COLUMN_NAME = 'is_main')
                         OR (TABLE_NAME = 'users'    AND COLUMN_NAME = 'is_owner'))""", (name,)) < 2:
            return False
        no_main = _count(db, """SELECT COUNT(DISTINCT b.`tenant_id`) FROM `branches` b
                     WHERE NOT EXISTS (SELECT 1 FROM `branches` m WHERE m.`tenant_id` = b.`tenant_id` AND m.`is_main` = 1)""")
        no_owner = _count(db, """SELECT COUNT(DISTINCT u.`tenant_id`) FROM `users` u
                     WHERE u.`role` = 'admin'
                       AND NOT EXISTS (SELECT 1 FROM `users` o WHERE o.`tenant_id` = u.`tenant_id` AND o.`is_owner` = 1)""")
        return no_main > 0 or no_owner > 0

    def owner_fix_apply():
        db.execute_raw("""UPDATE `branches` b
                     JOIN (SELECT `tenant_id`, MIN(`id`) AS min_id FROM `branches` GROUP BY `tenant_id`) t
                       ON b.`tenant_id` = t.`tenant_id` AND b.`id` = t.min_id
                     SET b.`is_main` = 1
                     WHERE b.`tenant_id` NOT IN (
                         SELECT tid FROM (SELECT DISTINCT `tenant_id` AS tid FROM `branches` WHERE `is_main` = 1) x
                     )""")
        db.execute_raw("""UPDATE `users` u
                     JOIN (SELECT `tenant_id`,
                                  COALESCE(MIN(CASE WHEN `is_active` = 1 THEN `id` END), MIN(`id`)) AS min_id
                           FROM `users` WHERE `role` = 'admin' GROUP BY `tenant_id`) t
                       ON u.`tenant_id` = t.`tenant_id` AND u.`id` = t.min_id
                     SET u.`is_owner` = 1
                     WHERE u.`tenant_id` NOT IN (
                         SELECT tid FROM (SELECT DISTINCT `tenant_id` AS tid FROM `users` WHERE `is_owner` = 1) x
                     )""")
    m.append(('主拠点・オーナーが未設定のテナントを補正（初期データでフラグが立っていなかった不具合の修復・2026-10）',
              owner_fix_needed, owner_fix_apply))

    m.append(('POSレジのテーブルを作成（会計・明細・設定・レシート番号・レジ精算・2026-10-22）',
              lambda: _count(db, "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_NAME IN (%s)"
                             % ','.join('?' * len(pos_schema.TABLES)), [name] + list(pos_schema.TABLES)) < len(pos_schema.TABLES),
              lambda: [db.execute_raw(pos_schema.ddl(t)) for t in pos_schema.TABLES]))

    m.append(('sales に会計（POS取引）との紐付け列 transaction_id を追加（2026-10-22）',
              lambda: _has_table(db, name, 'sales') and not _has_column(db, name, 'sales', 'transaction_id'),
              lambda: db.execute_raw(pos_schema.SALES_TRANSACTION_COLUMN_DDL)))

    m.append(('POSレジにレジ番号・会員の紐付け列を追加し、過去の会計に会員IDを補完（2026-10-23）',
              lambda: pos_schema.pending_column_upgrades(db) != [],
              lambda: pos_schema.apply_column_upgrades(db)))

    m.append(('ledgers に本人確認書類「その他」の内容（id_document_type_note）と販売予定価格（sale_price）の列を追加（2026-10-26）',
              lambda: ledger_schema.missing_columns(db) != [],
              lambda: ledger_schema.apply(db)))
    return m


def _code_warnings(db):
    """拠点ログインコードの重複（旧バージョンのデータ）の点検"""
    out = []
    try:
        for r in db.query(
                """SELECT b.`login_code`, GROUP_CONCAT(CONCAT(t.`code`, ':', b.`name`) ORDER BY b.`id` SEPARATOR ' / ') AS owners
             FROM `branches` b JOIN `tenants` t ON t.`id` = b.`tenant_id`
             WHERE b.`login_code` IS NOT NULL AND b.`login_code` <> ''
             GROUP BY b.`login_code`
             HAVING COUNT(*) > 1"""):
            out.append('拠点ログインコード「%s」が複数の拠点で重複しています（このコードではログインできません）: %s'
                       % (r['login_code'], r['owners']))
        for r in db.query(
                """SELECT b.`login_code`, CONCAT(bt.`code`, ':', b.`name`) AS owner
             FROM `branches` b
             JOIN `tenants` t  ON t.`code` = b.`login_code`
             JOIN `tenants` bt ON bt.`id` = b.`tenant_id`"""):
            out.append('拠点ログインコード「%s」（%s）がテナントコードと同じです（テナントコードが優先され、この拠点コードでは拠点を特定できません）'
                       % (r['login_code'], r['owner']))
    except Exception:
        pass  # login_code 列が無い環境では点検不要
    return out


def handle(page):
    logged_in, must_change = admin_logged_in(page)
    if must_change:
        return simple_page(403, 'パスワード変更が必要です',
                           '<p>システム管理者のパスワードが初期値のままです。先に '
                           '<a href="/admin/index.cgi?page=password">パスワード変更</a> を行ってから実行してください。</p>')
    if not logged_in:
        return simple_page(403, '認証が必要です',
                           '<h1 style="font-size:1.1rem;color:#1e3a5f;margin:0 0 12px;">システム管理者のログインが必要です</h1>'
                           '<p style="font-size:.9rem;line-height:1.8;color:#555;margin:0 0 12px;">'
                           'このマイグレーションスクリプトはスキーマを変更します。実行するには、先に'
                           ' <code>/admin/</code> からシステム管理者としてログインしてください。</p>'
                           '<p style="font-size:.9rem;line-height:1.8;color:#c0392b;margin:0;">'
                           '<strong>適用完了後は、この migrate.cgi を直ちにサーバーから削除してください。</strong></p>')

    # CSRF 対策（システム管理画面と同じトークンを使う）
    token = page.session.get('_csrf_token')
    if not token:
        token = secrets.token_hex(32)
        page.session.set('_csrf_token', token)

    errors, results, pending = [], [], []
    db = None
    items = []
    try:
        cfg = config.database()
        db = Database(cfg)
        db.connection()
        name = cfg['dbname']
        items = migrations(db, name)
    except Exception as e:
        errors.append('DB接続に失敗しました: %s' % e)
        db = None

    def check_all(report=True):
        out = []
        for label, check, _ in items:
            try:
                if check():
                    out.append(label)
            except Exception as e:
                if report:
                    errors.append('チェック失敗（%s）: %s' % (label, e))
        return out

    if db is not None:
        pending = check_all()
    req = page.request
    if req.is_post() and req.post('run') is not None:
        sent = req.raw_post('_csrf_token')
        if sent == '' or not secrets.compare_digest(str(token), sent):
            errors.append('セッションの有効期限が切れたか、不正なリクエストです。ページを再読み込みしてもう一度実行してください。')
        elif db is not None:
            for label, check, apply in items:
                try:
                    if check():
                        apply()
                        results.append('適用: ' + label)
                    else:
                        results.append('スキップ（適用済み）: ' + label)
                except Exception as e:
                    errors.append('適用失敗（%s）: %s' % (label, e))
            pending = check_all(report=False)

    try:
        return page.render('maintenance/migrate', {
            'errors': errors, 'codeWarnings': _code_warnings(db) if db is not None else [],
            'results': results, 'db_ok': db is not None, 'pending': pending, 'csrf_token': token,
        })
    finally:
        if db is not None:
            db.close()


def application(environ, start_response):
    return run(handle, environ, start_response, COOKIE)
