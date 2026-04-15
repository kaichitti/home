<?php
/**
 * webhook.php
 *
 * Stripe からの Webhook 受信エンドポイント。
 * Stripe ダッシュボードで下記URLを登録し、checkout.session.completed を購読する:
 *   https://<your-host>/webhook.php
 *
 * 署名検証を行い、対応する payments 行のステータスを paid に更新する。
 *
 * 注意: このファイルは Stripe から POST される公開エンドポイントなので、
 *       .htaccess でアクセス制限をかけないこと。
 */

declare(strict_types=1);

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/lib/db.php';
require_once __DIR__ . '/lib/stripe.php';

// 可能であれば人間にレスポンスを読まれないようヘッダを先に出す。
header('Content-Type: application/json; charset=utf-8');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'method_not_allowed']);
    exit;
}

$payload   = (string)file_get_contents('php://input');
$sigHeader = (string)($_SERVER['HTTP_STRIPE_SIGNATURE'] ?? '');
$cfg       = pgw_config();
$secret    = (string)$cfg['stripe_webhook_secret'];

if ($payload === '' || $sigHeader === '' || $secret === '' || !str_starts_with($secret, 'whsec_')) {
    http_response_code(400);
    echo json_encode(['error' => 'bad_request']);
    exit;
}

try {
    $client = new PgwStripeClient((string)$cfg['stripe_secret_key']);
    $event  = $client->verifyWebhook($payload, $sigHeader, $secret);
} catch (Throwable $e) {
    error_log('[pgw webhook] signature verification failed: ' . $e->getMessage());
    http_response_code(400);
    echo json_encode(['error' => 'invalid_signature']);
    exit;
}

$type = (string)($event['type'] ?? '');

try {
    switch ($type) {
        case 'checkout.session.completed':
        case 'checkout.session.async_payment_succeeded':
            pgw_handle_session_completed($event);
            break;

        case 'checkout.session.async_payment_failed':
        case 'checkout.session.expired':
            pgw_handle_session_failed($event);
            break;

        default:
            // 想定外イベントは ACK のみ返す（Stripe の再送を避けるため）。
            break;
    }
} catch (Throwable $e) {
    error_log('[pgw webhook] handler error: ' . $e->getMessage());
    http_response_code(500);
    echo json_encode(['error' => 'handler_error']);
    exit;
}

echo json_encode(['ok' => true]);


/**
 * checkout.session.completed 等の成功系イベントを処理する。
 *
 * @param array<string,mixed> $event
 */
function pgw_handle_session_completed(array $event): void
{
    $session = $event['data']['object'] ?? null;
    if (!is_array($session) || empty($session['id'])) {
        return;
    }
    $sessionId     = (string)$session['id'];
    $paymentStatus = (string)($session['payment_status'] ?? '');
    // paid / no_payment_required のみ成功扱い。
    if ($paymentStatus !== 'paid' && $paymentStatus !== 'no_payment_required') {
        return;
    }

    $email = $session['customer_details']['email'] ?? ($session['customer_email'] ?? null);

    $pdo = pgw_db();
    $stmt = $pdo->prepare("
        UPDATE payments
           SET status='paid',
               paid_at=CURRENT_TIMESTAMP,
               customer_email=COALESCE(:email, customer_email)
         WHERE stripe_session_id=:sid
           AND status='pending'
    ");
    $stmt->execute([
        ':sid'   => $sessionId,
        ':email' => $email,
    ]);
}

/**
 * 失敗・期限切れイベントを処理する。
 *
 * @param array<string,mixed> $event
 */
function pgw_handle_session_failed(array $event): void
{
    $session = $event['data']['object'] ?? null;
    if (!is_array($session) || empty($session['id'])) {
        return;
    }
    $sid = (string)$session['id'];

    pgw_db()->prepare("UPDATE payments SET status='failed' WHERE stripe_session_id=:sid AND status='pending'")
            ->execute([':sid' => $sid]);
}
