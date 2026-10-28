<?php

namespace FuryoDacho\Helpers;

/**
 * 認証付き暗号（AES-256-GCM）ヘルパー
 *
 * PHP openssl 拡張を使用。新規データは AES-256-GCM で暗号化し、
 * 認証タグ（GMAC）により改ざんを検知できる（Encrypt-then-MAC 相当）。
 *
 * 後方互換: 旧バージョンが AES-256-CBC（認証なし）で保存したデータも
 * 復号できる。判定方法:
 *   - 文字列: 先頭マジック "FDC1" があれば GCM、なければ旧 CBC。
 *   - ファイル: iv カラムに ':' が含まれれば "ivhex:taghex"（GCM）、
 *               含まれなければ 32桁の hex（旧 CBC の 16byte IV）。
 */
class Crypto
{
    /** 新規データ用（認証付き） */
    private const CIPHER_GCM = 'aes-256-gcm';
    /** 旧データ復号用（後方互換・認証なし） */
    private const CIPHER_CBC = 'AES-256-CBC';

    private const GCM_IV_LENGTH  = 12;
    private const GCM_TAG_LENGTH = 16;
    private const CBC_IV_LENGTH  = 16;

    /** 文字列暗号化の新フォーマット識別子（旧CBCデータと区別するため） */
    private const MAGIC = "FDC1";

    private string $key;

    public function __construct(?string $key = null)
    {
        $configKey = $key ?? (require __DIR__ . '/../../config/config.php')['encryption_key'];

        if (empty($configKey)) {
            throw new \RuntimeException('暗号化キーが設定されていません。環境変数 ENCRYPTION_KEY を設定してください。');
        }

        // 鍵を256ビット（32バイト）に正規化
        // （旧データとの互換のため、鍵の導出方法は変更しない）
        $this->key = substr(hash('sha256', $configKey, true), 0, 32);
    }

    /**
     * 平文を暗号化してBase64文字列を返す（AES-256-GCM・認証付き）
     *
     * フォーマット: base64( MAGIC(4) + IV(12) + TAG(16) + 暗号文 )
     *
     * @param string $plainText 暗号化する平文
     * @return string
     * @throws \RuntimeException 暗号化失敗時
     */
    public function encrypt(string $plainText): string
    {
        $iv  = random_bytes(self::GCM_IV_LENGTH);
        $tag = '';

        $encrypted = openssl_encrypt(
            $plainText,
            self::CIPHER_GCM,
            $this->key,
            OPENSSL_RAW_DATA,
            $iv,
            $tag,
            '',
            self::GCM_TAG_LENGTH
        );

        if ($encrypted === false) {
            throw new \RuntimeException('暗号化に失敗しました。');
        }

        return base64_encode(self::MAGIC . $iv . $tag . $encrypted);
    }

    /**
     * Base64エンコードされた暗号文を復号して平文を返す
     *
     * 新フォーマット（GCM）と旧フォーマット（CBC）を自動判定する。
     *
     * @param string $cipherText encrypt() が返した文字列（または旧CBC形式）
     * @return string
     * @throws \RuntimeException 復号失敗・改ざん検知時
     */
    public function decrypt(string $cipherText): string
    {
        $raw = base64_decode($cipherText, true);

        if ($raw === false) {
            throw new \RuntimeException('暗号文のフォーマットが不正です。');
        }

        $magicLen = strlen(self::MAGIC);

        if (strncmp($raw, self::MAGIC, $magicLen) === 0) {
            // 新フォーマット（AES-256-GCM）
            $iv  = substr($raw, $magicLen, self::GCM_IV_LENGTH);
            $tag = substr($raw, $magicLen + self::GCM_IV_LENGTH, self::GCM_TAG_LENGTH);
            $enc = substr($raw, $magicLen + self::GCM_IV_LENGTH + self::GCM_TAG_LENGTH);

            if (strlen($iv) !== self::GCM_IV_LENGTH || strlen($tag) !== self::GCM_TAG_LENGTH) {
                throw new \RuntimeException('暗号文のフォーマットが不正です。');
            }

            $decrypted = openssl_decrypt($enc, self::CIPHER_GCM, $this->key, OPENSSL_RAW_DATA, $iv, $tag);
        } else {
            // 旧フォーマット（AES-256-CBC・後方互換）
            if (strlen($raw) < self::CBC_IV_LENGTH) {
                throw new \RuntimeException('暗号文のフォーマットが不正です。');
            }
            $iv  = substr($raw, 0, self::CBC_IV_LENGTH);
            $enc = substr($raw, self::CBC_IV_LENGTH);
            $decrypted = openssl_decrypt($enc, self::CIPHER_CBC, $this->key, OPENSSL_RAW_DATA, $iv);
        }

        if ($decrypted === false) {
            throw new \RuntimeException('復号に失敗しました。');
        }

        return $decrypted;
    }

    /**
     * 平文のハッシュを生成（暗号化キーのハッシュ検証用）
     *
     * @param string $value ハッシュ化する値
     * @return string       SHA-256 ハッシュ（hex）
     */
    public static function hash(string $value): string
    {
        return hash('sha256', $value);
    }

    /**
     * ファイルを AES-256-GCM で暗号化して書き出す（認証付き）
     *
     * IV と認証タグをファイルに連結せず返り値として返す。
     * これにより LedgerFile テーブルの iv カラム（VARCHAR(64)）へ
     *   "ivの16進(24) : tagの16進(32)"  （計57文字）
     * の形で保存でき、暗号化ファイル本体と IV/タグを分離保管できる。
     *
     * @param string $sourcePath 暗号化するファイルのパス
     * @param string $destPath   暗号化後の出力先パス
     * @return string            "ivhex:taghex"（DB の iv カラムへ保存する）
     * @throws \RuntimeException ファイル読み書き・暗号化失敗時
     */
    public function encryptFile(string $sourcePath, string $destPath): string
    {
        $plainData = file_get_contents($sourcePath);

        if ($plainData === false) {
            throw new \RuntimeException("ファイルが読み取れません: {$sourcePath}");
        }

        $iv  = random_bytes(self::GCM_IV_LENGTH);
        $tag = '';

        $encrypted = openssl_encrypt(
            $plainData,
            self::CIPHER_GCM,
            $this->key,
            OPENSSL_RAW_DATA,
            $iv,
            $tag,
            '',
            self::GCM_TAG_LENGTH
        );

        if ($encrypted === false) {
            throw new \RuntimeException('ファイルの暗号化に失敗しました。');
        }

        if (file_put_contents($destPath, $encrypted) === false) {
            throw new \RuntimeException("ファイルの書き込みに失敗しました: {$destPath}");
        }

        return bin2hex($iv) . ':' . bin2hex($tag);
    }

    /**
     * 暗号化ファイルを復号して一時ファイルに書き出し、そのパスを返す
     *
     * 新フォーマット（GCM・iv カラムが "ivhex:taghex"）と
     * 旧フォーマット（CBC・iv カラムが 32桁 hex）を自動判定する。
     * 呼び出し元は返却されたパスを使用後に unlink() で削除すること。
     *
     * @param string $encryptedPath 暗号化されたファイルのパス
     * @param string $iv            encryptFile() が返した値（iv カラムの値）
     * @return string               復号済み一時ファイルのパス
     * @throws \RuntimeException ファイル読み書き・復号・改ざん検知時
     */
    public function decryptFile(string $encryptedPath, string $iv): string
    {
        $cipherData = file_get_contents($encryptedPath);

        if ($cipherData === false) {
            throw new \RuntimeException("ファイルが読み取れません: {$encryptedPath}");
        }

        if (strpos($iv, ':') !== false) {
            // 新フォーマット（AES-256-GCM）
            [$ivHex, $tagHex] = explode(':', $iv, 2);
            $ivBytes  = hex2bin($ivHex);
            $tagBytes = hex2bin($tagHex);

            if ($ivBytes === false || $tagBytes === false
                || strlen($ivBytes) !== self::GCM_IV_LENGTH
                || strlen($tagBytes) !== self::GCM_TAG_LENGTH) {
                throw new \RuntimeException('IV のフォーマットが不正です。');
            }

            $decrypted = openssl_decrypt($cipherData, self::CIPHER_GCM, $this->key, OPENSSL_RAW_DATA, $ivBytes, $tagBytes);
        } else {
            // 旧フォーマット（AES-256-CBC・後方互換）
            $ivBytes = hex2bin($iv);
            if ($ivBytes === false || strlen($ivBytes) !== self::CBC_IV_LENGTH) {
                throw new \RuntimeException('IV のフォーマットが不正です。');
            }
            $decrypted = openssl_decrypt($cipherData, self::CIPHER_CBC, $this->key, OPENSSL_RAW_DATA, $ivBytes);
        }

        if ($decrypted === false) {
            throw new \RuntimeException('ファイルの復号に失敗しました。');
        }

        $tmpPath = sys_get_temp_dir() . '/' . bin2hex(random_bytes(16));

        if (file_put_contents($tmpPath, $decrypted) === false) {
            throw new \RuntimeException("一時ファイルの書き込みに失敗しました: {$tmpPath}");
        }

        return $tmpPath;
    }

    /**
     * 暗号化キーを生成する（初期設定・キーローテーション用）
     *
     * @return string 64文字の hex 文字列（256ビット）
     */
    public static function generateKey(): string
    {
        return bin2hex(random_bytes(32));
    }
}
