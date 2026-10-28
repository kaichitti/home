<?php

namespace FuryoDacho\Core;

/**
 * 予期しないエラー（未捕捉の例外・致命的エラー）の共通処理
 *
 * 以前は本番設定（display_errors=0）で未捕捉の例外が起きると、真っ白な画面
 * （HTTP 500・本文なし）になり、利用者には何が起きたか分からなかった。
 * DB接続失敗・不正な形式のパラメータ（配列の送信など）による型エラー等でも、
 * アプリと同じデザインのエラー画面（JSON API には JSON）を返し、詳細はエラーログへ記録する。
 */
final class ErrorHandler
{
    private static bool $debug = false;

    public static function register(bool $debug): void
    {
        self::$debug = $debug;
        set_exception_handler([self::class, 'handleException']);
        register_shutdown_function([self::class, 'handleShutdown']);
    }

    public static function handleException(\Throwable $e): void
    {
        error_log('[furyo-dacho] Uncaught ' . get_class($e) . ': ' . $e->getMessage()
            . ' in ' . $e->getFile() . ':' . $e->getLine());

        // 型エラー（?page[]=x のような配列パラメータ等）は利用者側の入力不備として 400 にする
        $isBadRequest = $e instanceof \TypeError || $e instanceof \ValueError;
        $status  = $isBadRequest ? 400 : 500;
        $title   = $isBadRequest ? 'リクエストの形式が正しくありません' : 'システムエラーが発生しました';
        $message = $isBadRequest
            ? '入力内容の形式が正しくありません。ページを再読み込みして、もう一度お試しください。'
            : "処理中に予期しないエラーが発生しました。\nしばらく待ってからもう一度お試しください。解決しない場合は管理者に連絡してください。";
        if (self::$debug) {
            $message .= "\n\n[DEBUG] " . get_class($e) . ': ' . $e->getMessage() . "\n" . $e->getFile() . ':' . $e->getLine();
        }

        self::output($status, $title, $message);
    }

    /**
     * 致命的エラー（メモリ不足・構文エラー等）で処理が止まった場合も、出力前ならエラー画面を返す
     */
    public static function handleShutdown(): void
    {
        $err = error_get_last();
        if ($err === null || !in_array($err['type'], [E_ERROR, E_PARSE, E_CORE_ERROR, E_COMPILE_ERROR], true)) {
            return;
        }
        error_log('[furyo-dacho] Fatal error: ' . $err['message'] . ' in ' . $err['file'] . ':' . $err['line']);
        if (headers_sent()) {
            return;
        }
        $message = "処理中に予期しないエラーが発生しました。\nしばらく待ってからもう一度お試しください。";
        if (self::$debug) {
            $message .= "\n\n[DEBUG] " . $err['message'] . "\n" . $err['file'] . ':' . $err['line'];
        }
        self::output(500, 'システムエラーが発生しました', $message);
    }

    private static function output(int $status, string $title, string $message): void
    {
        // 途中まで出力したバッファ（ビューの描画途中など）は破棄してからエラー画面を出す
        while (ob_get_level() > 0) {
            ob_end_clean();
        }
        if (headers_sent()) {
            echo "\n" . htmlspecialchars($title, ENT_QUOTES, 'UTF-8');
            return;
        }

        $accept = (string)($_SERVER['HTTP_ACCEPT'] ?? '');
        if (strpos($accept, 'application/json') !== false) {
            http_response_code($status);
            header('Content-Type: application/json; charset=UTF-8');
            header('Cache-Control: no-store');
            echo json_encode(['ok' => false, 'code' => 'server', 'error' => $title . '。' . strtok($message, "\n")], JSON_UNESCAPED_UNICODE);
            return;
        }

        (new Response())->errorPage($status, $title, $message);
    }
}
