<?php
/**
 * lib/stripe.php
 *
 * Composer を使わない最小限の Stripe API クライアント。
 * 必要最低限の機能のみを実装する:
 *   - Checkout Session の作成 / 取得
 *   - Webhook 署名の検証 (HMAC-SHA256, v1 スキーム)
 *
 * Stripe API 仕様は form-urlencoded の深いネスト（key[sub][idx]）を要求するため、
 * 独自にエンコーダを実装している。
 */

declare(strict_types=1);

/**
 * Stripe API 由来の例外。
 */
class PgwStripeException extends RuntimeException {}

final class PgwStripeClient
{
    private string $secretKey;
    private string $apiBase = 'https://api.stripe.com/v1';
    // 安定版 API バージョンを固定する（Stripe 側の将来的な破壊的変更を防ぐ）。
    private string $apiVersion = '2024-06-20';

    public function __construct(string $secretKey)
    {
        if ($secretKey === '' || !str_starts_with($secretKey, 'sk_')) {
            throw new PgwStripeException('Stripe の Secret Key が未設定または不正です。');
        }
        $this->secretKey = $secretKey;
    }

    /**
     * Checkout Session を作成する。
     *
     * @param array<string,mixed> $params Stripe API 形式のパラメータ
     * @return array<string,mixed>        レスポンスJSONをデコードした連想配列
     */
    public function createCheckoutSession(array $params): array
    {
        return $this->request('POST', '/checkout/sessions', $params);
    }

    /**
     * Checkout Session を取得する。
     */
    public function retrieveCheckoutSession(string $sessionId): array
    {
        return $this->request('GET', '/checkout/sessions/' . rawurlencode($sessionId));
    }

    /**
     * Webhook ペイロードの署名を検証し、イベント本体を返す。
     *
     * @param string $payload   リクエスト生ボディ
     * @param string $sigHeader Stripe-Signature ヘッダ値
     * @param string $secret    Webhook Signing Secret (whsec_...)
     * @param int    $tolerance タイムスタンプ許容差（秒）
     * @return array<string,mixed> イベント本体
     */
    public function verifyWebhook(string $payload, string $sigHeader, string $secret, int $tolerance = 300): array
    {
        $timestamp = null;
        $signatures = [];
        foreach (explode(',', $sigHeader) as $part) {
            $kv = explode('=', trim($part), 2);
            if (count($kv) !== 2) continue;
            [$k, $v] = $kv;
            if ($k === 't')       $timestamp = $v;
            elseif ($k === 'v1')  $signatures[] = $v;
        }
        if ($timestamp === null || $signatures === []) {
            throw new PgwStripeException('Stripe-Signature ヘッダが不正です。');
        }
        if (abs(time() - (int)$timestamp) > $tolerance) {
            throw new PgwStripeException('Webhook タイムスタンプが許容範囲外です。');
        }

        $signedPayload = $timestamp . '.' . $payload;
        $expected = hash_hmac('sha256', $signedPayload, $secret);
        foreach ($signatures as $sig) {
            if (hash_equals($expected, $sig)) {
                $data = json_decode($payload, true);
                if (!is_array($data)) {
                    throw new PgwStripeException('Webhook ペイロードのJSONが不正です。');
                }
                return $data;
            }
        }
        throw new PgwStripeException('Webhook 署名が一致しません。');
    }

    // ---------------------------------------------------------------------
    // 以下、内部実装
    // ---------------------------------------------------------------------

    /**
     * @param array<string,mixed> $params
     * @return array<string,mixed>
     */
    private function request(string $method, string $path, array $params = []): array
    {
        $url  = $this->apiBase . $path;
        $body = self::encode($params);

        $headers = [
            'Authorization: Bearer ' . $this->secretKey,
            'Stripe-Version: ' . $this->apiVersion,
            'Accept: application/json',
        ];

        if ($method === 'GET') {
            if ($body !== '') {
                $url .= '?' . $body;
            }
            $responseBody = $this->httpSend($method, $url, $headers, null);
        } else {
            $headers[] = 'Content-Type: application/x-www-form-urlencoded';
            $responseBody = $this->httpSend($method, $url, $headers, $body);
        }

        $decoded = json_decode($responseBody['body'], true);
        if (!is_array($decoded)) {
            throw new PgwStripeException('Stripe からの応答をJSONとして解釈できません。');
        }
        if ($responseBody['status'] >= 400) {
            $msg = $decoded['error']['message'] ?? ('Stripe API エラー (HTTP ' . $responseBody['status'] . ')');
            throw new PgwStripeException($msg);
        }
        return $decoded;
    }

    /**
     * HTTP 送信（cURL があれば cURL、なければ stream wrappers）。
     *
     * @param list<string> $headers
     * @return array{status:int, body:string}
     */
    private function httpSend(string $method, string $url, array $headers, ?string $body): array
    {
        if (function_exists('curl_init')) {
            $ch = curl_init();
            curl_setopt_array($ch, [
                CURLOPT_URL            => $url,
                CURLOPT_CUSTOMREQUEST  => $method,
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_HTTPHEADER     => $headers,
                CURLOPT_TIMEOUT        => 30,
                CURLOPT_CONNECTTIMEOUT => 10,
                CURLOPT_SSL_VERIFYPEER => true,
                CURLOPT_SSL_VERIFYHOST => 2,
            ]);
            if ($body !== null) {
                curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
            }
            $resp = curl_exec($ch);
            if ($resp === false) {
                $err = curl_error($ch);
                curl_close($ch);
                throw new PgwStripeException('HTTP通信エラー: ' . $err);
            }
            $status = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
            curl_close($ch);
            return ['status' => $status, 'body' => (string)$resp];
        }

        // フォールバック: allow_url_fopen が有効な環境向け
        $opts = [
            'http' => [
                'method'        => $method,
                'header'        => implode("\r\n", $headers),
                'timeout'       => 30,
                'ignore_errors' => true,
            ],
            'ssl' => [
                'verify_peer'      => true,
                'verify_peer_name' => true,
            ],
        ];
        if ($body !== null) {
            $opts['http']['content'] = $body;
        }
        $ctx = stream_context_create($opts);
        $resp = @file_get_contents($url, false, $ctx);
        if ($resp === false) {
            throw new PgwStripeException('HTTP通信エラー（stream wrappers 使用時）');
        }
        $status = 0;
        foreach (($http_response_header ?? []) as $h) {
            if (preg_match('#^HTTP/\S+\s+(\d+)#', $h, $m)) {
                $status = (int)$m[1];
            }
        }
        return ['status' => $status, 'body' => (string)$resp];
    }

    /**
     * Stripe 形式の form-urlencoded エンコード。
     * ネスト連想配列 -> key[sub]=val, ネスト配列 -> key[0]=val 形式。
     *
     * @param array<string|int,mixed> $params
     */
    public static function encode(array $params, string $prefix = ''): string
    {
        $pairs = [];
        foreach ($params as $k => $v) {
            if ($v === null) continue;
            $key = $prefix === '' ? (string)$k : $prefix . '[' . $k . ']';
            if (is_array($v)) {
                if ($v === []) continue;
                $encoded = self::encode($v, $key);
                if ($encoded !== '') $pairs[] = $encoded;
            } elseif (is_bool($v)) {
                $pairs[] = rawurlencode($key) . '=' . ($v ? 'true' : 'false');
            } else {
                $pairs[] = rawurlencode($key) . '=' . rawurlencode((string)$v);
            }
        }
        return implode('&', $pairs);
    }
}
