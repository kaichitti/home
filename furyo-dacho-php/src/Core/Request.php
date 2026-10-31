<?php

namespace FuryoDacho\Core;

/**
 * HTTPリクエストラッパー
 * XSS対策のため、取得値はすべてhtmlspecialcharsでサニタイズする
 */
class Request
{
    /**
     * GETパラメータを取得
     */
    public function get(string $key, $default = null)
    {
        if (!isset($_GET[$key])) {
            return $default;
        }
        return $this->sanitize($_GET[$key]);
    }

    /**
     * POSTパラメータを取得
     */
    public function post(string $key, $default = null)
    {
        if (!isset($_POST[$key])) {
            return $default;
        }
        return $this->sanitize($_POST[$key]);
    }

    /**
     * POST全体を取得（バリデーション前処理用）
     */
    public function all(): array
    {
        return array_map([$this, 'sanitize'], $_POST);
    }

    /**
     * アップロードされたファイルを取得
     */
    public function file(string $key): ?array
    {
        return $_FILES[$key] ?? null;
    }

    /**
     * HTTPメソッドを取得
     */
    public function method(): string
    {
        return strtoupper($_SERVER['REQUEST_METHOD'] ?? 'GET');
    }

    /**
     * POSTリクエストかチェック
     */
    public function isPost(): bool
    {
        return $this->method() === 'POST';
    }

    /**
     * クライアントIPアドレスを取得
     *
     * 既定では REMOTE_ADDR のみを信頼する。X-Forwarded-For は信頼できる
     * リバースプロキシ配下で TRUST_PROXY=true を設定した場合のみ、偽装できない
     * 右端（自前プロキシが追記した値）から解決する（詳細は ClientIp）。
     */
    public function ip(): string
    {
        return \FuryoDacho\Helpers\ClientIp::resolve();
    }

    /**
     * ページ名を取得（ルーティング用）
     */
    public function page(): string
    {
        $page = $this->get('page', 'dashboard');
        // ?page[]=x のように配列が渡されると戻り値型(string)違反の TypeError で
        // 500 エラーになっていたため、文字列以外は存在しないページとして扱う
        return is_string($page) ? $page : '';
    }

    /**
     * 値をサニタイズ
     *
     * 注意: ここで htmlspecialchars は行わない。
     * 以前は入力時にHTMLエンコードしてDBへ保存していたため、
     * ビュー側の htmlspecialchars と合わさって二重エスケープが発生し、
     * 「&」を含む品名などが「&amp;amp;」として表示・CSV出力される不具合があった。
     * XSS対策は出力時（ビュー/エクスポート）のエスケープで行う。
     * ここでは trim と NULバイト・制御文字の除去のみ行う。
     */
    private function sanitize($value)
    {
        if (is_array($value)) {
            return array_map([$this, 'sanitize'], $value);
        }
        if (is_string($value)) {
            // NULバイトと改行・タブ以外の制御文字を除去
            $value = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', '', $value) ?? $value;
            return trim($value);
        }
        return $value;
    }
}
