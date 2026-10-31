"""
会員（相手方情報・本人確認情報の引用元）

台帳には値をコピーして保存するため、会員情報を後から変更・削除しても過去の台帳記録は変わらない。
"""
from ..db import DBError, ER_NO_SUCH_TABLE
from .base import BaseModel

CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS `members` (
                `id`                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
                `tenant_id`          INT UNSIGNED NOT NULL,
                `member_code`        VARCHAR(50)  NOT NULL COMMENT '会員番号（テナント内一意）',
                `counterpart_type`   ENUM('individual','corporate') NOT NULL DEFAULT 'individual',
                `name`               VARCHAR(255) NOT NULL COMMENT '氏名（法人の場合は名称）',
                `address`            VARCHAR(512) NULL DEFAULT NULL,
                `occupation`         VARCHAR(255) NULL DEFAULT NULL,
                `age`                TINYINT UNSIGNED NULL DEFAULT NULL,
                `phone`              VARCHAR(20)  NULL DEFAULT NULL,
                `contact_name`       VARCHAR(255) NULL DEFAULT NULL COMMENT '担当者名（法人）',
                `account`            VARCHAR(255) NULL DEFAULT NULL COMMENT '取引アカウント',
                `id_document_type`   ENUM('driver_license','my_number','passport','health_insurance','residence_card','residence_status','special_permanent','other') NULL DEFAULT NULL,
                `id_document_number` VARCHAR(64)  NULL DEFAULT NULL,
                `note`               TEXT         NULL DEFAULT NULL,
                `created_at`         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                `updated_at`         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                UNIQUE INDEX `uq_members_tenant_code` (`tenant_id`, `member_code`),
                INDEX `idx_members_tenant_id` (`tenant_id`),
                INDEX `idx_members_name` (`name`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
              COMMENT='会員（相手方情報の引用元）'"""

_OPTIONAL = ('address', 'occupation', 'phone', 'contact_name', 'account',
             'id_document_type', 'id_document_number', 'note')


def _opt(data, key):
    v = data.get(key)
    return None if v is None or v == '' else v


def _values(data):
    age = data.get('age')
    return [
        data['member_code'],
        data.get('counterpart_type') or 'individual',
        data['name'],
        _opt(data, 'address'),
        _opt(data, 'occupation'),
        int(age) if age is not None and age != '' else None,
        _opt(data, 'phone'),
        _opt(data, 'contact_name'),
        _opt(data, 'account'),
        _opt(data, 'id_document_type'),
        _opt(data, 'id_document_number'),
        _opt(data, 'note'),
    ]


class Member(BaseModel):
    table = 'members'

    def _with_table(self, fn):
        try:
            return fn()
        except DBError as e:
            if e.code == ER_NO_SUCH_TABLE:
                self.db.execute(CREATE_TABLE_SQL)
                return fn()
            raise

    def search(self, tenant_id, keyword=None, limit=50, offset=0):
        """一覧（会員番号・氏名の部分一致で検索できる）"""
        def run():
            sql = "SELECT * FROM `members` WHERE `tenant_id` = ?"
            params = [int(tenant_id)]
            if keyword is not None and keyword != '':
                sql += " AND (`member_code` LIKE ? OR `name` LIKE ?)"
                like = '%' + keyword + '%'
                params += [like, like]
            sql += " ORDER BY `member_code` ASC LIMIT %d OFFSET %d" % (int(limit), int(offset))
            return self.db.query(sql, params)
        return self._with_table(run)

    def count_all(self, tenant_id, keyword=None):
        def run():
            sql = "SELECT COUNT(*) FROM `members` WHERE `tenant_id` = ?"
            params = [int(tenant_id)]
            if keyword is not None and keyword != '':
                sql += " AND (`member_code` LIKE ? OR `name` LIKE ?)"
                like = '%' + keyword + '%'
                params += [like, like]
            return int(self.db.value(sql, params) or 0)
        return self._with_table(run)

    def find_by_id(self, member_id, tenant_id):
        return self._with_table(lambda: self.db.query_one(
            "SELECT * FROM `members` WHERE `id` = ? AND `tenant_id` = ?", (int(member_id), int(tenant_id))))

    def find_by_code(self, tenant_id, code):
        """会員番号で検索（台帳フォームの引用機能）"""
        return self._with_table(lambda: self.db.query_one(
            "SELECT * FROM `members` WHERE `tenant_id` = ? AND `member_code` = ?", (int(tenant_id), code)))

    def exists_code(self, tenant_id, code, exclude_id=None):
        def run():
            sql = "SELECT COUNT(*) FROM `members` WHERE `tenant_id` = ? AND `member_code` = ?"
            params = [int(tenant_id), code]
            if exclude_id is not None:
                sql += " AND `id` != ?"
                params.append(int(exclude_id))
            return int(self.db.value(sql, params) or 0) > 0
        return self._with_table(run)

    def generate_code(self, tenant_id):
        """未使用の会員番号を自動で付ける（M-0001 形式）"""
        def run():
            last = self.db.value(
                """SELECT `member_code` FROM `members`
                 WHERE `tenant_id` = ? AND `member_code` REGEXP '^M-[0-9]+$'
                 ORDER BY CAST(SUBSTRING(`member_code`, 3) AS UNSIGNED) DESC
                 LIMIT 1""", (int(tenant_id),))
            nxt = int(str(last)[2:]) + 1 if last else 1
            while True:
                code = 'M-%04d' % nxt
                nxt += 1
                if not self.exists_code(tenant_id, code):
                    return code
        return self._with_table(run)

    def create(self, tenant_id, data):
        return self._with_table(lambda: self.db.insert(
            """INSERT INTO `members`
                    (`tenant_id`, `member_code`, `counterpart_type`, `name`, `address`,
                     `occupation`, `age`, `phone`, `contact_name`, `account`,
                     `id_document_type`, `id_document_number`, `note`)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", [int(tenant_id)] + _values(data)))

    def update(self, member_id, tenant_id, data):
        self._with_table(lambda: self.db.execute(
            """UPDATE `members` SET
                    `member_code` = ?, `counterpart_type` = ?, `name` = ?, `address` = ?,
                    `occupation` = ?, `age` = ?, `phone` = ?, `contact_name` = ?, `account` = ?,
                    `id_document_type` = ?, `id_document_number` = ?, `note` = ?, `updated_at` = NOW()
                 WHERE `id` = ? AND `tenant_id` = ?""", _values(data) + [int(member_id), int(tenant_id)]))
        return True

    def delete(self, member_id, tenant_id):
        self._with_table(lambda: self.db.execute(
            "DELETE FROM `members` WHERE `id` = ? AND `tenant_id` = ?", (int(member_id), int(tenant_id))))
        return True
