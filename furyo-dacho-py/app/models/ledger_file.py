"""台帳の添付ファイル（暗号化して保存。iv 列に復号用の情報を保存する）"""
import os

from .base import BaseModel


class LedgerFile(BaseModel):
    table = 'ledger_files'

    def find_all_by_ledger_and_type(self, ledger_id, tenant_id, file_type):
        return self.db.query(
            """SELECT * FROM `ledger_files`
             WHERE `ledger_id` = ? AND `tenant_id` = ? AND `file_type` = ?
             ORDER BY `id` ASC""", (int(ledger_id), int(tenant_id), file_type))

    def count_by_ledger_and_type(self, ledger_id, tenant_id, file_type):
        return int(self.db.value(
            """SELECT COUNT(*) FROM `ledger_files`
             WHERE `ledger_id` = ? AND `tenant_id` = ? AND `file_type` = ?""",
            (int(ledger_id), int(tenant_id), file_type)) or 0)

    def create(self, data):
        return self.db.insert(
            """INSERT INTO `ledger_files`
             (`ledger_id`, `tenant_id`, `file_type`, `original_filename`,
              `stored_filename`, `file_path`, `iv`, `file_size`, `mime_type`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(data['ledger_id']), int(data['tenant_id']), data['file_type'], data['original_filename'],
             data['stored_filename'], data['file_path'], data['iv'], int(data['file_size']), data['mime_type']))

    def find_by_ledger(self, ledger_id, tenant_id):
        return self.db.query(
            """SELECT * FROM `ledger_files`
             WHERE `ledger_id` = ? AND `tenant_id` = ?
             ORDER BY `created_at` ASC""", (int(ledger_id), int(tenant_id)))

    def find_latest_by_ledger_and_type(self, ledger_id, tenant_id, file_type):
        """同じ種別のファイルが複数ある場合は最後に登録したもの"""
        return self.db.query_one(
            """SELECT * FROM `ledger_files`
             WHERE `ledger_id` = ? AND `tenant_id` = ? AND `file_type` = ?
             ORDER BY `id` DESC
             LIMIT 1""", (int(ledger_id), int(tenant_id), file_type))

    def find_by_id(self, file_id, tenant_id):
        return self.db.query_one("SELECT * FROM `ledger_files` WHERE `id` = ? AND `tenant_id` = ?",
                                 (int(file_id), int(tenant_id)))

    def delete_by_ledger(self, ledger_id, tenant_id, upload_dir):
        """台帳の全ファイルを削除する（ファイル本体も削除）"""
        for f in self.find_by_ledger(ledger_id, tenant_id):
            full = os.path.join(upload_dir.rstrip('/'), f['file_path'])
            try:
                if os.path.exists(full):
                    os.unlink(full)
            except OSError:
                pass
        self.db.execute("DELETE FROM `ledger_files` WHERE `ledger_id` = ? AND `tenant_id` = ?",
                        (int(ledger_id), int(tenant_id)))

    def delete(self, file_id, tenant_id):
        """1件削除（ファイル本体の削除は呼び出し元で行う）"""
        self.db.execute("DELETE FROM `ledger_files` WHERE `id` = ? AND `tenant_id` = ?", (int(file_id), int(tenant_id)))
        return True
