<?php
/**
 * success.php
 *
 * Stripe Checkout の success_url で呼び出される。
 *   t=<success_token>&session_id=<cs_...>
 *
 *   1. success_token で payments を検索
 *   2. Webhook がすでに paid にしていればそれを採用
 *   3. まだ pending の場合は Stripe API で Session を直接照会し、
 *      payment_status=paid を確認できれば paid に昇格
 *   4. 有効期限内なら「秘密のURL」へリダイレクト
 *      初回到達時は status=redeemed, redeemed_at=now() を記録
 */

declare(strict_types=1);

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/lib/db.php';
require_once __DIR__ . '/lib/stripe.php';

$token     = (string)($_GET['t'] ?? '');
$sessionId = (string)($_GET['session_id'] ?? '');

if (!preg_match('/^[a-f0-9]{64}$/', $token)) {
    http_response_code(400);
    exit('トークンが不正です。');
}

$pdo = pgw_db();
$stmt = $pdo->prepare('SELECT * FROM payments WHERE success_token = :t LIMIT 1');
$stmt->execute([':t' => $token]);
$payment = $stmt->fetch();

if (!$payment) {
    http_response_code(404);
    exit('該当する支払い情報が見つかりません。');
}

// 有効期限チェック（expires_at は UTC 文字列）。
if (!empty($payment['expires_at']) && strtotime((string)$payment['expires_at'] . ' UTC') < time()) {
    http_response_code(410);
    exit('このリンクの有効期限は切れています。お手数ですが、もう一度決済をお試しください。');
}

// Webhook 未着でも自力確認できるよう、pending のときは Stripe に問い合わせる。
if ($payment['status'] === 'pending') {
    try {
        $cfg    = pgw_config();
        $client = new PgwStripeClient((string)$cfg['stripe_secret_key']);
        $sid    = $sessionId !== '' ? $sessionId : (string)$payment['stripe_session_id'];
        $session = $client->retrieveCheckoutSession($sid);

        if (($session['payment_status'] ?? '') === 'paid') {
            $email = $session['customer_details']['email'] ?? ($session['customer_email'] ?? null);
            $up = $pdo->prepare("
                UPDATE payments
                   SET status='paid', paid_at=CURRENT_TIMESTAMP, customer_email=COALESCE(:email, customer_email)
                 WHERE id=:id AND status='pending'
            ");
            $up->execute([':id' => (int)$payment['id'], ':email' => $email]);
            $payment['status'] = 'paid';
        }
    } catch (Throwable $e) {
        error_log('[pgw success] ' . $e->getMessage());
        // 通信失敗時は下の分岐で「処理中」を表示する。
    }
}

if ($payment['status'] === 'paid' || $payment['status'] === 'redeemed') {
    // まだ redeem されていなければ印をつける（redirect は常に行う）。
    if ($payment['status'] === 'paid') {
        $pdo->prepare("UPDATE payments SET status='redeemed', redeemed_at=CURRENT_TIMESTAMP WHERE id=:id AND status='paid'")
            ->execute([':id' => (int)$payment['id']]);
    }

    // link_id から target_url を取得してリダイレクト。
    $q = $pdo->prepare('SELECT target_url FROM links WHERE id = :id LIMIT 1');
    $q->execute([':id' => (int)$payment['link_id']]);
    $target = (string)($q->fetchColumn() ?: '');
    if ($target === '') {
        http_response_code(500);
        exit('リダイレクト先が未設定です。管理者にお問い合わせください。');
    }
    pgw_redirect($target, 302);
}

// pending のまま: Webhook 到着待ちの可能性あり。軽くポーリングを促す。
http_response_code(202);
?><!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="3">
  <title>決済処理中</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif; text-align: center; padding: 4rem 1rem; color: #333; }
    .spinner { width: 32px; height: 32px; border: 3px solid #ddd; border-top-color: #2a63d0; border-radius: 50%; animation: sp 1s linear infinite; margin: 0 auto 1rem; }
    @keyframes sp { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="spinner" aria-hidden="true"></div>
  <h1>決済処理中です…</h1>
  <p>自動的に画面を更新します。しばらくお待ちください。</p>
  <p><small>このページが更新されない場合は <a href="">ここをクリック</a> してください。</small></p>
</body>
</html>
