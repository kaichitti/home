<?php

namespace FuryoDacho\Core;

/**
 * HTTPレスポンスヘルパー
 */
class Response
{
    /**
     * 指定URLへリダイレクト
     */
    public function redirect(string $url): void
    {
        header('Location: ' . $url);
        exit;
    }

    /**
     * ステータスコードを設定
     */
    public function status(int $code): self
    {
        http_response_code($code);
        return $this;
    }

    /**
     * JSONレスポンスを返して終了
     */
    public function json($data, int $status = 200): void
    {
        http_response_code($status);
        header('Content-Type: application/json; charset=UTF-8');
        echo json_encode($data, JSON_UNESCAPED_UNICODE);
        exit;
    }

    /**
     * テキストレスポンスを返して終了
     */
    public function text(string $text, int $status = 200): void
    {
        http_response_code($status);
        header('Content-Type: text/plain; charset=UTF-8');
        echo $text;
        exit;
    }

    /**
     * ファイルダウンロードレスポンス
     */
    public function download(string $filePath, string $fileName, string $mimeType = 'application/octet-stream'): void
    {
        if (!file_exists($filePath)) {
            $this->status(404)->text('File not found');
        }

        header('Content-Type: ' . $mimeType);
        header('Content-Disposition: attachment; filename="' . rawurlencode($fileName) . '"');
        header('Content-Length: ' . filesize($filePath));
        header('Cache-Control: no-cache, no-store, must-revalidate');
        readfile($filePath);
        exit;
    }

    /**
     * 403 Forbidden
     */
    public function forbidden(string $message = 'アクセスが拒否されました。'): void
    {
        $this->errorPage(403, 'アクセスできません', $message);
    }

    /**
     * アプリ本体のデザインに合わせたエラー画面を表示する
     * （以前はプレーンテキストがそのまま表示されていた）
     */
    public function errorPage(int $status, string $title, string $message): void
    {
        http_response_code($status);
        header('Content-Type: text/html; charset=UTF-8');

        $h = static fn (string $v): string => htmlspecialchars($v, ENT_QUOTES, 'UTF-8');

        // システム管理画面（/admin/）のエラーでは、戻り先も管理画面のダッシュボードにする
        // （以前は常にテナント側のダッシュボードへのリンクだった）
        $uri       = (string)($_SERVER['REQUEST_URI'] ?? '');
        $script    = (string)($_SERVER['SCRIPT_NAME'] ?? '');
        $isAdmin   = strpos($uri, '/admin/') === 0 || $uri === '/admin' || strpos($script, '/admin/') !== false;
        $homeUrl   = $isAdmin ? '/admin/index.php?page=dashboard' : '/index.php?page=dashboard';
        $homeLabel = $isAdmin ? '管理画面トップ' : 'ダッシュボード';

        echo '<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>' . $h($title) . ' - 古物台帳管理システム</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, "Segoe UI", "Hiragino Kaku Gothic ProN", Meiryo, sans-serif;
    background: #f4f5f7; color: #333;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 24px;
}
.error-card {
    background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.12);
    max-width: 480px; width: 100%; overflow: hidden;
}
.error-card__header {
    background: #1e3a5f; color: #fff; padding: 14px 20px;
    font-size: .95rem; font-weight: 600;
}
.error-card__body { padding: 28px 24px; text-align: center; }
.error-card__code {
    font-size: 2.6rem; font-weight: 700; color: #1e3a5f; margin-bottom: 4px;
}
.error-card__title { font-size: 1.05rem; font-weight: 600; margin-bottom: 12px; }
.error-card__message {
    font-size: .875rem; color: #666; line-height: 1.7; margin-bottom: 22px;
    white-space: pre-wrap; word-break: break-word;
}
.btn {
    display: inline-block; background: #1e3a5f; color: #fff; text-decoration: none;
    border: none; border-radius: 6px; padding: 10px 24px; font-size: .9rem; cursor: pointer;
}
.btn:hover { background: #2a4e7f; }
.btn-secondary { background: #eef1f5; color: #333; margin-left: 8px; }
@media (max-width: 420px) { .btn { display: block; margin: 8px 0 0 !important; } }
.btn-secondary:hover { background: #dfe4ea; }
</style>
</head>
<body>
<div class="error-card">
    <div class="error-card__header">古物台帳管理システム</div>
    <div class="error-card__body">
        <div class="error-card__code">' . (int)$status . '</div>
        <div class="error-card__title">' . $h($title) . '</div>
        <div class="error-card__message">' . $h($message) . '</div>
        <a href="javascript:history.back()" class="btn">前のページに戻る</a>
        <a href="' . $homeUrl . '" class="btn btn-secondary">' . $homeLabel . '</a>
    </div>
</div>
</body>
</html>';
        exit;
    }

    /**
     * 404 Not Found
     * （以前は status(404) の後に text() のデフォルト200で上書きされ、
     *   本文は404メッセージなのにHTTP 200が返っていた）
     */
    public function notFound(string $message = 'ページが見つかりません。'): void
    {
        $this->errorPage(404, 'ページが見つかりません', $message);
    }
}
