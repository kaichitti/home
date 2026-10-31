<?php

namespace FuryoDacho\Helpers;

/**
 * セッション単位のレート制限（スライディングウィンドウ）
 *
 * ログイン必須のエンドポイント（会員照会・POS在庫検索など）向けの「ベストエフォート」の
 * 抑止策。機械的な連続照会（スクリプトによる会員番号の総当たり等）の速度を落とすことが目的で、
 * 完全な防止策ではない:
 * - 計数はセッション単位のため、再ログインや複数セッションを使えばリセットされる
 *   （成功したログインは試行制限の対象外。ログイン自体は監査ログに残る）。
 * - 会員一覧・会員編集など、同一テナントの職員に閲覧が認められている画面は対象外。
 */
class RateLimiter
{
    /**
     * リクエストを1回分カウントし、上限内なら true を返す
     *
     * @param string $key       制限の種類（例: 'member.lookup'）
     * @param int    $max       ウィンドウ内の最大リクエスト数
     * @param int    $windowSec ウィンドウの長さ（秒）
     * @return bool true=許可 / false=上限超過
     */
    public static function hit(string $key, int $max, int $windowSec): bool
    {
        if (session_status() !== PHP_SESSION_ACTIVE) {
            return true;
        }

        $now    = time();
        $bucket = $_SESSION['_rate_limit'][$key] ?? [];
        if (!is_array($bucket)) {
            $bucket = [];
        }

        // ウィンドウ外の古い記録を捨てる
        $bucket = array_values(array_filter(
            $bucket,
            static fn ($t): bool => is_int($t) && $t > $now - $windowSec
        ));

        if (count($bucket) >= $max) {
            $_SESSION['_rate_limit'][$key] = $bucket;
            return false;
        }

        $bucket[] = $now;
        $_SESSION['_rate_limit'][$key] = $bucket;
        return true;
    }
}
