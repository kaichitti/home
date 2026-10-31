<?php

namespace FuryoDacho\Models;

use PDOException;
use RuntimeException;

/**
 * モデル基底クラス
 * PDO接続をシングルトンで保持し、全モデルに共通する処理を提供する。
 */
abstract class BaseModel
{
    protected \PDO $pdo;

    /** @var string テーブル名（サブクラスで上書き） */
    protected string $table = '';

    public function __construct(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    /**
     * PDO接続をシングルトンで取得
     * config/database.php を読み込み、接続を確立する。
     */
    public static function connect(): \PDO
    {
        static $pdo = null;

        if ($pdo !== null) {
            return $pdo;
        }

        $configPath = defined('BASE_PATH')
            ? BASE_PATH . '/config/database.php'
            : __DIR__ . '/../../config/database.php';

        if (!is_file($configPath)) {
            throw new RuntimeException("Database config not found: {$configPath}");
        }

        $config = require $configPath;
        $dsn    = "mysql:host={$config['host']};dbname={$config['dbname']};charset={$config['charset']}";

        try {
            $pdo = new \PDO($dsn, $config['username'], $config['password'], [
                \PDO::ATTR_ERRMODE            => \PDO::ERRMODE_EXCEPTION,
                \PDO::ATTR_DEFAULT_FETCH_MODE => \PDO::FETCH_ASSOC,
                \PDO::ATTR_EMULATE_PREPARES   => false,
            ]);
        } catch (PDOException $e) {
            $source = $config['source'] ?? [];
            $details = sprintf(
                'DB connection failed. config=%s env=%s env_exists=%s host=%s db=%s user=%s app_env=%s',
                $configPath,
                $source['env_path'] ?? dirname($configPath) . '/.env',
                !empty($source['env_exists']) ? 'yes' : 'no',
                $config['host'] ?? '',
                $config['dbname'] ?? '',
                $config['username'] ?? '',
                $source['app_env'] ?? ''
            );
            throw new RuntimeException($details . ' / ' . $e->getMessage(), 0, $e);
        }

        // DBセッションのタイムゾーンをアプリ（Asia/Tokyo = +09:00）に揃える。
        // 以前は未設定だったため、DBサーバーが UTC 等の環境では NOW() や
        // created_at の既定値がPHP側（日本時間）と9時間ずれ、アカウントロックの
        // 期限判定が即「期限切れ」扱いになる・登録日時がずれる等の不具合があった。
        // （schema.sql も SET time_zone = '+09:00' を前提にしている）
        try {
            $pdo->exec("SET time_zone = '+09:00'");
        } catch (PDOException $e) {
            // 設定できない環境でも接続自体は継続する
        }

        return $pdo;
    }
}
