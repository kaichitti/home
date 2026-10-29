"""
古物区分

区分は3種類:
  1. 法定13区分（古物営業法施行規則 別表第1）: 英語コードで ledgers に保存
  2. その他（'other'）: item_category_note に自由記述を保存
  3. テナント独自区分: 区分名をそのまま ledgers に保存
     （区分を後から削除しても過去の帳簿の表記は変わらない）
"""
from ..db import DBError, ER_NO_SUCH_TABLE
from ..util import trim
from .base import BaseModel

OTHER = 'other'

STATUTORY = {
    'art': '美術品類',
    'clothing': '衣類',
    'watch_jewelry': '時計・宝飾品類',
    'automobile': '自動車',
    'motorcycle': '自動二輪車及び原動機付自転車',
    'bicycle': '自転車類',
    'camera': '写真機類',
    'office_equipment': '事務機器類',
    'machinery': '機械工具類',
    'tools': '道具類',
    'leather_rubber': '皮革・ゴム製品類',
    'books': '書籍',
    'gift_certificates': '金券類',
}

CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS `item_categories` (
                `id`         INT UNSIGNED NOT NULL AUTO_INCREMENT,
                `tenant_id`  INT UNSIGNED NOT NULL,
                `name`       VARCHAR(100) NOT NULL COMMENT '区分名',
                `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (`id`),
                UNIQUE INDEX `uq_item_categories_tenant_name` (`tenant_id`, `name`),
                INDEX `idx_item_categories_tenant_id` (`tenant_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
              COMMENT='テナント独自の古物区分'"""


def label(value, note=None):
    """保存値を表示名にする"""
    if value is None or value == '':
        return ''
    value = str(value)
    if value in STATUTORY:
        return STATUTORY[value]
    if value == OTHER:
        return 'その他（%s）' % note if note is not None and note != '' else 'その他'
    return value  # テナント独自区分は名前がそのまま保存されている


class CategoryError(RuntimeError):
    """利用者に表示するメッセージ付きのエラー"""


class ItemCategory(BaseModel):
    table = 'item_categories'

    def _with_table(self, fn):
        """テーブルが無い（マイグレーション未実行）場合は作成してやり直す"""
        try:
            return fn()
        except DBError as e:
            if e.code == ER_NO_SUCH_TABLE:
                self.db.execute(CREATE_TABLE_SQL)
                return fn()
            raise

    def find_all_by_tenant(self, tenant_id):
        return self._with_table(lambda: self.db.query(
            "SELECT * FROM `item_categories` WHERE `tenant_id` = ? ORDER BY `name` ASC", (int(tenant_id),)))

    def find_by_id(self, category_id, tenant_id):
        return self._with_table(lambda: self.db.query_one(
            "SELECT * FROM `item_categories` WHERE `id` = ? AND `tenant_id` = ?", (int(category_id), int(tenant_id))))

    def create(self, tenant_id, name):
        name = trim(name)
        if name == '':
            raise CategoryError('区分名を入力してください。')
        if len(name) > 100:
            raise CategoryError('区分名は100文字以内で入力してください。')
        # 法定区分の名称・コード、'other' との衝突を防ぐ
        if name in STATUTORY.values() or name in STATUTORY or name == OTHER or name == 'その他':
            raise CategoryError('この区分名は既定の区分と重複しているため使用できません。')
        if self.exists_name(tenant_id, name):
            raise CategoryError('この区分名はすでに登録されています。')
        return self._with_table(lambda: self.db.insert(
            "INSERT INTO `item_categories` (`tenant_id`, `name`) VALUES (?, ?)", (int(tenant_id), name)))

    def delete(self, category_id, tenant_id):
        """削除する（過去の台帳には区分名がそのまま保存されているため、表示・検索に影響しない）"""
        self.db.execute("DELETE FROM `item_categories` WHERE `id` = ? AND `tenant_id` = ?",
                        (int(category_id), int(tenant_id)))
        return True

    def exists_name(self, tenant_id, name):
        return self._with_table(lambda: int(self.db.value(
            "SELECT COUNT(*) FROM `item_categories` WHERE `tenant_id` = ? AND `name` = ?",
            (int(tenant_id), name)) or 0) > 0)

    def build_options(self, tenant_id):
        """台帳フォーム・検索用の選択肢（法定13区分 + 独自区分 + その他）"""
        options = dict(STATUTORY)
        for row in self.find_all_by_tenant(tenant_id):
            options[row['name']] = row['name']
        options[OTHER] = 'その他（自由記述）'
        return options

    def is_valid_value(self, tenant_id, value):
        if value in STATUTORY or value == OTHER:
            return True
        return self.exists_name(tenant_id, value)
