<?php

namespace FuryoDacho\Helpers;

/**
 * ファイルアップロードヘルパー
 * - MIMEタイプ・サイズ検証
 * - UUIDベースのファイル名生成
 * - ストレージへの保存（暗号化前処理）
 */
class FileUpload
{
    private array  $config;
    private string $uploadDir;

    /** @var array<string> 許可するMIMEタイプ */
    private array $allowedMimeTypes;

    /** @var int 最大ファイルサイズ（バイト） */
    private int $maxFileSize;

    public function __construct()
    {
        $this->config          = require __DIR__ . '/../../config/config.php';
        $this->uploadDir       = rtrim($this->config['upload_dir'], '/');
        $this->allowedMimeTypes = $this->config['allowed_mime_types'];
        $this->maxFileSize     = $this->config['max_file_size'];
    }

    /**
     * ファイルを検証・暗号化してストレージに保存する（Phase4 メイン API）
     *
     * @param array  $file      $_FILES['field'] の値
     * @param int    $tenantId  テナントID
     * @param int    $ledgerId  台帳ID（サブディレクトリ分離に使用）
     * @param string $fileType  'id_document' | 'purchase_receipt'
     * @return array{stored_filename: string, file_path: string, iv: string, original_filename: string, file_size: int, mime_type: string}
     * @throws \RuntimeException バリデーション失敗・暗号化失敗時
     */
    public function save(array $file, int $tenantId, int $ledgerId, string $fileType): array
    {
        $this->validate($file);

        $extension      = $this->getExtension($file['name']);
        $storedFilename = $this->generateUuidV4() . '.' . $extension;
        $destDir        = $this->uploadDir . '/' . $tenantId . '/' . $ledgerId;

        if (!is_dir($destDir) && !mkdir($destDir, 0700, true)) {
            throw new \RuntimeException("アップロードディレクトリの作成に失敗しました: {$destDir}");
        }

        $destPath = $destDir . '/' . $storedFilename;

        // finfo で MIME を確定してから暗号化
        $mimeType = $this->detectMimeType($file['tmp_name']);

        $crypto = new Crypto();
        $iv     = $crypto->encryptFile($file['tmp_name'], $destPath);

        // 暗号化成功後に一時ファイルを削除
        if (is_uploaded_file($file['tmp_name'])) {
            @unlink($file['tmp_name']);
        }

        return [
            'stored_filename'   => $storedFilename,
            'file_path'         => $tenantId . '/' . $ledgerId . '/' . $storedFilename,
            'iv'                => $iv,
            'original_filename' => basename($file['name']),
            'file_size'         => $file['size'],
            'mime_type'         => $mimeType,
        ];
    }

    /**
     * アップロードファイルを検証して一時領域に保存する（暗号化なし・後方互換）
     *
     * @param array  $file       $_FILES['field'] の値
     * @param int    $tenantId   テナントID（サブディレクトリ分離に使用）
     * @return array{stored_filename: string, file_path: string, original_filename: string, file_size: int, mime_type: string}
     * @throws \RuntimeException バリデーション失敗時
     */
    public function upload(array $file, int $tenantId): array
    {
        $this->validate($file);

        $extension      = $this->getExtension($file['name']);
        $storedFilename = $this->generateFilename($extension);
        $tenantDir      = $this->uploadDir . '/' . $tenantId;

        if (!is_dir($tenantDir) && !mkdir($tenantDir, 0700, true)) {
            throw new \RuntimeException("アップロードディレクトリの作成に失敗しました。");
        }

        $destPath = $tenantDir . '/' . $storedFilename;

        if (!move_uploaded_file($file['tmp_name'], $destPath)) {
            throw new \RuntimeException("ファイルの移動に失敗しました。");
        }

        return [
            'stored_filename'  => $storedFilename,
            'file_path'        => $tenantId . '/' . $storedFilename,
            'original_filename' => basename($file['name']),
            'file_size'        => $file['size'],
            'mime_type'        => $this->detectMimeType($destPath),
        ];
    }

    /**
     * ファイルを削除する
     */
    public function delete(string $relativePath): bool
    {
        $fullPath = $this->uploadDir . '/' . $relativePath;

        if (!file_exists($fullPath)) {
            return false;
        }

        return unlink($fullPath);
    }

    /**
     * アップロードファイルのバリデーション
     */
    private function validate(array $file): void
    {
        if (!isset($file['error']) || $file['error'] !== UPLOAD_ERR_OK) {
            throw new \RuntimeException("ファイルのアップロードに失敗しました。エラーコード: " . ($file['error'] ?? 'unknown'));
        }

        if ($file['size'] > $this->maxFileSize) {
            $maxMb = round($this->maxFileSize / 1048576, 1);
            throw new \RuntimeException("ファイルサイズが上限（{$maxMb}MB）を超えています。");
        }

        if (!is_uploaded_file($file['tmp_name'])) {
            throw new \RuntimeException("不正なファイルアップロードが検出されました。");
        }

        $mimeType = $this->detectMimeType($file['tmp_name']);

        if (!in_array($mimeType, $this->allowedMimeTypes, true)) {
            throw new \RuntimeException("許可されていないファイル形式です。（{$mimeType}）");
        }
    }

    /**
     * fileinfo拡張でMIMEタイプを検出（拡張子偽装対策）
     */
    private function detectMimeType(string $filePath): string
    {
        $finfo = new \finfo(FILEINFO_MIME_TYPE);
        return $finfo->file($filePath) ?: 'application/octet-stream';
    }

    /**
     * UUIDv4ベースのファイル名を生成
     */
    private function generateFilename(string $extension): string
    {
        return sprintf(
            '%s.%s',
            $this->generateUuidV4(),
            $extension
        );
    }

    /**
     * UUIDv4を生成
     */
    private function generateUuidV4(): string
    {
        $bytes = random_bytes(16);
        $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
        $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($bytes), 4));
    }

    /**
     * ファイル名から拡張子を取得（サニタイズ済み）
     */
    private function getExtension(string $filename): string
    {
        $ext = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
        // 許可する拡張子のみ通す（設定の許可MIME・商品画像に合わせ gif/webp を含める）
        $allowed = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'pdf'];
        return in_array($ext, $allowed, true) ? $ext : 'bin';
    }
}
