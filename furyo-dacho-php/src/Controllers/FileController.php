<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\LedgerFile;
use FuryoDacho\Models\AuditLog;
use FuryoDacho\Helpers\Crypto;

/**
 * ファイルダウンロードコントローラー
 *
 * 暗号化済みファイルへの Web 直接アクセスを禁止し、
 * このコントローラー経由でのみファイルを提供する。
 * ダウンロード時にテナント ID の二重チェックを行う。
 */
class FileController extends BaseController
{
    /**
     * 暗号化ファイルを復号してダウンロードさせる
     *
     * GET /index.php?page=file.download&id={id}
     */
    public function download(): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();
        $id       = (int)$this->request->get('id', 0);
        $typeIn   = $this->request->get('type', '');
        $type     = is_string($typeIn) ? $typeIn : '';

        if ($id <= 0) {
            $this->response->notFound('ファイル ID が不正です。');
            return;
        }

        $ledgerFileModel = new LedgerFile($this->pdo);

        if ($type !== '') {
            // ビューからのリンクは「台帳ID + ファイル種別」で渡される。
            // 以前は id を ledger_files.id と解釈していたため、
            // IDのズレで404や別ファイルの取得が発生していた。
            // 旧リンクの 'receipt_form' も DB enum の 'purchase_receipt' に正規化する。
            $fileType = $type === 'receipt_form' ? 'purchase_receipt' : $type;

            if (!in_array($fileType, ['id_document', 'purchase_receipt', 'item_photo'], true)) {
                $this->response->notFound('ファイル種別が不正です。');
                return;
            }

            $fileRecord = $ledgerFileModel->findLatestByLedgerAndType($id, $tenantId, $fileType);
        } else {
            // 後方互換: type 指定なしの場合は ledger_files.id として扱う
            $fileRecord = $ledgerFileModel->findById($id, $tenantId);
        }

        if ($fileRecord === null) {
            $this->response->notFound('ファイルが見つかりません。');
            return;
        }

        // テナント ID 二重チェック（念のため再確認）
        if ((int)$fileRecord['tenant_id'] !== $tenantId) {
            $this->response->notFound('ファイルが見つかりません。');
            return;
        }

        $config          = require __DIR__ . '/../../config/config.php';
        $uploadDir       = rtrim($config['upload_dir'], '/');
        $encryptedPath   = $uploadDir . '/' . $fileRecord['file_path'];

        if (!file_exists($encryptedPath)) {
            $this->response->notFound('ファイルが見つかりません。');
            return;
        }

        // 復号して一時ファイルに書き出す
        try {
            $crypto  = new Crypto();
            $tmpPath = $crypto->decryptFile($encryptedPath, $fileRecord['iv']);
        } catch (\RuntimeException $e) {
            $this->response->status(500)->text('ファイルの復号に失敗しました。');
            return;
        }

        // 安全なファイル名を組み立てる（ヘッダーインジェクション対策）
        // ASCIIフォールバック + RFC 5987 filename* で日本語ファイル名を保持する
        // （以前は日本語がすべて "_" に置換され「___.png」のようになっていた）
        $original     = (string)$fileRecord['original_filename'];
        $asciiName    = preg_replace('/[^\w.\-]/u', '_', $original) ?: 'download';
        $utf8Name     = rawurlencode(str_replace(["\r", "\n", '"'], '', $original));
        $mimeType     = $fileRecord['mime_type'] ?: 'application/octet-stream';
        $fileSize     = filesize($tmpPath);

        // ダウンロードヘッダーを送信
        header('Content-Type: ' . $mimeType);
        // inline=1 かつ画像の場合はブラウザ内表示（商品画像プレビュー用）
        $disposition = ($this->request->get('inline') === '1'
            && strpos((string)$fileRecord['mime_type'], 'image/') === 0)
            ? 'inline' : 'attachment';
        header('Content-Disposition: ' . $disposition . '; filename="' . $asciiName . '"; filename*=UTF-8\'\'' . $utf8Name);
        header('Content-Length: ' . $fileSize);
        header('Cache-Control: no-store, no-cache, must-revalidate');
        header('Pragma: no-cache');
        header('X-Content-Type-Options: nosniff');

        // ファイルをストリーム送信
        $fh = fopen($tmpPath, 'rb');
        if ($fh !== false) {
            while (!feof($fh)) {
                echo fread($fh, 8192);
            }
            fclose($fh);
        }

        // 一時ファイルを削除
        @unlink($tmpPath);

        // 監査ログ（export アクション）
        try {
            (new AuditLog($this->pdo))->log(
                $tenantId,
                $userId,
                $this->auth->user()['display_name'],
                null,
                'export',
                $id,
                null,
                ['file_type' => $fileRecord['file_type'], 'original_filename' => $fileRecord['original_filename']],
                $this->request->ip()
            );
        } catch (\Throwable $e) {
            // 監査ログ失敗はサイレントに処理（ダウンロード自体は完了済み）
            error_log('AuditLog 書き込みエラー: ' . $e->getMessage());
        }

        exit;
    }
}
