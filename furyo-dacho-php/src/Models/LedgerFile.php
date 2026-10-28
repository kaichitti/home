<?php

namespace FuryoDacho\Models;

/**
 * LedgerFile モデル
 * 添付ファイル（暗号化保存）の管理を担当する。
 * iv カラムに暗号化時の IV（hex 文字列）を保存し、復号時に使用する。
 */
class LedgerFile extends BaseModel
{

    /**
     * 台帳IDと種別で全ファイルを取得（商品画像一覧用）
     */
    public function findAllByLedgerAndType(int $ledgerId, int $tenantId, string $fileType): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `ledger_files`
             WHERE `ledger_id` = ? AND `tenant_id` = ? AND `file_type` = ?
             ORDER BY `id` ASC"
        );
        $stmt->execute([$ledgerId, $tenantId, $fileType]);
        return $stmt->fetchAll();
    }

    /**
     * 台帳IDと種別のファイル数
     */
    public function countByLedgerAndType(int $ledgerId, int $tenantId, string $fileType): int
    {
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) FROM `ledger_files`
             WHERE `ledger_id` = ? AND `tenant_id` = ? AND `file_type` = ?"
        );
        $stmt->execute([$ledgerId, $tenantId, $fileType]);
        return (int)$stmt->fetchColumn();
    }

    protected string $table = 'ledger_files';

    /**
     * ファイルレコードを作成
     *
     * @param array $data {
     *   ledger_id, tenant_id, file_type, original_filename,
     *   stored_filename, file_path, iv, file_size, mime_type
     * }
     * @return int 生成された ID
     */
    public function create(array $data): int
    {
        $stmt = $this->pdo->prepare(
            "INSERT INTO `ledger_files`
             (`ledger_id`, `tenant_id`, `file_type`, `original_filename`,
              `stored_filename`, `file_path`, `iv`, `file_size`, `mime_type`)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        );
        $stmt->execute([
            $data['ledger_id'],
            $data['tenant_id'],
            $data['file_type'],
            $data['original_filename'],
            $data['stored_filename'],
            $data['file_path'],
            $data['iv'],
            $data['file_size'],
            $data['mime_type'],
        ]);
        return (int)$this->pdo->lastInsertId();
    }

    /**
     * 台帳 ID に紐づくファイル一覧を取得
     *
     * @param int $ledgerId
     * @param int $tenantId
     * @return array
     */
    public function findByLedger(int $ledgerId, int $tenantId): array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `ledger_files`
             WHERE `ledger_id` = ? AND `tenant_id` = ?
             ORDER BY `created_at` ASC"
        );
        $stmt->execute([$ledgerId, $tenantId]);
        return $stmt->fetchAll();
    }

    /**
     * 後方互換エイリアス
     */
    public function getByLedger(int $ledgerId, int $tenantId): array
    {
        return $this->findByLedger($ledgerId, $tenantId);
    }

    /**
     * 台帳 ID + ファイル種別で最新のファイルを取得
     * （同種別のファイルが複数ある場合は最後にアップロードされたものを返す）
     *
     * @param int    $ledgerId
     * @param int    $tenantId
     * @param string $fileType 'id_document' | 'purchase_receipt'
     * @return array|null
     */
    public function findLatestByLedgerAndType(int $ledgerId, int $tenantId, string $fileType): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `ledger_files`
             WHERE `ledger_id` = ? AND `tenant_id` = ? AND `file_type` = ?
             ORDER BY `id` DESC
             LIMIT 1"
        );
        $stmt->execute([$ledgerId, $tenantId, $fileType]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    /**
     * ID と テナント ID でファイルを取得
     *
     * @param int $id
     * @param int $tenantId
     * @return array|null
     */
    public function findById(int $id, int $tenantId): ?array
    {
        $stmt = $this->pdo->prepare(
            "SELECT * FROM `ledger_files` WHERE `id` = ? AND `tenant_id` = ?"
        );
        $stmt->execute([$id, $tenantId]);
        $row = $stmt->fetch();
        return $row ?: null;
    }

    /**
     * 台帳に紐づく全ファイルを削除する（物理ファイルも削除）
     *
     * @param int    $ledgerId
     * @param int    $tenantId
     * @param string $uploadDir config の upload_dir（絶対パス）
     */
    public function deleteByLedger(int $ledgerId, int $tenantId, string $uploadDir): void
    {
        $files = $this->findByLedger($ledgerId, $tenantId);

        foreach ($files as $file) {
            $fullPath = rtrim($uploadDir, '/') . '/' . $file['file_path'];
            if (file_exists($fullPath)) {
                @unlink($fullPath);
            }
        }

        $stmt = $this->pdo->prepare(
            "DELETE FROM `ledger_files` WHERE `ledger_id` = ? AND `tenant_id` = ?"
        );
        $stmt->execute([$ledgerId, $tenantId]);
    }

    /**
     * ファイルレコードを 1 件削除（物理ファイルの削除は呼び出し元で行う）
     *
     * @param int $id
     * @param int $tenantId
     * @return bool
     */
    public function delete(int $id, int $tenantId): bool
    {
        $stmt = $this->pdo->prepare(
            "DELETE FROM `ledger_files` WHERE `id` = ? AND `tenant_id` = ?"
        );
        return $stmt->execute([$id, $tenantId]);
    }
}
