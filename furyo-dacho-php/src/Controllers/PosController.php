<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\Sale;
use FuryoDacho\Models\AuditLog;
use FuryoDacho\Models\Member;
use FuryoDacho\Models\Branch;
use FuryoDacho\Models\PosSchema;
use FuryoDacho\Models\PosSetting;
use FuryoDacho\Models\PosTransaction;
use FuryoDacho\Models\PosClosing;
use FuryoDacho\Helpers\PosCalculator;
use FuryoDacho\Helpers\ReceiptLayout;
use FuryoDacho\Helpers\RateLimiter;
use FuryoDacho\Core\Session;

/**
 * POSレジコントローラー（ログイン必須）
 *
 * 会計の流れ:
 *   在庫検索 → カート（単価×数量・単品値引）→ 小計値引・消費税 → 支払方法・お預り/お釣り
 *   → [会計確定] 端末のレシートプリンタ接続を確認
 *        接続あり : 決済完了 → レシートを印刷
 *        接続なし : 確認ダイアログ →「許可」で決済完了 → レシートを画面に発行（後から印刷可）
 *
 * 会計1回ごとに pos_transactions（レシート番号・支払・税）と明細スナップショットを保存し、
 * 明細ごとに sales（販売記録）を作成して在庫を減らす。取消（管理者）は販売記録を削除して在庫を戻す。
 */
class PosController extends BaseController
{
    private const MAX_LINES = 100;

    // ================================================================
    // 共通ヘルパー
    // ================================================================

    private function setupSchema(): void
    {
        PosSchema::ensure($this->pdo);
    }

    private function json(array $data, int $status = 200): void
    {
        header('Cache-Control: no-store');
        $this->response->json($data, $status);
    }

    private function jsonError(string $message, string $code = 'error', int $status = 400, array $extra = []): void
    {
        $this->json(['ok' => false, 'code' => $code, 'error' => $message] + $extra, $status);
    }

    /**
     * JSON API 用の認証チェック（未ログイン時はログイン画面へのリダイレクトではなく 401 を返す。
     * 画面側はカートを保持したまま再ログインを案内できる）
     */
    private function requireAuthJson(): void
    {
        if (!$this->auth->isLoggedIn()) {
            $this->jsonError('ログインの有効期限が切れました。別のタブで再ログインしてから、もう一度お試しください（カートは保存されています）。', 'session', 401);
        }
        if ($this->auth->mustChangePassword()) {
            $this->jsonError('パスワードの変更が必要です。', 'password', 403);
        }
    }

    private function verifyCsrfJson(): void
    {
        if (!$this->request->isPost()) {
            $this->jsonError('不正なリクエストです。', 'method', 405);
        }
        $token        = (string)($_POST['_csrf_token'] ?? '');
        $sessionToken = (string)($_SESSION['_csrf_token'] ?? '');
        if ($token === '' || $sessionToken === '' || !hash_equals($sessionToken, $token)) {
            $this->jsonError('セッションの有効期限が切れたか、不正なリクエストです。ページを再読み込みしてください（カートは保存されています）。', 'csrf', 403);
        }
    }

    /**
     * 整数として解釈できる値（整数 or 数字のみの文字列）なら int、それ以外は null
     */
    private static function intOrNull($v): ?int
    {
        if (is_int($v)) {
            return $v;
        }
        if (is_string($v) && preg_match('/^[0-9]{1,12}$/', $v)) {
            return (int)$v;
        }
        if (is_float($v) && floor($v) === $v && abs($v) < 1e12) {
            return (int)$v;
        }
        return null;
    }

    private static function normDate($value, string $default): string
    {
        $value = is_string($value) ? trim($value) : '';
        if (preg_match('/^(\d{4})-(\d{2})-(\d{2})$/', $value, $m) && checkdate((int)$m[2], (int)$m[3], (int)$m[1])) {
            return $value;
        }
        return $default;
    }

    /**
     * レジ番号（1〜99）として解釈できれば int、それ以外は null
     */
    private static function registerOrNull($v): ?int
    {
        if (is_int($v) || (is_string($v) && ctype_digit($v))) {
            $n = (int)$v;
            return ($n >= 1 && $n <= 99) ? $n : null;
        }
        return null;
    }

    private function registerFilter(string $key = 'register', bool $post = false): ?int
    {
        return self::registerOrNull($post ? $this->request->post($key, '') : $this->request->get($key, ''));
    }

    private function branchFilter(): ?int
    {
        $b = $this->request->get('branch', '');
        return (is_string($b) && ctype_digit($b) && (int)$b > 0) ? (int)$b : null;
    }

    private function audit(string $action, ?int $targetId, ?array $before, ?array $after): void
    {
        try {
            (new AuditLog($this->pdo))->log(
                $this->auth->getTenantId(), $this->auth->getUserId(), (string)($this->auth->user()['display_name'] ?? ''),
                null, $action, $targetId, $before, $after, $this->request->ip()
            );
        } catch (\Throwable $e) {
            error_log('[furyo-dacho] audit log failed: ' . $e->getMessage());
        }
    }

    /**
     * 印刷用レイアウトを HTML（ブラウザ印刷・画面表示）または JSON（直結プリンタ）で返す
     */
    private function outputPrint(array $layout, string $title): void
    {
        if ((string)$this->request->get('format', '') === 'json') {
            $this->json(['ok' => true, 'title' => $title, 'layout' => $layout]);
        }
        $paper = (string)$this->request->get('w', '80') === '58' ? 58 : 80;
        $this->render('pos/print', [
            'printLayout' => $layout,
            'title'  => $title,
            'paper'  => $paper,
            'embed'  => (string)$this->request->get('embed', '') === '1',
        ]);
    }

    // ================================================================
    // レジ画面
    // ================================================================

    public function index(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $settings = (new PosSetting($this->pdo))->get($tenantId);

        $this->render('pos/index', [
            'settings'   => $settings,
            'posUserKey' => 't' . $tenantId . 'u' . $this->auth->getUserId(),
            'isAdmin'    => $this->auth->isAdmin(),
        ]);
    }

    /**
     * 在庫検索（JSON）
     *   q     : 品名・シリアル番号・台帳番号
     *   exact : 1 = バーコード読取（シリアル番号完全一致・台帳番号のみ）
     */
    public function search(): void
    {
        $this->requireAuthJson();
        \FuryoDacho\Models\LedgerSchema::ensure($this->pdo);

        // 在庫・シリアル番号の機械的な列挙を防ぐ（1分間に120回まで。
        // 画面側は入力ごとに300msの間隔を空けて検索するため通常操作では到達しない）
        if (!RateLimiter::hit('pos.search', 120, 60)) {
            $this->json(['ok' => false, 'items' => [], 'error' => '短時間に検索が集中しています。しばらく待ってから再度お試しください。'], 429);
        }

        $keyword = $this->request->get('q', '');
        $keyword = is_string($keyword) ? mb_substr(trim($keyword), 0, 100) : '';
        $exact   = (string)$this->request->get('exact', '') === '1';

        $items = (new Sale($this->pdo))->searchInStock($this->auth->getTenantId(), $keyword, 30, $exact);

        $this->json([
            'ok'    => true,
            'items' => array_map(static function (array $r): array {
                return [
                    'ledger_id'     => (int)$r['id'],
                    'item_name'     => (string)$r['item_name'],
                    'serial_number' => (string)($r['serial_number'] ?? ''),
                    'remaining'     => (int)$r['remaining'],
                    'purchase_date' => (string)$r['transaction_date'],
                    'pending'       => ($r['approval_status'] ?? '') === 'pending',
                    // 販売予定価格（台帳に登録されていればカートの単価に自動入力する）
                    'sale_price'    => isset($r['sale_price']) && $r['sale_price'] !== null ? (int)$r['sale_price'] : null,
                ];
            }, $items),
        ]);
    }

    // ================================================================
    // 会計確定
    // ================================================================

    /**
     * 会計確定（JSON）
     *
     * POST: _csrf_token, payload（JSON）
     *   payload = {
     *     client_token, items: [{ledger_id, quantity, unit_price, line_discount}],
     *     discount: {type: none|amount|percent, value}, payment: {method, tendered, ref},
     *     member_code, note, receipt_mode: print|unprinted, expected_total
     *   }
     */
    public function checkout(): void
    {
        $this->requireAuthJson();
        $this->verifyCsrfJson();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();
        $user     = $this->auth->user() ?? [];

        $payload = json_decode((string)($_POST['payload'] ?? ''), true);
        if (!is_array($payload)) {
            $this->jsonError('会計データが不正です。ページを再読み込みしてください。');
        }

        // 二重送信防止キー（通信エラー後の再送でも同じ会計が二重に登録されない）
        $token = $payload['client_token'] ?? '';
        if (!is_string($token) || !preg_match('/^[A-Za-z0-9-]{16,64}$/', $token)) {
            $this->jsonError('会計データが不正です（送信キー）。ページを再読み込みしてください。');
        }

        $txModel = new PosTransaction($this->pdo);
        $existing = $txModel->findByToken($tenantId, $token);
        if ($existing !== null) {
            $this->json($this->checkoutResponse($existing, true));
        }

        // ---- 明細 ----
        $items = $payload['items'] ?? null;
        if (!is_array($items) || count($items) === 0) {
            $this->jsonError('カートが空です。');
        }
        if (count($items) > self::MAX_LINES) {
            $this->jsonError('1回の会計で処理できるのは' . self::MAX_LINES . '明細までです。');
        }

        $lines = [];
        foreach (array_values($items) as $i => $item) {
            if (!is_array($item)) {
                $this->jsonError('明細の形式が不正です。');
            }
            $ledgerId = self::intOrNull($item['ledger_id'] ?? null);
            $qty      = self::intOrNull($item['quantity'] ?? null);
            $price    = self::intOrNull($item['unit_price'] ?? null);
            $ldisc    = self::intOrNull($item['line_discount'] ?? 0);
            if ($ledgerId === null || $ledgerId <= 0) {
                $this->jsonError('明細' . ($i + 1) . 'の商品が不正です。');
            }
            if ($qty === null || $qty < 1) {
                $this->jsonError('明細' . ($i + 1) . 'の数量が不正です。');
            }
            if ($price === null) {
                $this->jsonError('明細' . ($i + 1) . 'の単価を入力してください（0円の場合は0）。', 'validation', 400, ['line' => $i]);
            }
            if ($ldisc === null) {
                $this->jsonError('明細' . ($i + 1) . 'の値引額が不正です。', 'validation', 400, ['line' => $i]);
            }
            $lines[] = ['ledger_id' => $ledgerId, 'quantity' => $qty, 'unit_price' => $price, 'line_discount' => $ldisc];
        }

        // ---- その他の入力 ----
        $discountIn = is_array($payload['discount'] ?? null) ? $payload['discount'] : [];
        $dType  = in_array($discountIn['type'] ?? 'none', ['none', 'amount', 'percent'], true) ? $discountIn['type'] : 'none';
        $dValue = self::intOrNull($discountIn['value'] ?? 0);
        if ($dValue === null) {
            $this->jsonError('値引の入力が不正です。');
        }

        $paymentIn = is_array($payload['payment'] ?? null) ? $payload['payment'] : [];
        $method    = is_string($paymentIn['method'] ?? null) ? $paymentIn['method'] : '';
        $tenderedRaw = $paymentIn['tendered'] ?? null;
        $tendered  = ($tenderedRaw === null || $tenderedRaw === '') ? null : self::intOrNull($tenderedRaw);
        if ($tenderedRaw !== null && $tenderedRaw !== '' && $tendered === null) {
            $this->jsonError('お預り金額は数値（円）で入力してください。');
        }
        $paymentRef = is_string($paymentIn['ref'] ?? null) ? trim($paymentIn['ref']) : '';
        $memberCode = is_string($payload['member_code'] ?? null) ? trim($payload['member_code']) : '';
        $note       = is_string($payload['note'] ?? null) ? trim($payload['note']) : '';
        $receiptMode = ($payload['receipt_mode'] ?? '') === 'unprinted' ? 'unprinted' : 'print';
        // レジ番号（端末の「POS設定・プリンタ」で設定。未設定・不正値は記録しない）
        $registerNo  = self::registerOrNull($payload['register_no'] ?? null);
        $expectedTotal = self::intOrNull($payload['expected_total'] ?? null);

        // 制御文字の除去（Request::sanitize と同じ方針）
        foreach (['paymentRef', 'memberCode', 'note'] as $var) {
            $$var = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', '', $$var) ?? '';
        }
        if (mb_strlen($paymentRef) > 100) {
            $this->jsonError('承認番号等は100文字以内で入力してください。');
        }
        if (mb_strlen($memberCode) > 50) {
            $this->jsonError('会員番号は50文字以内で入力してください。');
        }
        if (mb_strlen($note) > 400) {
            $this->jsonError('備考は400文字以内で入力してください。');
        }
        $member = null;
        if ($memberCode !== '') {
            $member = (new Member($this->pdo))->findByCode($tenantId, $memberCode);
            if ($member === null) {
                $this->jsonError('会員番号「' . $memberCode . '」は登録されていません。先に会員管理から登録するか、空欄にしてください。', 'member');
            }
        }

        // ---- 商品（台帳）の存在確認と品名のスナップショット ----
        $ledgerIds = array_values(array_unique(array_column($lines, 'ledger_id')));
        $ph   = implode(',', array_fill(0, count($ledgerIds), '?'));
        $stmt = $this->pdo->prepare(
            "SELECT `id`, `item_name`, `serial_number` FROM `ledgers`
             WHERE `tenant_id` = ? AND `deleted_at` IS NULL AND `id` IN ($ph)"
        );
        $stmt->execute(array_merge([$tenantId], $ledgerIds));
        $ledgers = [];
        foreach ($stmt->fetchAll() as $row) {
            $ledgers[(int)$row['id']] = $row;
        }
        foreach ($ledgerIds as $lid) {
            if (!isset($ledgers[$lid])) {
                $this->jsonError('台帳 #' . $lid . ' の商品が見つかりません（削除された可能性があります）。カートから外してください。', 'stock');
            }
        }

        // ---- 金額計算（サーバー側で再計算し、画面の合計と一致することを確認） ----
        $settings = (new PosSetting($this->pdo))->get($tenantId);
        try {
            $calc = PosCalculator::calculate(
                $lines,
                ['type' => $dType, 'value' => $dValue],
                ['rate' => $settings['tax_rate'], 'mode' => $settings['tax_mode'], 'rounding' => $settings['tax_rounding']]
            );
        } catch (\InvalidArgumentException $e) {
            $this->jsonError($e->getMessage(), 'validation');
        }
        // 画面の合計との一致確認は、お預り金額の検証より先に行う。
        // （以前は後だったため、消費税の設定変更で合計が増えた場合に「ちょうど」で預かった会計では
        //   「お預り金額が足りません」と表示され、本来の「再読み込みしてください」の案内が出なかった）
        if ($expectedTotal === null || $expectedTotal !== $calc['total']) {
            $this->jsonError(
                '画面の合計金額（¥' . number_format((int)$expectedTotal) . '）と計算結果（¥' . number_format($calc['total'])
                . '）が一致しません。消費税の設定が変更された可能性があります。ページを再読み込みしてからやり直してください。',
                'total_mismatch',
                409,
                ['server_total' => $calc['total']]
            );
        }
        try {
            $pay = PosCalculator::payment($method, $calc['total'], $tendered);
        } catch (\InvalidArgumentException $e) {
            $this->jsonError($e->getMessage(), 'validation');
        }

        $requestedQty = [];
        foreach ($lines as $l) {
            $requestedQty[$l['ledger_id']] = ($requestedQty[$l['ledger_id']] ?? 0) + $l['quantity'];
        }

        $storeInfo = json_encode([
            'store_name'     => $settings['store_name'],
            'store_address'  => $settings['store_address'],
            'store_phone'    => $settings['store_phone'],
            'invoice_number' => $settings['invoice_number'],
            'receipt_header' => $settings['receipt_header'],
            'receipt_footer' => $settings['receipt_footer'],
        ], JSON_UNESCAPED_UNICODE);

        $ctx = compact(
            'tenantId', 'userId', 'user', 'token', 'lines', 'ledgers', 'calc', 'pay', 'paymentRef',
            'memberCode', 'member', 'note', 'receiptMode', 'requestedQty', 'storeInfo', 'registerNo'
        );

        // 同時実行でデッドロック・ロック待ちタイムアウトになった場合は少し待って再試行する
        for ($attempt = 1; ; $attempt++) {
            try {
                $txId = $this->runCheckout($ctx);
                break;
            } catch (\DomainException $e) {
                // 在庫不足（他の端末で先に販売された等）
                $this->jsonError($e->getMessage(), 'stock', 409);
            } catch (\PDOException $e) {
                if ($this->pdo->inTransaction()) {
                    $this->pdo->rollBack();
                }
                $sqlCode = (int)($e->errorInfo[1] ?? 0);
                if ($sqlCode === 1062 && strpos($e->getMessage(), 'uq_pos_tx_token') !== false) {
                    // 同じ送信キーの会計が並行して確定済み → その会計を返す
                    $dup = $txModel->findByToken($tenantId, $token);
                    if ($dup !== null) {
                        $this->json($this->checkoutResponse($dup, true));
                    }
                }
                if (in_array($sqlCode, [1213, 1205], true) && $attempt < 3) {
                    usleep(150000 * $attempt);
                    continue;
                }
                error_log('[furyo-dacho] POS checkout failed: ' . $e->getMessage());
                $this->jsonError('会計処理に失敗しました。もう一度お試しください。（決済は完了していません）', 'server', 500);
            } catch (\Throwable $e) {
                if ($this->pdo->inTransaction()) {
                    $this->pdo->rollBack();
                }
                error_log('[furyo-dacho] POS checkout failed: ' . $e->getMessage());
                $this->jsonError('会計処理に失敗しました。もう一度お試しください。（決済は完了していません）', 'server', 500);
            }
        }

        $tx = $txModel->findById($txId, $tenantId);
        $this->json($this->checkoutResponse($tx ?? ['id' => $txId], false));
    }

    /**
     * 会計の登録本体（1トランザクション）
     *
     * @return int 会計ID
     * @throws \DomainException 在庫不足
     */
    private function runCheckout(array $c): int
    {
        $saleModel = new Sale($this->pdo);
        $txModel   = new PosTransaction($this->pdo);

        $this->pdo->beginTransaction();

        // 対象台帳の行をID順にロックしてから最新の残数で検証する（Sale::lockLedgers 参照）。
        // ※ トランザクション開始後、このロックより前に通常の SELECT を実行しないこと
        $locked = $saleModel->lockLedgers(array_keys($c['requestedQty']), $c['tenantId']);
        $ids = array_keys($c['requestedQty']);
        sort($ids);
        foreach ($ids as $lid) {
            $remaining = isset($locked[$lid]) ? $locked[$lid]['quantity'] - $locked[$lid]['sold'] : null;
            if ($remaining === null || $c['requestedQty'][$lid] > $remaining) {
                $this->pdo->rollBack();
                $name = (string)($c['ledgers'][$lid]['item_name'] ?? ('#' . $lid));
                throw new \DomainException(
                    '「' . $name . '」の残在庫（' . max(0, (int)$remaining) . '点）が不足しています（カート内 合計'
                    . $c['requestedQty'][$lid] . '点）。他の会計で販売された可能性があります。数量を確認してください。'
                );
            }
        }

        $now       = date('Y-m-d H:i:s');
        $receiptNo = $txModel->nextReceiptNo($c['tenantId'], substr($now, 0, 10));
        $calc      = $c['calc'];

        $txId = $txModel->insert([
            'tenant_id'       => $c['tenantId'],
            'branch_id'       => !empty($c['user']['branch_id']) ? (int)$c['user']['branch_id'] : null,
            'register_no'     => $c['registerNo'],
            'receipt_no'      => $receiptNo,
            'client_token'    => $c['token'],
            'member_code'     => $c['memberCode'],
            'member_id'       => $c['member'] !== null ? (int)$c['member']['id'] : null,
            'member_name'     => $c['member'] !== null ? (string)$c['member']['name'] : '',
            'item_count'      => $calc['item_count'],
            'subtotal'        => $calc['subtotal'],
            'discount_type'   => $calc['discount_type'],
            'discount_value'  => $calc['discount_value'],
            'discount_amount' => $calc['discount_amount'],
            'tax_mode'        => $calc['tax_mode'],
            'tax_rate'        => $calc['tax_rate'],
            'tax_amount'      => $calc['tax_amount'],
            'total'           => $calc['total'],
            'payment_method'  => $c['pay']['method'],
            'tendered'        => $c['pay']['tendered'],
            'change_amount'   => $c['pay']['change'],
            'payment_ref'     => $c['pay']['method'] === 'cash' ? '' : $c['paymentRef'],
            'note'            => $c['note'],
            'store_info'      => $c['storeInfo'],
            'cashier_name'    => (string)($c['user']['display_name'] ?? ''),
            // プリンタ未接続を「許可」して決済した場合は画面発行（未印刷）として記録する
            'receipt_status'  => $c['receiptMode'] === 'unprinted' ? 'unprinted' : 'pending',
            'created_by'      => $c['userId'],
            'created_at'      => $now,
        ]);

        $saleNote = '[POS] ' . $receiptNo . ($c['note'] !== '' ? ' ' . $c['note'] : '');
        $auditLines = [];
        foreach ($c['lines'] as $i => $l) {
            $ledger = $c['ledgers'][$l['ledger_id']];
            $saleId = $saleModel->create($c['tenantId'], [
                'ledger_id'      => $l['ledger_id'],
                'transaction_id' => $txId,
                'member_code'    => $c['memberCode'],
                'quantity'       => $l['quantity'],
                'sale_amount'    => $calc['lines'][$i]['allocated'],
                'sold_at'        => $now,
                'note'           => mb_substr($saleNote, 0, 512),
                'created_by'     => $c['userId'],
            ]);
            $txModel->insertItem([
                'transaction_id'   => $txId,
                'tenant_id'        => $c['tenantId'],
                'ledger_id'        => $l['ledger_id'],
                'sale_id'          => $saleId,
                'line_no'          => $i + 1,
                'item_name'        => (string)$ledger['item_name'],
                'serial_number'    => (string)($ledger['serial_number'] ?? ''),
                'quantity'         => $l['quantity'],
                'unit_price'       => $l['unit_price'],
                'line_discount'    => $l['line_discount'],
                'amount'           => $calc['lines'][$i]['amount'],
                'allocated_amount' => $calc['lines'][$i]['allocated'],
            ]);
            $auditLines[] = ['ledger_id' => $l['ledger_id'], 'sale_id' => $saleId, 'quantity' => $l['quantity'], 'amount' => $calc['lines'][$i]['allocated']];
        }

        (new AuditLog($this->pdo))->log(
            $c['tenantId'], $c['userId'], (string)($c['user']['display_name'] ?? ''), null, 'create', $txId, null,
            [
                'kind'           => 'pos_transaction',
                'receipt_no'     => $receiptNo,
                'register_no'    => $c['registerNo'],
                'member_code'    => $c['memberCode'] !== '' ? $c['memberCode'] : null,
                'total'          => $calc['total'],
                'discount'       => $calc['discount_amount'],
                'tax'            => $calc['tax_amount'],
                'payment_method' => $c['pay']['method'],
                'receipt_mode'   => $c['receiptMode'],
                'lines'          => $auditLines,
            ],
            $this->request->ip()
        );

        $this->pdo->commit();
        return $txId;
    }

    private function checkoutResponse(array $tx, bool $duplicate): array
    {
        $id = (int)$tx['id'];
        return [
            'ok'          => true,
            'duplicate'   => $duplicate,
            'transaction' => [
                'id'             => $id,
                'receipt_no'     => (string)($tx['receipt_no'] ?? ''),
                'register_no'    => isset($tx['register_no']) ? (int)$tx['register_no'] : null,
                'member_name'    => (string)($tx['member_name'] ?? ''),
                'total'          => (int)($tx['total'] ?? 0),
                'tendered'       => (int)($tx['tendered'] ?? 0),
                'change'         => (int)($tx['change_amount'] ?? 0),
                'payment_method' => (string)($tx['payment_method'] ?? ''),
                'receipt_status' => (string)($tx['receipt_status'] ?? ''),
                'print_count'    => (int)($tx['print_count'] ?? 0),
                'created_at'     => (string)($tx['created_at'] ?? ''),
            ],
            'receipt_url' => '/index.php?page=pos.receipt&id=' . $id,
            'show_url'    => '/index.php?page=pos.show&id=' . $id,
        ];
    }

    /**
     * 印刷結果の記録（JSON）
     * POST: id, doc (receipt|ryoshu), result (printed|failed)
     */
    public function printed(): void
    {
        $this->requireAuthJson();
        $this->verifyCsrfJson();

        $tenantId = $this->auth->getTenantId();
        $id     = (int)$this->request->post('id', 0);
        $doc    = $this->request->post('doc', 'receipt') === 'ryoshu' ? 'ryoshu' : 'receipt';
        $result = $this->request->post('result', '') === 'printed' ? 'printed' : 'failed';

        $rec = (new PosTransaction($this->pdo))->recordPrint($id, $tenantId, $doc, $result);
        if ($rec === null) {
            $this->jsonError('取引が見つかりません。', 'not_found', 404);
        }

        // 領収書の発行とレシートの再発行は不正防止のため監査ログに残す
        $isReprint = $doc === 'receipt' && (int)$rec['before']['print_count'] > 0;
        if ($result === 'printed' && ($doc === 'ryoshu' || $isReprint)) {
            $this->audit('export', $id, null, [
                'kind'    => 'pos_print',
                'doc'     => $doc === 'ryoshu' ? '領収書' : 'レシート（再発行）',
                'count'   => $doc === 'ryoshu' ? (int)$rec['after']['ryoshu_count'] : (int)$rec['after']['print_count'],
            ]);
        }

        $this->json(['ok' => true, 'receipt_status' => $rec['after']['receipt_status'], 'print_count' => (int)$rec['after']['print_count']]);
    }

    // ================================================================
    // レシート・領収書
    // ================================================================

    /**
     * レシート / 領収書（HTML or JSON）
     * GET: id, doc (receipt|ryoshu), to（宛名）, tadashi（但し書き）, w (58|80), embed, format
     */
    public function receipt(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $txModel  = new PosTransaction($this->pdo);
        $tx       = $txModel->findById((int)$this->request->get('id', 0), $tenantId);
        if ($tx === null) {
            if ((string)$this->request->get('format', '') === 'json') {
                $this->jsonError('取引が見つかりません。', 'not_found', 404);
            }
            $this->response->notFound('取引が見つかりません。');
            return;
        }

        if ((string)$this->request->get('doc', '') === 'ryoshu') {
            $to      = $this->request->get('to', '');
            $tadashi = $this->request->get('tadashi', '');
            $to      = is_string($to) ? mb_substr($to, 0, 40) : '';
            $tadashi = is_string($tadashi) ? mb_substr($tadashi, 0, 50) : '';
            if ($tadashi === '') {
                $tadashi = (new PosSetting($this->pdo))->get($tenantId)['ryoshu_tadashi'];
            }
            $layout = ReceiptLayout::ryoshu($tx, $to, $tadashi, (int)$tx['ryoshu_count'] > 0);
            $this->outputPrint($layout, '領収書 ' . $tx['receipt_no']);
            return;
        }

        $items  = $txModel->items((int)$tx['id'], $tenantId);
        $layout = ReceiptLayout::receipt($tx, $items, (int)$tx['print_count'] > 0);
        $this->outputPrint($layout, 'レシート ' . $tx['receipt_no']);
    }

    /**
     * テスト印刷用レイアウト
     */
    public function printTest(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();
        $settings = (new PosSetting($this->pdo))->get($this->auth->getTenantId());
        $this->outputPrint(ReceiptLayout::test($settings), 'テスト印刷');
    }

    // ================================================================
    // 取引履歴・詳細・取消・CSV
    // ================================================================

    private function historyFilters(): array
    {
        $today = date('Y-m-d');
        $str = function (string $key, int $max): string {
            $v = $this->request->get($key, '');
            return is_string($v) ? mb_substr(trim($v), 0, $max) : '';
        };
        $from = self::normDate($this->request->get('date_from', ''), $today);
        $to   = self::normDate($this->request->get('date_to', ''), $today);
        if ($from > $to) {
            [$from, $to] = [$to, $from];
        }
        $status = $str('status', 20);
        $method = $str('payment_method', 20);
        return [
            'date_from'      => $from,
            'date_to'        => $to,
            'status'         => in_array($status, ['completed', 'voided'], true) ? $status : '',
            'payment_method' => isset(ReceiptLayout::PAYMENT_LABELS[$method]) ? $method : '',
            'receipt_no'     => $str('receipt_no', 20),
            // 会員: 会員番号の完全一致 または 会員名の部分一致（旧URLの member_code も受け付ける）
            'member'         => $str('member', 50) !== '' ? $str('member', 50) : $str('member_code', 50),
            'member_id'      => ctype_digit($str('member_id', 10)) ? (int)$str('member_id', 10) : 0,
            'cashier'        => $str('cashier', 50),
            'keyword'        => $str('keyword', 100),
            'ledger_id'      => ctype_digit($str('ledger_id', 18)) ? (int)$str('ledger_id', 18) : 0,
            'register_no'    => $this->registerFilter(),
            'branch_id'      => $this->branchFilter(),
        ];
    }

    /**
     * 画面の絞り込み条件をURLのクエリに戻す（ページ送り・CSV出力用）
     */
    public static function filterQuery(array $f, array $extra = []): string
    {
        $q = [
            'date_from'      => $f['date_from'] ?? '',
            'date_to'        => $f['date_to'] ?? '',
            'status'         => $f['status'] ?? '',
            'payment_method' => $f['payment_method'] ?? '',
            'receipt_no'     => $f['receipt_no'] ?? '',
            'member'         => $f['member'] ?? '',
            'member_id'      => !empty($f['member_id']) ? (int)$f['member_id'] : '',
            'cashier'        => $f['cashier'] ?? '',
            'keyword'        => $f['keyword'] ?? '',
            'ledger_id'      => !empty($f['ledger_id']) ? (int)$f['ledger_id'] : '',
            'register'       => $f['register_no'] ?? '',
            'branch'         => $f['branch_id'] ?? '',
        ];
        $q = array_filter($q, static fn ($v) => $v !== '' && $v !== null) + $extra;
        return http_build_query($q);
    }

    // ================================================================
    // レシート番号での呼出・会員検索
    // ================================================================

    /**
     * 入力・読み取ったレシート番号を正規化する
     *  - 「20261023-0001」  … そのまま
     *  - 「202610230001」   … レシートのバーコード（ハイフンなし）
     *  - 「1」「0001」      … 本日の連番
     *
     * @return string|null 正規化できない場合は null
     */
    public static function normalizeReceiptNo(string $in, string $today): ?string
    {
        $v = mb_convert_kana(trim($in), 'a', 'UTF-8');
        $v = str_replace(['ー', '－', '―', '‐', ' ', 'No.', 'NO.', 'no.', '#'], ['-', '-', '-', '-', '', '', '', '', ''], $v);
        if (preg_match('/^(\d{8})-?(\d{4,6})$/', $v, $m)) {
            $y = (int)substr($m[1], 0, 4);
            $mo = (int)substr($m[1], 4, 2);
            $d = (int)substr($m[1], 6, 2);
            if ($y >= 2000 && $y <= 2100 && checkdate($mo, $d, $y)) {
                return $m[1] . '-' . $m[2];
            }
            return null;
        }
        if (preg_match('/^\d{1,6}$/', $v) && (int)$v > 0) {
            return str_replace('-', '', $today) . '-' . str_pad((string)(int)$v, 4, '0', STR_PAD_LEFT);
        }
        return null;
    }

    /**
     * レシート番号で取引を呼び出す（明細・再印刷・領収書・取消の画面へ）
     * GET: no, format=json（POSレジの検索欄から）
     */
    public function lookup(): void
    {
        $json = (string)$this->request->get('format', '') === 'json';
        if ($json) {
            $this->requireAuthJson();
        } else {
            // ルートは JSON 応答のため認証なしで登録しているので、画面遷移の場合はここで確認する
            $this->auth->requireAuth();
            if ($this->auth->mustChangePassword()) {
                $this->response->redirect('/index.php?page=change_password');
                return;
            }
        }
        $this->setupSchema();

        $in = $this->request->get('no', '');
        $no = is_string($in) ? self::normalizeReceiptNo($in, date('Y-m-d')) : null;
        $tx = $no !== null ? (new PosTransaction($this->pdo))->findByReceiptNo($this->auth->getTenantId(), $no) : null;

        if ($json) {
            if ($tx === null) {
                $this->json(['ok' => false, 'error' => 'レシート番号「' . (is_string($in) ? mb_substr($in, 0, 30) : '') . '」の取引は見つかりません。']);
            }
            $this->json(['ok' => true, 'id' => (int)$tx['id'], 'receipt_no' => $tx['receipt_no'], 'url' => '/index.php?page=pos.show&id=' . (int)$tx['id']]);
        }
        if ($tx === null) {
            (new Session())->setFlash('error', 'レシート番号「' . (is_string($in) ? mb_substr($in, 0, 30) : '') . '」の取引は見つかりません。'
                . '（例：20261023-0001、本日分は連番だけ「1」でも可）');
            $this->response->redirect('/index.php?page=pos.history');
            return;
        }
        $this->response->redirect('/index.php?page=pos.show&id=' . (int)$tx['id']);
    }

    /**
     * 会員検索（JSON・POSレジの会員選択用）
     * GET: q（会員番号・氏名・電話番号の一部）
     */
    public function memberSearch(): void
    {
        $this->requireAuthJson();

        // 会員情報の機械的な列挙を防ぐ（1分間に30回まで）
        if (!RateLimiter::hit('pos.member', 30, 60)) {
            $this->json(['ok' => false, 'members' => [], 'error' => '短時間に検索が集中しています。しばらく待ってから再度お試しください。'], 429);
        }
        $q = $this->request->get('q', '');
        $q = is_string($q) ? mb_substr(trim($q), 0, 50) : '';
        if (mb_strlen($q) < 1) {
            $this->json(['ok' => true, 'members' => []]);
        }

        $like  = '%' . strtr($q, ['\\' => '\\\\', '%' => '\\%', '_' => '\\_']) . '%';
        $digits = preg_replace('/[^0-9]/', '', mb_convert_kana($q, 'n', 'UTF-8'));
        $sql = "SELECT `id`, `member_code`, `name`, `counterpart_type`, `phone` FROM `members`
                WHERE `tenant_id` = ? AND (`member_code` LIKE ? OR `name` LIKE ?"
             . (strlen($digits) >= 4 ? " OR REPLACE(REPLACE(`phone`, '-', ''), ' ', '') LIKE ?" : '') . ")
                ORDER BY (`member_code` = ?) DESC, `member_code` ASC LIMIT 20";
        $params = [$this->auth->getTenantId(), $like, $like];
        if (strlen($digits) >= 4) {
            $params[] = '%' . $digits . '%';
        }
        $params[] = $q;
        try {
            $stmt = $this->pdo->prepare($sql);
            $stmt->execute($params);
            $rows = $stmt->fetchAll();
        } catch (\PDOException $e) {
            $rows = [];
        }
        $stats = (new PosTransaction($this->pdo))->memberStats($this->auth->getTenantId(), array_column($rows, 'id'));

        $this->json(['ok' => true, 'members' => array_map(static function (array $m) use ($stats): array {
            $phone = preg_replace('/[^0-9]/', '', (string)($m['phone'] ?? ''));
            $st = $stats[(int)$m['id']] ?? ['count' => 0, 'total' => 0, 'last_at' => null];
            return [
                'id'          => (int)$m['id'],
                'member_code' => (string)$m['member_code'],
                'name'        => (string)$m['name'],
                'corporate'   => $m['counterpart_type'] === 'corporate',
                // 電話番号は本人確認の目安として下4桁のみ返す
                'phone_tail'  => strlen($phone) >= 4 ? substr($phone, -4) : '',
                'visits'      => $st['count'],
                'last_at'     => $st['last_at'] !== null ? substr((string)$st['last_at'], 0, 10) : '',
            ];
        }, $rows)]);
    }

    public function history(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $filters  = $this->historyFilters();
        $p        = $this->request->get('p', '1');
        $page     = (is_string($p) && ctype_digit($p)) ? max(1, (int)$p) : 1;
        $perPage  = 50;

        $result = (new PosTransaction($this->pdo))->search($tenantId, $filters, $page, $perPage);

        $this->render('pos/history', [
            'rows'       => $result['rows'],
            'total'      => $result['total'],
            'sumTotal'   => $result['sum_total'],
            'sumCount'   => $result['sum_count'],
            'filters'    => $filters,
            'page'       => $page,
            'totalPages' => max(1, (int)ceil($result['total'] / $perPage)),
            'branches'   => (new Branch($this->pdo))->findAllByTenant($tenantId),
            'registers'  => (new PosTransaction($this->pdo))->registerNumbers($tenantId),
            'isAdmin'    => $this->auth->isAdmin(),
            'activePage' => 'pos.history',
        ]);
    }

    /**
     * レジ明細検索（明細単位の検索・集計）
     */
    public function items(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $filters  = $this->historyFilters();
        $p        = $this->request->get('p', '1');
        $page     = (is_string($p) && ctype_digit($p)) ? max(1, (int)$p) : 1;
        $perPage  = 100;
        $model    = new PosTransaction($this->pdo);
        $result   = $model->searchItems($tenantId, $filters, $page, $perPage);

        $this->render('pos/items', [
            'rows'       => $result['rows'],
            'total'      => $result['total'],
            'sumQty'     => $result['qty'],
            'sumAmount'  => $result['amount'],
            'sumAlloc'   => $result['allocated'],
            'filters'    => $filters,
            'page'       => $page,
            'totalPages' => max(1, (int)ceil($result['total'] / $perPage)),
            'branches'   => (new Branch($this->pdo))->findAllByTenant($tenantId),
            'registers'  => $model->registerNumbers($tenantId),
            'isAdmin'    => $this->auth->isAdmin(),
            'activePage' => 'pos.items',
        ]);
    }

    public function show(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $txModel  = new PosTransaction($this->pdo);
        $tx       = $txModel->findById((int)$this->request->get('id', 0), $tenantId);
        if ($tx === null) {
            $this->response->notFound('取引が見つかりません。');
            return;
        }

        $this->render('pos/show', [
            'tx'         => $tx,
            'items'      => $txModel->items((int)$tx['id'], $tenantId),
            'settings'   => (new PosSetting($this->pdo))->get($tenantId),
            'isAdmin'    => $this->auth->isAdmin(),
            'activePage' => 'pos.history',
        ]);
    }

    /**
     * 会計の取消（返品・管理者のみ）: 販売記録を削除して在庫を戻す
     */
    public function voidTransaction(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $session  = new Session();
        $id       = (int)$this->request->post('id', 0);
        $reason   = trim((string)$this->request->post('reason', ''));
        $back     = '/index.php?page=pos.show&id=' . $id;

        if ($reason === '' || mb_strlen($reason) > 255) {
            $session->setFlash('error', '取消理由を255文字以内で入力してください。');
            $this->response->redirect($back);
            return;
        }

        $txModel = new PosTransaction($this->pdo);
        try {
            $before = $txModel->void($id, $tenantId, $this->auth->getUserId(), $reason);
        } catch (\Throwable $e) {
            error_log('[furyo-dacho] POS void failed: ' . $e->getMessage());
            $session->setFlash('error', '取消処理に失敗しました。もう一度お試しください。');
            $this->response->redirect($back);
            return;
        }
        if ($before === null) {
            $session->setFlash('error', 'この取引は取消できません（既に取消済みか、見つかりません）。');
            $this->response->redirect($back);
            return;
        }

        $items = $txModel->items($id, $tenantId);
        $this->audit('delete', $id, [
            'kind'           => 'pos_transaction',
            'receipt_no'     => $before['receipt_no'],
            'total'          => (int)$before['total'],
            'payment_method' => $before['payment_method'],
            'lines'          => array_map(static fn ($i) => ['ledger_id' => (int)$i['ledger_id'], 'sale_id' => $i['sale_id'] !== null ? (int)$i['sale_id'] : null, 'quantity' => (int)$i['quantity']], $items),
        ], ['kind' => 'pos_void', 'status' => 'voided', 'reason' => $reason]);

        $refund = $before['payment_method'] === 'cash'
            ? '現金 ¥' . number_format((int)$before['total']) . ' を返金してください。'
            : ReceiptLayout::PAYMENT_LABELS[$before['payment_method']] . 'の取消（返金）手続きを各決済端末で行ってください。';
        $session->setFlash('success', '✓ 取引 No.' . $before['receipt_no'] . ' を取り消し、在庫を戻しました。' . $refund);
        $this->response->redirect($back);
    }

    /**
     * 取引明細の CSV 出力（管理者のみ）
     */
    public function export(): void
    {
        $this->auth->requireAdmin();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $filters  = $this->historyFilters();
        // mode=items: レジ明細検索の条件（品名・シリアル・台帳IDで明細を絞る）で出力
        $lineMode = (string)$this->request->get('mode', '') === 'items';
        $rows     = (new PosTransaction($this->pdo))->exportRows($tenantId, $filters, 20000, $lineMode);

        $this->audit('export', null, null, ['kind' => 'pos_csv', 'count' => count($rows), 'filters' => $filters]);

        $name  = 'POS売上明細_' . str_replace('-', '', $filters['date_from']) . '-' . str_replace('-', '', $filters['date_to']) . '.csv';
        $ascii = 'pos_sales_' . str_replace('-', '', $filters['date_from']) . '-' . str_replace('-', '', $filters['date_to']) . '.csv';
        header('Content-Type: text/csv; charset=UTF-8');
        header('Content-Disposition: attachment; filename="' . $ascii . '"; filename*=UTF-8\'\'' . rawurlencode($name));
        header('Cache-Control: no-cache, no-store, must-revalidate');

        $safe = static function ($v): string {
            $s = (string)$v;
            // 先頭が = + - @ タブ CR のセルは数式として評価されないよう無害化（ExportController::csvSafe と同じ）
            // ただし負の数値（-1000 等）は数値のまま出力する
            if ($s !== '' && in_array($s[0], ['=', '+', '-', '@', "\t", "\r"], true) && !preg_match('/^-[0-9]+$/', $s)) {
                return "'" . $s;
            }
            return $s;
        };

        $fp = fopen('php://output', 'w');
        fwrite($fp, "\xEF\xBB\xBF");
        fputcsv($fp, ['会計日時', 'レシート番号', 'レジ番号', '状態', '拠点', '担当者', '支払方法', '会員番号', '会員名', '明細No', '台帳ID',
            '品名', 'シリアル番号', '数量', '単価', '単品値引', '明細金額', '売上計上額', '会計小計', '小計値引',
            '税区分', '税率(%)', '消費税等', '会計合計', 'お預り', 'お釣り', '取消日時', '取消理由']);
        foreach ($rows as $r) {
            fputcsv($fp, array_map($safe, [
                $r['created_at'], $r['receipt_no'], $r['register_no'] ?? '', $r['status'] === 'voided' ? '取消' : '完了', $r['branch_name'] ?? '',
                $r['cashier_name'] ?? '', ReceiptLayout::PAYMENT_LABELS[$r['payment_method']] ?? $r['payment_method'],
                $r['member_code'] ?? '', $r['member_name'] ?? '', $r['line_no'], $r['ledger_id'], $r['item_name'], $r['serial_number'] ?? '',
                $r['quantity'], (int)$r['unit_price'], (int)$r['line_discount'], (int)$r['amount'], (int)$r['allocated_amount'],
                (int)$r['subtotal'], (int)$r['discount_amount'], $r['tax_mode'] === 'exclusive' ? '外税' : '内税',
                $r['tax_rate'], (int)$r['tax_amount'], (int)$r['total'], (int)$r['tendered'], (int)$r['change_amount'],
                $r['voided_at'] ?? '', $r['void_reason'] ?? '',
            ]));
        }
        fclose($fp);
        exit;
    }

    // ================================================================
    // レジ精算（日計）
    // ================================================================

    private function branchLabel(?int $branchId, array $branches): string
    {
        if ($branchId === null) {
            return '全拠点';
        }
        foreach ($branches as $b) {
            if ((int)$b['id'] === $branchId) {
                return (string)$b['name'];
            }
        }
        return '拠点 #' . $branchId;
    }

    public function daily(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $date     = self::normDate($this->request->get('date', ''), date('Y-m-d'));
        $branchId = $this->branchFilter();
        $registerNo = $this->registerFilter();
        $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);
        if ($branchId !== null && $this->branchLabel($branchId, $branches) === '拠点 #' . $branchId) {
            $branchId = null; // 他テナントの拠点IDは無視
        }
        $txModel = new PosTransaction($this->pdo);

        $this->render('pos/daily', [
            'date'        => $date,
            'branchId'    => $branchId,
            'registerNo'  => $registerNo,
            'registers'   => $txModel->registerNumbers($tenantId),
            'branches'    => $branches,
            'branchLabel' => $this->branchLabel($branchId, $branches),
            'summary'     => $txModel->dailySummary($tenantId, $date, $branchId, $registerNo),
            'closings'    => (new PosClosing($this->pdo))->findByDate($tenantId, $date),
            'closedId'    => (int)$this->request->get('closed', 0),
            'denominations' => PosClosing::DENOMINATIONS,
            'activePage'  => 'pos.daily',
        ]);
    }

    /**
     * 精算の記録
     * POST: date, branch, opening_float, den[金種]=枚数, counted_cash, note
     */
    public function close(): void
    {
        $this->auth->requireAuth();
        $this->verifyCsrf();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $session  = new Session();
        $date     = self::normDate($this->request->post('date', ''), '');
        $branchIn = $this->request->post('branch', '');
        $branchId = (is_string($branchIn) && ctype_digit($branchIn) && (int)$branchIn > 0) ? (int)$branchIn : null;
        $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);
        if ($branchId !== null && $this->branchLabel($branchId, $branches) === '拠点 #' . $branchId) {
            $branchId = null;
        }
        $registerNo = $this->registerFilter('register', true);
        $back = '/index.php?page=pos.daily&date=' . rawurlencode($date) . ($branchId !== null ? '&branch=' . $branchId : '')
              . ($registerNo !== null ? '&register=' . $registerNo : '');

        if ($date === '' || $date > date('Y-m-d')) {
            $session->setFlash('error', '営業日が不正です（未来の日付は精算できません）。');
            $this->response->redirect('/index.php?page=pos.daily');
            return;
        }

        $num = static function ($v): ?int {
            // 全角のカンマ・円記号・空白も取り除く（画面の計算は受け付けるのに、保存時だけエラーになっていた）
            $v = is_string($v) ? str_replace([',', '，', '¥', '￥', '\\', ' ', '　'], '', mb_convert_kana($v, 'n', 'UTF-8')) : '';
            if ($v === '') {
                return 0;
            }
            return preg_match('/^[0-9]{1,10}$/', $v) ? (int)$v : null;
        };

        $opening = $num($this->request->post('opening_float', ''));
        $counted = $num($this->request->post('counted_cash', ''));
        $note    = trim((string)$this->request->post('note', ''));
        if ($opening === null || $counted === null || $opening > PosCalculator::MAX_AMOUNT || $counted > PosCalculator::MAX_AMOUNT) {
            $session->setFlash('error', '釣銭準備金・現金実査額は0以上の数値（円）で入力してください。');
            $this->response->redirect($back);
            return;
        }
        if (mb_strlen($note) > 400) {
            $session->setFlash('error', '備考は400文字以内で入力してください。');
            $this->response->redirect($back);
            return;
        }

        $denIn = $this->request->post('den', []);
        $denominations = [];
        $denTotal = 0;
        foreach (PosClosing::DENOMINATIONS as $face) {
            $cnt = is_array($denIn) ? $num($denIn[(string)$face] ?? '') : 0;
            if ($cnt === null || $cnt > 100000) {
                $session->setFlash('error', number_format($face) . '円の枚数が不正です。');
                $this->response->redirect($back);
                return;
            }
            $denominations[(string)$face] = $cnt;
            $denTotal += $face * $cnt;
        }
        // 金種を入力した場合は金種の合計を実査額とする
        if ($denTotal > 0) {
            $counted = $denTotal;
        }

        $summary  = (new PosTransaction($this->pdo))->dailySummary($tenantId, $date, $branchId, $registerNo);
        // 理論現金残高 = 釣銭準備金 + 当日の現金売上 − 当日に返金した前日以前の現金会計
        $expected = $opening + (int)$summary['cash_sales'] - (int)($summary['refund_prev_cash'] ?? 0);
        $user     = $this->auth->user() ?? [];

        $closingId = (new PosClosing($this->pdo))->create([
            'tenant_id'      => $tenantId,
            'branch_id'      => $branchId,
            'register_no'    => $registerNo,
            'biz_date'       => $date,
            'tx_count'       => (int)$summary['tx_count'],
            'sales_total'    => (int)$summary['total'],
            'cash_sales'     => (int)$summary['cash_sales'],
            'opening_float'  => $opening,
            'expected_cash'  => $expected,
            'counted_cash'   => $counted,
            'difference'     => $counted - $expected,
            'denominations'  => $denominations,
            'summary'        => $summary,
            'note'           => $note,
            'closed_by'      => $this->auth->getUserId(),
            'closed_by_name' => (string)($user['display_name'] ?? ''),
        ]);

        $this->audit('create', $closingId, null, [
            'kind' => 'pos_closing', 'biz_date' => $date, 'branch_id' => $branchId, 'register_no' => $registerNo,
            'sales_total' => (int)$summary['total'], 'expected_cash' => $expected, 'counted_cash' => $counted,
            'difference' => $counted - $expected,
        ]);

        $diff = $counted - $expected;
        $session->setFlash(
            $diff === 0 ? 'success' : 'error',
            ($diff === 0 ? '✓ 精算を記録しました（過不足なし）。' : '精算を記録しました。現金に過不足があります（' . ($diff > 0 ? '+' : '-') . '¥' . number_format(abs($diff)) . '）。')
        );
        $this->response->redirect($back . '&closed=' . $closingId);
    }

    /**
     * 精算レポートの印刷（HTML or JSON）
     */
    public function closingPrint(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $closing  = (new PosClosing($this->pdo))->findById((int)$this->request->get('id', 0), $tenantId);
        if ($closing === null) {
            if ((string)$this->request->get('format', '') === 'json') {
                $this->jsonError('精算記録が見つかりません。', 'not_found', 404);
            }
            $this->response->notFound('精算記録が見つかりません。');
            return;
        }
        $settings = (new PosSetting($this->pdo))->get($tenantId);
        $label    = $closing['branch_id'] !== null ? (string)($closing['branch_name'] ?? ('拠点 #' . $closing['branch_id'])) : '全拠点';
        $regLabel = !empty($closing['register_no']) ? 'レジ' . sprintf('%02d', (int)$closing['register_no']) : '全レジ';
        $this->outputPrint(ReceiptLayout::closing($closing, $settings['store_name'], $label, $regLabel), 'レジ精算 ' . $closing['biz_date']);
    }

    // ================================================================
    // 設定
    // ================================================================

    public function settings(): void
    {
        $this->auth->requireAuth();
        $this->setupSchema();

        $this->render('pos/settings', [
            'settings'   => (new PosSetting($this->pdo))->get($this->auth->getTenantId()),
            'isAdmin'    => $this->auth->isAdmin(),
            'errors'     => [],
            'activePage' => 'pos.settings',
        ]);
    }

    public function settingsSave(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();
        $this->setupSchema();

        $tenantId = $this->auth->getTenantId();
        $model    = new PosSetting($this->pdo);
        $before   = $model->get($tenantId);

        [$data, $errors] = PosSetting::validate($_POST + []);
        // Request::sanitize と同じく制御文字を除去（改行は保持）
        foreach ($data as $k => $v) {
            if (is_string($v)) {
                $data[$k] = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/u', '', $v) ?? '';
            }
        }

        if ($errors !== []) {
            $this->render('pos/settings', [
                'settings'   => array_merge($before, $data, ['store_name_raw' => $data['store_name']]),
                'isAdmin'    => true,
                'errors'     => $errors,
                'activePage' => 'pos.settings',
            ]);
            return;
        }

        $model->save($tenantId, $data, $this->auth->getUserId());
        $keys = ['store_name_raw', 'store_address', 'store_phone', 'invoice_number', 'tax_rate', 'tax_mode', 'tax_rounding', 'receipt_header', 'receipt_footer', 'ryoshu_tadashi'];
        $b = ['kind' => 'pos_settings'];
        foreach ($keys as $k) {
            $b[$k] = $before[$k];
        }
        $a = ['kind' => 'pos_settings'] + $data;
        $this->audit('edit', null, $b, $a);

        (new Session())->setFlash('success', '✓ 店舗・レシート設定を保存しました。');
        $this->response->redirect('/index.php?page=pos.settings');
    }
}
