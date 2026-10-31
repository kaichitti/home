<?php

namespace FuryoDacho\Helpers;

/**
 * ログイン試行制限（ブルートフォース対策 + アカウントロックDoS対策）
 *
 * login_attempts テーブルに「失敗」と「成功」を記録し、次の観点で判定する。
 *
 *  1. IP 単位
 *     同一IPからの失敗（照合せず拒否した試行 success=2 を含む）が IP_WINDOW_MIN 分間に
 *     IP_MAX_FAILURES 回に達したら、そのIPを一時拒否。
 *     （1つのIPから多数のアカウントを狙うパスワードスプレー・総当たり対策）
 *
 *  2. アカウント × IP 単位
 *     同一IPから同一アカウントへの失敗が PAIR_WINDOW_MIN 分間に PAIR_MAX_FAILURES 回に達したら
 *     その組合せのみ拒否。攻撃者が自分のIPから失敗を重ねても、他のIPは巻き込まない。
 *
 *  3. アカウント単位（分散攻撃への備え）
 *     アカウントへの失敗が一定数に達したらロックする（判定は呼び出し側）。ただし
 *     「過去にそのアカウントでログイン成功したことのあるIP（信頼済みIP）」からの試行は
 *     ロックの対象外とする。第三者が故意に失敗を重ねて正規ユーザーを締め出す
 *     「アカウントロックDoS」を緩和しつつ、未知のIPからの総当たりは引き続き遮断する。
 *
 * 【並行リクエスト対策（予約方式）】
 * 「判定してから照合し、失敗したら記録する」順序だと、同時に大量のリクエストを送ると
 * 記録前に全リクエストが判定を通過してしまう。そこで照合の前に reserve() で失敗行を
 * 先に記録し、その行を含めて件数を数える。どの順序で並行実行されても、上限を超えて
 * 照合まで進めるリクエストは生じない。成功時は recordSuccess() で予約を取り消す。
 *
 * 【識別子】
 * - アカウント: 呼び出し側でDBの正規の識別子（ユーザーID等）から作ったキーを渡すこと。
 *   入力文字列のままだと、照合順序（utf8mb4_unicode_ci）上は同一とみなされる表記ゆれ
 *   （大文字・全角・アクセント・ゼロ幅文字など）で別キー扱いになり制限を回避される。
 *   キーは SHA-256 で保存し、メールアドレス等の平文は残さない。
 * - IP: IPv6 は /64 単位にまとめる（1契約者が広大なアドレス空間を持つため）。
 *
 * テーブルが利用できない場合は可用性を優先して制限を行わない（テナント側は
 * users テーブルのアカウントロックで最低限の保護が維持される）。
 */
class LoginThrottle
{
    /** IP単位: 15分間に30回失敗で、そのIPからの試行を拒否 */
    public const IP_MAX_FAILURES = 30;
    public const IP_WINDOW_MIN   = 15;

    /** アカウント×IP単位: 30分間に5回失敗で、その組合せを拒否 */
    public const PAIR_MAX_FAILURES = 5;
    public const PAIR_WINDOW_MIN   = 30;

    /** アカウント単位: 30分間に5回失敗でロック（信頼済みIPは除外） */
    public const ACCOUNT_MAX_FAILURES = 5;
    public const ACCOUNT_WINDOW_MIN   = 30;

    /** 信頼済みIPとみなす期間（最後のログイン成功からの日数） */
    public const TRUSTED_IP_DAYS = 30;

    private \PDO $pdo;

    public function __construct(\PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    /**
     * アカウント識別キーを生成する（例: tenant|uid:12, admin|id:1）
     */
    public static function accountKey(string $scope, string ...$parts): string
    {
        $normalized = array_map(
            static fn (string $p): string => mb_strtolower(trim($p)),
            $parts
        );
        return $scope . '|' . implode('|', $normalized);
    }

    /**
     * IPを制限用の単位にまとめる（IPv4 はそのまま、IPv6 は /64）
     */
    public static function bucket(string $ip): string
    {
        $bin = @inet_pton($ip);
        if ($bin === false) {
            return $ip;
        }
        if (strlen($bin) === 16) {
            // IPv4 射影アドレス（::ffff:a.b.c.d）は IPv4 として扱う
            if (substr($bin, 0, 12) === str_repeat("\0", 10) . "\xff\xff") {
                return (string)inet_ntop(substr($bin, 12));
            }
            return inet_ntop(substr($bin, 0, 8) . str_repeat("\0", 8)) . '/64';
        }
        return (string)inet_ntop($bin);
    }

    /**
     * 照合前に試行を予約する（失敗行を先に記録し、それを含めて上限を判定）
     *
     * @return int|null 予約した行ID（成功時は recordSuccess で取り消される）。
     *                  IP単位・組合せ単位の上限に達していれば null（拒否）。IP単位で拒否した
     *                  予約は取り消し、組合せ単位で拒否した予約は success=2 として残す
     *                  （IP単位の制限にのみ数える）。
     *                  記録先が利用できない場合は 0（制限なしで続行）。
     */
    public function reserve(string $accountKey, string $ip): ?int
    {
        try {
            return $this->withTable(function () use ($accountKey, $ip): ?int {
                $bucket = self::bucket($ip);
                $hash   = self::hashKey($accountKey);

                $ins = $this->pdo->prepare(
                    "INSERT INTO `login_attempts` (`ip`, `account_hash`, `success`) VALUES (?, ?, 0)"
                );
                $ins->execute([$bucket, $hash]);
                $id = (int)$this->pdo->lastInsertId();

                // IP単位（自分の予約を含めて上限を超えたら拒否）。
                // ロック中のため照合せず拒否した試行（success=2）もIP単位では数える
                // （数えないと、存在するアカウントかどうかでIP単位の消費量が変わり推測に使われ得る）
                $stmt = $this->pdo->prepare(
                    "SELECT COUNT(*) FROM `login_attempts`
                     WHERE `ip` = ? AND `success` IN (0, 2)
                       AND `created_at` >= DATE_SUB(NOW(), INTERVAL ? MINUTE)"
                );
                $stmt->execute([$bucket, self::IP_WINDOW_MIN]);
                $ipBlocked = (int)$stmt->fetchColumn() > self::IP_MAX_FAILURES;

                if ($ipBlocked) {
                    // IP単位で拒否した試行は記録を残さない（拒否中の再試行で期間を延長しない）
                    $this->release($id);
                    $this->maybePurge();
                    return null;
                }

                // アカウント×IP単位
                $stmt = $this->pdo->prepare(
                    "SELECT COUNT(*) FROM `login_attempts`
                     WHERE `account_hash` = ? AND `ip` = ? AND `success` = 0
                       AND `created_at` >= DATE_SUB(NOW(), INTERVAL ? MINUTE)"
                );
                $stmt->execute([$hash, $bucket, self::PAIR_WINDOW_MIN]);
                if ((int)$stmt->fetchColumn() > self::PAIR_MAX_FAILURES) {
                    // 組合せ単位で拒否した試行は、照合せず拒否した試行（success=2）として残す。
                    // 組合せ単位の制限は延長しないが、IP単位の制限には数える
                    // （IP単位の判定を通過した試行は、アカウントの有無・状態に関係なく
                    //   同じだけIP単位の枠を消費する＝アカウントの存在を推測されない）
                    $this->markRefused($id);
                    $this->maybePurge();
                    return null;
                }

                $this->maybePurge();
                return $id;
            });
        } catch (\Throwable $e) {
            error_log('LoginThrottle::reserve failed: ' . $e->getMessage());
            return 0;
        }
    }

    /**
     * 照合せずに拒否した試行（アカウントのロック中、またはアカウント×IP単位の制限）として
     * 記録し直す（success=2）。IP単位の制限には引き続き数えるが、アカウント×IP単位の制限と
     * システム管理者のアカウントロック（直近30分の失敗数）には数えない
     * （拒否中の再試行でそれらの期間を延ばさない）。
     */
    public function markRefused(int $id): void
    {
        if ($id <= 0) {
            return;
        }
        try {
            $this->pdo->prepare(
                "UPDATE `login_attempts` SET `success` = 2 WHERE `id` = ? AND `success` = 0"
            )->execute([$id]);
        } catch (\Throwable $e) {
            // 記録変更の失敗は無視（安全側＝失敗として数えられるだけ）
        }
    }

    /**
     * 予約を取り消す
     */
    public function release(int $id): void
    {
        if ($id <= 0) {
            return;
        }
        try {
            $this->pdo->prepare("DELETE FROM `login_attempts` WHERE `id` = ?")->execute([$id]);
        } catch (\Throwable $e) {
            // 取り消し失敗は無視（期間経過で自然に失効する）
        }
    }

    /**
     * アカウント単位の失敗回数がロック基準に達しているか
     * （システム管理者のようにユーザーテーブル側にロック列が無いアカウント用）
     *
     * @param int $excludeId 今回の試行の予約ID（自分自身は数えない）
     */
    public function isAccountLocked(string $accountKey, int $excludeId = 0): bool
    {
        try {
            return $this->withTable(function () use ($accountKey, $excludeId): bool {
                $stmt = $this->pdo->prepare(
                    "SELECT COUNT(*) FROM `login_attempts`
                     WHERE `account_hash` = ? AND `success` = 0 AND `id` <> ?
                       AND `created_at` >= DATE_SUB(NOW(), INTERVAL ? MINUTE)"
                );
                $stmt->execute([self::hashKey($accountKey), $excludeId, self::ACCOUNT_WINDOW_MIN]);
                return (int)$stmt->fetchColumn() >= self::ACCOUNT_MAX_FAILURES;
            });
        } catch (\Throwable $e) {
            return false;
        }
    }

    /**
     * このIPが、このアカウントで過去にログイン成功したことのある「信頼済みIP」か
     */
    public function isTrustedIp(string $accountKey, string $ip): bool
    {
        try {
            return $this->withTable(function () use ($accountKey, $ip): bool {
                $stmt = $this->pdo->prepare(
                    "SELECT 1 FROM `login_attempts`
                     WHERE `account_hash` = ? AND `ip` = ? AND `success` = 1
                       AND `created_at` >= DATE_SUB(NOW(), INTERVAL ? DAY)
                     LIMIT 1"
                );
                $stmt->execute([self::hashKey($accountKey), self::bucket($ip), self::TRUSTED_IP_DAYS]);
                return $stmt->fetchColumn() !== false;
            });
        } catch (\Throwable $e) {
            return false;
        }
    }

    /**
     * ログイン成功を記録する
     * - この組合せの失敗記録（今回の予約を含む）を消去
     * - このIPを信頼済みIPとして記録（組合せごとに最新1件のみ保持）
     */
    /**
     * 指定アカウントのログイン失敗記録を消去する（管理者によるロック解除・パスワード再設定時）
     * 信頼済みIP（成功記録）は残す。
     */
    public function clearFailures(string $accountKey): void
    {
        try {
            $this->withTable(function () use ($accountKey): void {
                $this->pdo->prepare("DELETE FROM `login_attempts` WHERE `account_hash` = ? AND `success` <> 1")
                    ->execute([self::hashKey($accountKey)]);
            });
        } catch (\Throwable $e) {
            error_log('[furyo-dacho] login attempts clear failed: ' . $e->getMessage());
        }
    }

    public function recordSuccess(string $accountKey, string $ip): void
    {
        try {
            $this->withTable(function () use ($accountKey, $ip): void {
                $hash   = self::hashKey($accountKey);
                $bucket = self::bucket($ip);
                $this->pdo->prepare(
                    "DELETE FROM `login_attempts` WHERE `account_hash` = ? AND `ip` = ?"
                )->execute([$hash, $bucket]);
                $this->pdo->prepare(
                    "INSERT INTO `login_attempts` (`ip`, `account_hash`, `success`) VALUES (?, ?, 1)"
                )->execute([$bucket, $hash]);
            });
        } catch (\Throwable $e) {
            // 記録失敗はログイン処理を妨げない
        }
    }

    // ----------------------------------------------------------------

    private static function hashKey(string $accountKey): string
    {
        return hash('sha256', $accountKey);
    }

    /**
     * 古い記録を間引く（失敗: 1日、成功: 信頼期間を超えたもの）
     * 毎回実行すると負荷になるため、およそ20回に1回だけ実行する。
     */
    private function maybePurge(): void
    {
        if (random_int(1, 20) !== 1) {
            return;
        }
        try {
            $this->pdo->prepare(
                "DELETE FROM `login_attempts`
                 WHERE (`success` IN (0, 2) AND `created_at` < DATE_SUB(NOW(), INTERVAL 1 DAY))
                    OR (`success` = 1 AND `created_at` < DATE_SUB(NOW(), INTERVAL ? DAY))"
            )->execute([self::TRUSTED_IP_DAYS]);
        } catch (\Throwable $e) {
            // 間引き失敗は無視
        }
    }

    /**
     * テーブル未作成環境（マイグレーション未実行）では自動作成して再実行する
     *
     * @template T
     * @param callable(): T $fn
     * @return T
     */
    private function withTable(callable $fn)
    {
        try {
            return $fn();
        } catch (\PDOException $e) {
            if (($e->errorInfo[0] ?? '') === '42S02' || strpos($e->getMessage(), '1146') !== false) {
                $this->pdo->exec(self::createTableSql());
                return $fn();
            }
            throw $e;
        }
    }

    /**
     * login_attempts テーブルの定義（schema.sql / migrate.php と同一）
     */
    public static function createTableSql(): string
    {
        return "CREATE TABLE IF NOT EXISTS `login_attempts` (
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
          COMMENT='ログイン試行履歴（ブルートフォース・アカウントロックDoS対策）'";
    }
}
