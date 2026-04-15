<?php
/**
 * checkout.php
 *
 * 公開エンドポイント。URL 例: /checkout.php?slug=premium-pdf
 *
 *   1. slug で active なリンクを検索
 *   2. Stripe Checkout Session を作成
 *   3. 内部トークンと共に payments テーブルへレコードを記録
 *   4. Stripe 決済画面へリダイレクト
 */

declare(strict_types=1);

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/lib/db.php';
require_once __DIR__ . '/lib/stripe.php';

$slug = trim((string)($_GET['slug'] ?? ''));
if ($slug === '' || !preg_match('/^[A-Za-z0-9_\-]{3,64}$/', $slug)) {
    http_response_code(400);
    exit('不正なリンクです。');
}

$link = pgw_find_active_link($slug);
if (!$link) {
    http_response_code(404);
    exit('このリンクは無効か存在しません。');
}

$cfg    = pgw_config();
$base   = pgw_base_url();

try {
    $client = new PgwStripeClient((string)$cfg['stripe_secret_key']);

    // 成功URLに埋め込むトークン。webhook や success.php で照合する。
    $successToken = bin2hex(random_bytes(32));

    // Stripe 側に変数 {CHECKOUT_SESSION_ID} を展開してもらう。
    $successUrl = $base . '/success.php?t=' . $successToken . '&session_id={CHECKOUT_SESSION_ID}';
    $cancelUrl  = $base . '/checkout.php?slug=' . rawurlencode($slug) . '&cancelled=1';

    $session = $client->createCheckoutSession([
        'mode' => 'payment',
        'payment_method_types' => ['card'],
        'line_items' => [
            [
                'price_data' => [
                    'currency'     => (string)$link['currency'],
                    'unit_amount'  => (int)$link['price'],
                    'product_data' => [
                        'name' => (string)$link['name'],
                    ],
                ],
                'quantity' => 1,
            ],
        ],
        'success_url'         => $successUrl,
        'cancel_url'          => $cancelUrl,
        // 内部照合用 ID。webhook に含まれて返る。
        'client_reference_id' => $successToken,
        'metadata' => [
            'link_id'       => (string)$link['id'],
            'link_slug'     => (string)$link['slug'],
            'success_token' => $successToken,
        ],
    ]);

    if (empty($session['id']) || empty($session['url'])) {
        throw new RuntimeException('Stripe Session のレスポンスが不正です。');
    }

    $expiresAt = gmdate('Y-m-d H:i:s', time() + (int)$cfg['success_token_ttl']);

    $stmt = pgw_db()->prepare("
        INSERT INTO payments (link_id, stripe_session_id, success_token, status, amount, currency, expires_at)
        VALUES (:link_id, :sid, :tok, 'pending', :amount, :currency, :exp)
    ");
    $stmt->execute([
        ':link_id'  => (int)$link['id'],
        ':sid'      => (string)$session['id'],
        ':tok'      => $successToken,
        ':amount'   => (int)$link['price'],
        ':currency' => (string)$link['currency'],
        ':exp'      => $expiresAt,
    ]);

    pgw_redirect((string)$session['url'], 303);

} catch (Throwable $e) {
    http_response_code(500);
    // 内部エラーの詳細はエンドユーザーに晒さない。
    error_log('[pgw checkout] ' . $e->getMessage());
    echo '決済画面の準備に失敗しました。しばらくしてから再度お試しください。';
}
