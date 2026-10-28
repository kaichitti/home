<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\Ledger;
use FuryoDacho\Models\Branch;
use FuryoDacho\Models\AuditLog;
use FuryoDacho\Models\Alert;
use FuryoDacho\Models\LedgerFile;
use FuryoDacho\Helpers\FileUpload;
use FuryoDacho\Helpers\Validator;

/**
 * 古物台帳コントローラー
 */
class LedgerController extends BaseController
{
    // 台帳登録の必須フィールド一覧
    private const REQUIRED_FIELDS = [
        'transaction_date',
        'transaction_type',
        'item_category',
        'item_name',
        'quantity',
        'transaction_amount',
        'counterpart_name',
        'counterpart_address',
    ];

    /** 本人確認書類種別の有効値 */
    private const DOC_TYPES = [
        'driver_license', 'my_number', 'passport', 'health_insurance',
        'residence_card', 'residence_status', 'special_permanent', 'other',
    ];

    /**
     * 台帳一覧（検索フォーム + ページネーション）
     */
    public function index(): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        // 検索条件は文字列のみ受け付ける（配列が送られた場合は条件なしとして扱う）
        $g = function (string $key): ?string {
            $v = $this->request->get($key);
            return is_string($v) ? $v : null;
        };
        $filters  = [
            'date_from'          => $g('date_from'),
            'date_to'            => $g('date_to'),
            'item_category'      => $g('item_category'),
            'transaction_type'   => $g('transaction_type'),
            'item_name'          => $g('item_name'),
            'counterpart_name'   => $g('counterpart_name'),
            'serial_number'      => $g('serial_number'),
            'approval_status'    => $g('approval'),
            // 検索フォームの name 属性は registered_by。
            // 以前は registered_by_id しか見ていなかったため登録者フィルタが機能していなかった。
            'registered_by_id'   => $g('registered_by') ?? $g('registered_by_id'),
            'branch_id'          => $g('branch_id'),
            'fiscal_year'        => $g('fiscal_year'),
        ];
        $page    = max(1, (int)$this->request->get('p', 1));
        $perPage = 50;

        $ledgerModel = new Ledger($this->pdo);
        $result      = $ledgerModel->findAll($tenantId, $filters, $page, $perPage);
        $ledgers     = $result['records'];
        $total       = $result['total'];
        $years       = $ledgerModel->getYears($tenantId);
        $branches    = (new Branch($this->pdo))->findAllByTenant($tenantId);
        $users       = (new \FuryoDacho\Models\User($this->pdo))->getByTenant($tenantId);

        // ビューが期待する変数名に合わせてエイリアスを設定
        $search                  = $filters;
        $search['registered_by'] = $filters['registered_by_id'];
        $currentPage = $page;
        $totalPages  = $total > 0 ? (int)ceil($total / $perPage) : 1;

        // 法定13区分 + テナント独自区分 + その他（検索用）
        $itemTypes = (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId);
        $transactionTypes = [
            'buy' => '買取', 'exchange' => '交換', 'consignment' => '委託販売受け', 'other' => 'その他',
        ];

        $approvalMode = $this->request->get('approval') === 'pending';

        $this->render('ledger/index', compact(
            'ledgers', 'total', 'search', 'currentPage', 'totalPages',
            'perPage', 'branches', 'years', 'users', 'itemTypes', 'transactionTypes',
            'approvalMode'
        ));
    }

    /**
     * 台帳登録フォーム表示
     */
    public function create(): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);
        $categoryOptions = (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId);

        // 新規登録の初期値: 取引年月日は今日、拠点はログイン中の利用者の所属拠点（拠点が1つだけならその拠点）
        $defaultBranch = $this->auth->user()['branch_id'] ?? null;
        if (empty($defaultBranch) && count($branches) === 1) {
            $defaultBranch = (int)$branches[0]['id'];
        }

        $this->render('ledger/form', [
            'ledger'          => null,
            'branches'        => $branches,
            'categoryOptions' => $categoryOptions,
            'csrf_token'      => $this->generateCsrfToken(),
            'errors'          => [],
            'input'           => [
                'transaction_date' => date('Y-m-d'),
                'branch_id'        => $defaultBranch !== null ? (string)$defaultBranch : '',
            ],
        ]);
    }

    /**
     * 台帳登録処理（POST）
     * バリデーション → 保存 → AuditLog 記録の順に処理する。
     * ファイルアップロード（LedgerFile）は TODO: Phase4
     */
    public function store(): void
    {
        $this->auth->requireAuth();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();
        $input    = $this->request->all();

        // branch_id はフォーム送信値を優先し、未送信の場合はセッションのユーザー情報から補完する
        if (empty($input['branch_id'])) {
            $input['branch_id'] = $this->auth->user()['branch_id'] ?? null;
        }

        // branch_id が NULL の場合は登録不可（台帳は拠点紐付け必須）
        if (empty($input['branch_id'])) {
            $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);
            $this->render('ledger/form', [
                'ledger'          => null,
                'branches'        => $branches,
                'categoryOptions' => (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId),
                'csrf_token'      => $this->generateCsrfToken(),
                'errors'          => ['general' => '拠点が設定されていません。フォームで拠点を選択するか、管理者に連絡して拠点を割り当ててもらってください。'],
                'input'           => $input,
            ]);
            return;
        }

        // branch_id が現在テナントの拠点か検証（他テナントへの不正紐付け防止）
        if (!$this->branchBelongsToTenant((int)$input['branch_id'], $tenantId)) {
            $this->response->forbidden('無効な拠点が指定されました。');
            return;
        }

        $errors = $this->validateLedgerInput($input);

        if (!empty($errors)) {
            $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);
            $this->render('ledger/form', [
                'ledger'          => null,
                'branches'        => $branches,
                'categoryOptions' => (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId),
                'csrf_token'      => $this->generateCsrfToken(),
                'errors'          => $errors,
                'input'           => $input,
            ]);
            return;
        }

        $input['registered_by'] = $userId;
        $ledgerModel = new Ledger($this->pdo);
        try {
            $newId = $ledgerModel->create($tenantId, $input);
        } catch (\PDOException $e) {
            // DBエラーは内部情報（SQL文等）を画面に出さず、入力内容を残したままフォームを再表示する
            error_log('LedgerController::store failed: ' . $e->getMessage());
            $this->render('ledger/form', [
                'ledger'          => null,
                'branches'        => (new Branch($this->pdo))->findAllByTenant($tenantId),
                'categoryOptions' => (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId),
                'csrf_token'      => $this->generateCsrfToken(),
                'errors'          => ['general' => '台帳を登録できませんでした。入力内容（文字数・数値の範囲など）を確認してください。'],
                'input'           => $input,
            ]);
            return;
        }

        // 登録完了のメッセージ（以前は一覧へ ?flash=created を付けて戻るだけで、画面には何も表示されなかった）
        $successMessages = ['台帳 #' . $newId . '「' . (string)$input['item_name'] . '」を登録しました。'];

        // 相手方情報から新規会員を同時登録（チェックボックスON時）
        if (!empty($this->request->post('register_member'))) {
            $memberModel = new \FuryoDacho\Models\Member($this->pdo);
            $code        = trim((string)($input['member_code'] ?? ''));

            if ($code !== '' && $memberModel->existsCode($tenantId, $code)) {
                // 既存番号 → 会員登録はスキップ
                $successMessages[] = '会員番号「' . $code . '」は既に登録済みのため、会員の新規登録はスキップしました。';
            } else {
                // 未入力なら自動採番
                if ($code === '') {
                    $code = $memberModel->generateCode($tenantId);
                }

                try {
                    $memberModel->create($tenantId, [
                        'member_code'        => $code,
                        'counterpart_type'   => $input['counterpart_type'] ?? 'individual',
                        'name'               => $input['counterpart_name'] ?? '',
                        'address'            => $input['counterpart_address'] ?? '',
                        'occupation'         => $input['counterpart_occupation'] ?? '',
                        'age'                => $input['counterpart_age'] ?? '',
                        'phone'              => $input['counterpart_phone'] ?? '',
                        'contact_name'       => $input['counterpart_contact_name'] ?? '',
                        'account'            => $input['counterpart_account'] ?? '',
                        'id_document_type'   => $input['id_document_type'] ?? '',
                        'id_document_number' => $input['id_document_number'] ?? '',
                        'note'               => $input['counterpart_note'] ?? '',
                    ]);

                    // 台帳にも会員番号を反映（承認判定・引用に利用できるように）
                    $this->pdo->prepare(
                        "UPDATE `ledgers` SET `member_code` = ? WHERE `id` = ? AND `tenant_id` = ?"
                    )->execute([$code, $newId, $tenantId]);
                    $input['member_code'] = $code;

                    $successMessages[] = '相手方情報から会員「' . $code . '」を新規登録しました。';
                } catch (\PDOException $e) {
                    // 同時に同じ番号が登録された場合など。台帳は登録済みのため 500 にせず案内する
                    error_log('LedgerController::store member create failed: ' . $e->getMessage());
                    $successMessages[] = '会員の新規登録はできませんでした（会員番号「' . $code . '」が既に使われている可能性があります）。会員管理から登録してください。';
                }
            }
        }

        // Phase4: ファイルアップロード処理
        // 本人確認書類が「実際に保存できたか」で承認判定するため、判定より先に保存する。
        // （以前は判定後に保存しており、アップロードが失敗しても「書類あり」とみなされ
        //   承認待ちにならなかった。また後から設定したフラッシュで警告が上書きされ消えていた）
        $fileErrors = [];
        $this->saveUploadedFiles($newId, $tenantId, $fileErrors);

        $errorMessages = [];
        if (!empty($fileErrors)) {
            // 台帳自体は登録済みなので、ファイルの失敗はフラッシュで通知する
            $errorMessages[] = '台帳は登録されましたが、添付ファイルの保存に失敗しました: ' . implode(' / ', $fileErrors);
        }

        // 本人確認情報が未登録の場合はアラートを表示（登録自体は許可）
        $hasIdFile = (new LedgerFile($this->pdo))->countByLedgerAndType($newId, $tenantId, 'id_document') > 0;
        $idSkipped = empty($input['id_document_type']) && !$hasIdFile;

        if ($idSkipped) {
            // 相手方が「認証済み」か判定:
            // 会員番号が紐付いていて、その会員に本人確認情報が登録されていれば認証済みとみなす
            $verifiedMember = false;
            if (!empty($input['member_code'])) {
                $member = (new \FuryoDacho\Models\Member($this->pdo))
                    ->findByCode($tenantId, (string)$input['member_code']);
                $verifiedMember = $member !== null && !empty($member['id_document_type']);
            }

            if (!$verifiedMember) {
                // 本人確認スキップ + 未認証相手 → 管理者の承認待ちにする
                $this->pdo->prepare(
                    "UPDATE `ledgers` SET `approval_status` = 'pending' WHERE `id` = ? AND `tenant_id` = ?"
                )->execute([$newId, $tenantId]);

                $errorMessages[] = '⚠ 本人確認情報が未登録かつ相手方が未認証（本人確認済み会員に紐付いていない）のため、この台帳は管理者の承認待ちになりました。管理者が内容を確認して承認します。';
            } else {
                $errorMessages[] = '⚠ この台帳は本人確認情報が未登録です（本人確認済みの会員に紐付いているため承認は不要です）。必要に応じて編集画面から登録してください。';
            }
        }

        // 複数の警告があっても上書きで消えないよう、まとめて1件のフラッシュにする
        // （表示側で htmlspecialchars されるため、記号は HTML 実体参照ではなく文字で書く）
        if (!empty($errorMessages)) {
            (new \FuryoDacho\Core\Session())->setFlash('error', implode(' ／ ', $errorMessages));
        }

        // Phase5: 重複検知アラート（ファイル保存後に実行して ledger_files.created_at を参照できるようにする）
        (new Alert($this->pdo))->detectDuplicates($tenantId, $newId);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $userId,
            $this->auth->user()['display_name'],
            null,
            'create',
            $newId,
            null,
            $this->sanitizeForLog($input),
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash('success', implode(' ', $successMessages));
        $this->response->redirect('/index.php?page=ledger');
    }

    /**
     * 台帳詳細表示
     *
     * @param int $id
     */
    /**
     * 承認待ち台帳の承認（管理者のみ）
     * 本人確認スキップ + 未認証相手で登録された台帳を、
     * 管理者が内容確認のうえ承認する。
     */
    public function approve(int $id = 0): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->post('id');
        $session  = new \FuryoDacho\Core\Session();

        $record = (new Ledger($this->pdo))->findById($id, $tenantId);
        if ($record === null) {
            $this->response->notFound('台帳が見つかりません。');
            return;
        }

        if (($record['approval_status'] ?? 'none') !== 'pending') {
            $session->setFlash('error', 'この台帳は承認待ちではありません。');
            $this->response->redirect('/index.php?page=ledger.show&id=' . $id);
            return;
        }

        $this->pdo->prepare(
            "UPDATE `ledgers`
             SET `approval_status` = 'approved', `approved_by` = ?, `approved_at` = NOW()
             WHERE `id` = ? AND `tenant_id` = ?"
        )->execute([$this->auth->getUserId(), $id, $tenantId]);

        // 監査ログ
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $this->auth->getUserId(),
            $this->auth->user()['display_name'],
            null,
            'edit',
            $id,
            ['approval_status' => 'pending'],
            ['approval_status' => 'approved', 'action' => 'ledger_approved'],
            $this->request->ip()
        );

        $session->setFlash('success', '台帳 #' . $id . ' を承認しました。');
        $this->response->redirect('/index.php?page=ledger.show&id=' . $id);
    }

    /**
     * 販売記録の追加（在庫管理）
     */
    public function saleStore(): void
    {
        $this->auth->requireAuth();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $ledgerId = (int)$this->request->post('id');
        $session  = new \FuryoDacho\Core\Session();

        $record = (new Ledger($this->pdo))->findById($ledgerId, $tenantId);
        if ($record === null) {
            $this->response->notFound('台帳が見つかりません。');
            return;
        }

        $quantity   = (int)$this->postStr('quantity', '1');
        $saleAmount = $this->postStr('sale_amount');
        $soldAt     = $this->postStr('sold_at');
        $note       = $this->postStr('note');
        $memberCode = $this->postStr('member_code');

        $redirect = '/index.php?page=ledger.show&id=' . $ledgerId;

        // 販売先の会員番号（任意・入力時は存在チェック）
        if ($memberCode !== ''
            && (new \FuryoDacho\Models\Member($this->pdo))->findByCode($tenantId, $memberCode) === null) {
            $session->setFlash('error', '会員番号「' . $memberCode . '」は登録されていません。先に会員管理から登録してください。');
            $this->response->redirect($redirect);
            return;
        }

        if ($quantity < 1) {
            $session->setFlash('error', '販売個数は1以上で入力してください。');
            $this->response->redirect($redirect);
            return;
        }

        // 残数チェック（複数個口の分割販売に対応）
        $saleModel = new \FuryoDacho\Models\Sale($this->pdo);
        $remaining = (int)$record['quantity'] - $saleModel->soldQuantity($ledgerId, $tenantId);
        if ($quantity > $remaining) {
            $session->setFlash('error', '販売個数が残在庫（' . $remaining . '点）を超えています。');
            $this->response->redirect($redirect);
            return;
        }

        if ($saleAmount !== '' && (!ctype_digit($saleAmount) || strlen($saleAmount) > 12)) {
            $session->setFlash('error', '販売金額は数値（円）で入力してください。');
            $this->response->redirect($redirect);
            return;
        }

        // 日時: datetime-local（YYYY-MM-DDTHH:MM）またはブランク→現在時刻
        if ($soldAt === '') {
            $soldAt = date('Y-m-d H:i:s');
        } else {
            $soldAt = str_replace('T', ' ', $soldAt);
            $ts = strtotime($soldAt);
            if ($ts === false) {
                $session->setFlash('error', '販売日時の形式が不正です。');
                $this->response->redirect($redirect);
                return;
            }
            $soldAt = date('Y-m-d H:i:s', $ts);
        }

        if (mb_strlen($note) > 512) {
            $session->setFlash('error', '備考は512文字以内で入力してください。');
            $this->response->redirect($redirect);
            return;
        }

        // 同時に別の端末（POS等）で販売された場合の在庫超過を防ぐため、
        // トランザクション内で台帳行をロックし、最新の残数で再検証してから登録する。
        // DDL（暗黙コミットを伴う）のスキーマ補修はトランザクション開始前に済ませる。
        $saleModel->ensureSchema();
        $this->pdo->beginTransaction();
        try {
            $locked       = $saleModel->lockLedgers([$ledgerId], $tenantId);
            $remainingNow = isset($locked[$ledgerId])
                ? $locked[$ledgerId]['quantity'] - $locked[$ledgerId]['sold']
                : null;
            if ($remainingNow === null || $quantity > $remainingNow) {
                $this->pdo->rollBack();
                $session->setFlash('error', '販売個数が残在庫（' . max(0, (int)$remainingNow) . '点）を超えています。');
                $this->response->redirect($redirect);
                return;
            }

            $saleId = $saleModel->create($tenantId, [
                'ledger_id'   => $ledgerId,
                'member_code' => $memberCode,
                'quantity'    => $quantity,
                'sale_amount' => $saleAmount,
                'sold_at'     => $soldAt,
                'note'        => $note,
                'created_by'  => $this->auth->getUserId(),
            ]);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            $session->setFlash('error', '販売記録の登録に失敗しました。もう一度お試しください。');
            $this->response->redirect($redirect);
            return;
        }
        $remaining = $remainingNow;

        (new AuditLog($this->pdo))->log(
            $tenantId, $this->auth->getUserId(), $this->auth->user()['display_name'],
            null, 'create', $saleId, null,
            ['kind' => 'sale', 'ledger_id' => $ledgerId, 'quantity' => $quantity, 'sale_amount' => $saleAmount],
            $this->request->ip()
        );

        $newRemaining = $remaining - $quantity;
        $session->setFlash('success', '販売記録を追加しました。（残在庫: ' . $newRemaining . '点' . ($newRemaining === 0 ? '・売切' : '') . '）');
        $this->response->redirect($redirect);
    }

    /**
     * 販売記録の編集フォーム（管理者のみ・記録訂正用）
     */
    public function saleEdit(): void
    {
        $this->auth->requireAdmin();

        $tenantId = $this->auth->getTenantId();
        $saleId   = (int)$this->request->get('sale_id');

        $saleModel = new \FuryoDacho\Models\Sale($this->pdo);
        $sale      = $saleModel->findById($saleId, $tenantId);

        if ($sale === null) {
            $this->response->notFound('販売記録が見つかりません。');
            return;
        }

        if ($this->redirectIfPosSale($sale)) {
            return;
        }

        $record = (new Ledger($this->pdo))->findById((int)$sale['ledger_id'], $tenantId);
        if ($record === null) {
            $this->response->notFound('台帳が見つかりません。');
            return;
        }

        // この販売を除いた販売済数（数量変更の上限計算用）
        $soldOther = $saleModel->soldQuantity((int)$sale['ledger_id'], $tenantId) - (int)$sale['quantity'];
        $maxQty    = max(1, (int)$record['quantity'] - $soldOther);

        $this->render('sale/form', [
            'sale'       => $sale,
            'record'     => $record,
            'maxQty'     => $maxQty,
            'csrf_token' => $this->generateCsrfToken(),
        ]);
    }

    /**
     * 販売記録の更新（管理者のみ）
     */
    public function saleUpdate(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $saleId   = (int)$this->request->post('sale_id');
        $session  = new \FuryoDacho\Core\Session();

        $saleModel = new \FuryoDacho\Models\Sale($this->pdo);
        $sale      = $saleModel->findById($saleId, $tenantId);

        if ($sale === null) {
            $this->response->notFound('販売記録が見つかりません。');
            return;
        }

        if ($this->redirectIfPosSale($sale)) {
            return;
        }

        $ledgerId = (int)$sale['ledger_id'];
        $record   = (new Ledger($this->pdo))->findById($ledgerId, $tenantId);
        $redirect = '/index.php?page=ledger.show&id=' . $ledgerId;

        $quantity   = (int)$this->postStr('quantity', '1');
        $saleAmount = $this->postStr('sale_amount');
        $soldAt     = $this->postStr('sold_at');
        $note       = $this->postStr('note');
        $memberCode = $this->postStr('member_code');

        if ($quantity < 1) {
            $session->setFlash('error', '販売個数は1以上で入力してください。');
            $this->response->redirect($redirect);
            return;
        }

        if ($record === null) {
            $this->response->notFound('台帳が見つかりません。');
            return;
        }

        if ($saleAmount !== '' && (!ctype_digit($saleAmount) || strlen($saleAmount) > 12)) {
            $session->setFlash('error', '販売金額は数値（円）で入力してください。');
            $this->response->redirect($redirect);
            return;
        }

        if ($memberCode !== ''
            && (new \FuryoDacho\Models\Member($this->pdo))->findByCode($tenantId, $memberCode) === null) {
            $session->setFlash('error', '会員番号「' . $memberCode . '」は登録されていません。');
            $this->response->redirect($redirect);
            return;
        }

        if ($soldAt === '') {
            $soldAt = $sale['sold_at'];
        } else {
            $soldAt = str_replace('T', ' ', $soldAt);
            $ts = strtotime($soldAt);
            if ($ts === false) {
                $session->setFlash('error', '販売日時の形式が不正です。');
                $this->response->redirect($redirect);
                return;
            }
            $soldAt = date('Y-m-d H:i:s', $ts);
        }

        if (mb_strlen($note) > 512) {
            $session->setFlash('error', '備考は512文字以内で入力してください。');
            $this->response->redirect($redirect);
            return;
        }

        // 残数チェックと更新は、台帳行をロックしたトランザクション内で行う
        // （同時に POS 等で販売された場合でも、最新の販売数で検証して在庫超過を防ぐ）
        $saleModel->ensureSchema();
        $this->pdo->beginTransaction();
        try {
            $locked = $saleModel->lockLedgers([$ledgerId], $tenantId);
            $saleNow = $saleModel->findById($saleId, $tenantId); // ロック後の最新値
            if (!isset($locked[$ledgerId]) || $saleNow === null) {
                $this->pdo->rollBack();
                $this->response->notFound('販売記録が見つかりません。');
                return;
            }

            // この販売自身を除いた販売済数で上限を計算
            $soldOther = $locked[$ledgerId]['sold'] - (int)$saleNow['quantity'];
            $maxQty    = $locked[$ledgerId]['quantity'] - $soldOther;
            if ($quantity > $maxQty) {
                $this->pdo->rollBack();
                $session->setFlash('error', '販売個数が在庫（この記録分を除き残' . max(0, $maxQty) . '点）を超えています。');
                $this->response->redirect($redirect);
                return;
            }

            $saleModel->update($saleId, $tenantId, [
                'member_code' => $memberCode,
                'quantity'    => $quantity,
                'sale_amount' => $saleAmount,
                'sold_at'     => $soldAt,
                'note'        => $note,
            ]);
            $this->pdo->commit();
        } catch (\Throwable $e) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            $session->setFlash('error', '販売記録の修正に失敗しました。もう一度お試しください。');
            $this->response->redirect($redirect);
            return;
        }

        // 変更前の値はロック後に読み直した値を記録する（直前に別の修正があっても正しく残す）
        $saleBefore = $saleNow ?? $sale;
        (new AuditLog($this->pdo))->log(
            $tenantId, $this->auth->getUserId(), $this->auth->user()['display_name'],
            null, 'edit', $saleId,
            ['kind' => 'sale', 'quantity' => $saleBefore['quantity'], 'sale_amount' => $saleBefore['sale_amount'], 'sold_at' => $saleBefore['sold_at'], 'member_code' => $saleBefore['member_code'] ?? null],
            ['kind' => 'sale', 'quantity' => $quantity, 'sale_amount' => $saleAmount, 'sold_at' => $soldAt, 'member_code' => $memberCode],
            $this->request->ip()
        );

        $session->setFlash('success', '販売記録を修正しました。（在庫数に反映されます）');
        $this->response->redirect($redirect);
    }

    /**
     * 販売記録の削除（管理者のみ・記録訂正用）
     */
    public function saleDelete(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $saleId   = (int)$this->request->post('sale_id');
        $session  = new \FuryoDacho\Core\Session();

        $saleModel = new \FuryoDacho\Models\Sale($this->pdo);
        $sale      = $saleModel->findById($saleId, $tenantId);

        if ($sale === null) {
            $this->response->notFound('販売記録が見つかりません。');
            return;
        }

        if ($this->redirectIfPosSale($sale)) {
            return;
        }

        $saleModel->delete($saleId, $tenantId);

        (new AuditLog($this->pdo))->log(
            $tenantId, $this->auth->getUserId(), $this->auth->user()['display_name'],
            null, 'delete', $saleId,
            ['kind' => 'sale', 'ledger_id' => $sale['ledger_id'], 'quantity' => $sale['quantity'], 'sale_amount' => $sale['sale_amount']],
            null,
            $this->request->ip()
        );

        $session->setFlash('success', '販売記録を削除しました。（在庫数に反映されます）');
        $this->response->redirect('/index.php?page=ledger.show&id=' . (int)$sale['ledger_id']);
    }

    /**
     * POST の文字列項目（配列等が送られた場合は既定値）
     * （以前は (string) で変換しており、配列を送ると文字列 "Array" として扱われていた）
     */
    private function postStr(string $key, string $default = ''): string
    {
        $v = $this->request->post($key, $default);
        return is_string($v) ? trim($v) : $default;
    }

    /**
     * POSレジで会計した販売記録なら、取引詳細へ案内して true を返す
     *
     * POSの販売記録はレシート（会計）と金額・数量が食い違わないよう個別の修正・削除を禁止し、
     * POSの取引取消で訂正する。
     */
    private function redirectIfPosSale(array $sale): bool
    {
        if (empty($sale['transaction_id'])) {
            return false;
        }
        (new \FuryoDacho\Core\Session())->setFlash('error', 'この販売記録はPOSレジの会計に含まれるため、個別に修正・削除できません。POSの取引詳細から「取消」して会計し直してください。');
        $this->response->redirect('/index.php?page=pos.show&id=' . (int)$sale['transaction_id']);
        return true;
    }

    public function show(int $id = 0): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        $id       = $id ?: (int)$this->request->get('id');
        $record   = (new Ledger($this->pdo))->findById($id, $tenantId);

        if ($record === null) {
            $this->response->notFound('台帳が見つかりません。');
            return;
        }

        // 過去年度レコードは編集不可のため、編集ボタン自体を出さない
        $ledgerModel       = new Ledger($this->pdo);
        $currentFiscalYear = $ledgerModel->getFiscalYear(date('Y-m-d'));
        $isCurrentYear     = (int)$record['fiscal_year'] === $currentFiscalYear;

        $canEdit = $isCurrentYear
            && ($this->auth->isAdmin() || (int)$record['registered_by'] === $this->auth->getUserId());
        $isAdmin = $this->auth->isAdmin();
        $itemTypeLabels = \FuryoDacho\Models\ItemCategory::STATUTORY;
        $itemPhotos = (new LedgerFile($this->pdo))->findAllByLedgerAndType($id, $tenantId, 'item_photo');

        // 在庫管理: 販売記録と残数
        $saleModel    = new \FuryoDacho\Models\Sale($this->pdo);
        $sales        = $saleModel->findByLedger($id, $tenantId);
        $soldQuantity = $saleModel->soldQuantity($id, $tenantId);
        $remaining    = max(0, (int)$record['quantity'] - $soldQuantity);

        $this->render('ledger/show', [
            'ledger'         => $record,
            'record'         => $record,
            'canEdit'        => $canEdit,
            'isAdmin'        => $isAdmin,
            'itemTypeLabels' => $itemTypeLabels,
            'itemPhotos'     => $itemPhotos,
            'sales'          => $sales,
            'soldQuantity'   => $soldQuantity,
            'remaining'      => $remaining,
            'csrf_token'     => $this->generateCsrfToken(),
        ]);
    }

    /**
     * 台帳編集フォーム（権限チェックあり）
     *
     * @param int $id
     */
    public function edit(int $id = 0): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();
        $role     = $this->auth->getRole();
        $id       = $id ?: (int)$this->request->get('id');

        $ledgerModel = new Ledger($this->pdo);
        $record      = $ledgerModel->findById($id, $tenantId);

        if ($record === null) {
            $this->response->notFound('台帳が見つかりません。');
            return;
        }

        // 権限チェック: user ロールは自分の登録レコードのみ編集可
        if ($role !== 'admin' && (int)$record['registered_by'] !== $userId) {
            $this->response->forbidden('自分が登録したレコードのみ編集できます。');
            return;
        }

        // 過去年度チェック
        $currentFiscalYear = $ledgerModel->getFiscalYear(date('Y-m-d'));
        if ((int)$record['fiscal_year'] !== $currentFiscalYear) {
            $this->response->forbidden('過去年度のデータは編集できません。');
            return;
        }

        $branches = (new Branch($this->pdo))->findAllByTenant($tenantId);
        $categoryOptions = (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId);
        $itemPhotoCount  = (new LedgerFile($this->pdo))->countByLedgerAndType($id, $tenantId, 'item_photo');

        $this->render('ledger/form', [
            'ledger'          => $record,
            'branches'        => $branches,
            'categoryOptions' => $categoryOptions,
            'itemPhotoCount'  => $itemPhotoCount,
            'csrf_token'      => $this->generateCsrfToken(),
            'errors'          => [],
        ]);
    }

    /**
     * 台帳更新処理（POST）
     * バリデーション → 更新 → AuditLog（変更前後の値）記録。
     *
     * @param int $id
     */
    public function update(int $id = 0): void
    {
        $this->auth->requireAuth();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();
        $role     = $this->auth->getRole();
        // フォームの hidden の id を優先し、無ければ送信先URLの id を使う
        $id       = $id ?: ((int)$this->request->post('id') ?: (int)$this->request->get('id'));
        $input    = $this->request->all();

        // branch_id が現在テナントの拠点か検証（他テナントへの不正紐付け防止）
        if (!empty($input['branch_id']) && !$this->branchBelongsToTenant((int)$input['branch_id'], $tenantId)) {
            $this->response->forbidden('無効な拠点が指定されました。');
            return;
        }

        $errors = $this->validateLedgerInput($input);

        if (!empty($errors)) {
            $ledgerModel = new Ledger($this->pdo);
            $record      = $ledgerModel->findById($id, $tenantId);
            if ($record === null) {
                // 対象が無いまま再表示すると新規登録フォームとして表示され、
                // 「保存」で別の台帳が新規登録されてしまうため 404 にする
                $this->response->notFound('台帳が見つかりません。');
                return;
            }
            $branches    = (new Branch($this->pdo))->findAllByTenant($tenantId);
            $this->render('ledger/form', [
                'ledger'          => $record,
                'branches'        => $branches,
                'categoryOptions' => (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId),
                'csrf_token'      => $this->generateCsrfToken(),
                'errors'          => $errors,
                'input'           => $input,
                'itemPhotoCount'  => (new LedgerFile($this->pdo))->countByLedgerAndType($id, $tenantId, 'item_photo'),
            ]);
            return;
        }

        $ledgerModel = new Ledger($this->pdo);
        $before      = $ledgerModel->findById($id, $tenantId);

        if ($before === null) {
            $this->response->notFound('台帳が見つかりません。');
            return;
        }

        try {
            $ledgerModel->update($id, $tenantId, $userId, $role, $input);
        } catch (\PDOException $e) {
            // DBエラーは内部情報（SQL文等）を画面に出さず、入力内容を残したままフォームを再表示する。
            // ロック待ちのタイムアウト・デッドロックだけは「再試行で解決する」旨を案内する
            error_log('LedgerController::update failed: ' . $e->getMessage());
            $dbCode  = (int)($e->errorInfo[1] ?? 0);
            $message = in_array($dbCode, [1205, 1213], true)
                ? '他の操作（会計・販売登録など）と重なったため保存できませんでした。もう一度「保存」してください。'
                : '台帳を保存できませんでした。入力内容（文字数・数値の範囲など）を確認してください。';
            $this->render('ledger/form', [
                'ledger'          => $before,
                'branches'        => (new Branch($this->pdo))->findAllByTenant($tenantId),
                'categoryOptions' => (new \FuryoDacho\Models\ItemCategory($this->pdo))->buildOptions($tenantId),
                'csrf_token'      => $this->generateCsrfToken(),
                'errors'          => ['general' => $message],
                'input'           => $input,
                'itemPhotoCount'  => (new LedgerFile($this->pdo))->countByLedgerAndType($id, $tenantId, 'item_photo'),
            ]);
            return;
        } catch (\RuntimeException $e) {
            $this->response->forbidden($e->getMessage());
            return;
        }

        // Phase4: ファイルアップロード処理（更新時は新規ファイルがあれば追加保存）
        $fileErrors = [];
        $this->saveUploadedFiles($id, $tenantId, $fileErrors);
        if (!empty($fileErrors)) {
            (new \FuryoDacho\Core\Session())->setFlash(
                'error',
                '台帳は更新されましたが、添付ファイルの保存に失敗しました: ' . implode(' / ', $fileErrors)
            );
        }

        // 承認待ちの台帳に、編集で本人確認情報（書類種別・書類の画像）を追加した場合や
        // 本人確認済みの会員に紐付けた場合は、承認待ちを解除する
        // （以前は本人確認情報を後から登録しても「承認待ち」のまま残っていた）
        $approvalCleared = false;
        if (($before['approval_status'] ?? 'none') === 'pending') {
            $hasIdNow = !empty($input['id_document_type'])
                || (new LedgerFile($this->pdo))->countByLedgerAndType($id, $tenantId, 'id_document') > 0;
            if (!$hasIdNow && !empty($input['member_code'])) {
                $m = (new \FuryoDacho\Models\Member($this->pdo))->findByCode($tenantId, (string)$input['member_code']);
                $hasIdNow = $m !== null && !empty($m['id_document_type']);
            }
            if ($hasIdNow) {
                $this->pdo->prepare(
                    "UPDATE `ledgers` SET `approval_status` = 'none' WHERE `id` = ? AND `tenant_id` = ? AND `approval_status` = 'pending'"
                )->execute([$id, $tenantId]);
                $approvalCleared = true;
            }
        }

        // 監査ログ（変更前後の値）
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $userId,
            $this->auth->user()['display_name'],
            null,
            'edit',
            $id,
            $this->sanitizeForLog($before),
            $this->sanitizeForLog($input),
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash('success', '台帳 #' . $id . ' の変更を保存しました。'
            . ($approvalCleared ? '本人確認情報が登録されたため、承認待ちを解除しました。' : ''));
        $this->response->redirect('/index.php?page=ledger.show&id=' . $id);
    }

    /**
     * 台帳削除（管理者のみ・パスワード再入力確認）
     * POST でパスワードを受け取り、Auth::verifyCurrentPassword() で検証してから論理削除する。
     *
     * @param int $id
     */
    public function delete(int $id = 0): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $userId   = $this->auth->getUserId();
        $id       = $id ?: (int)$this->request->post('id');
        // パスワード再確認（$_POST から直接取得してエスケープを回避。配列等は不一致として扱う）
        $rawPassword = is_string($_POST['confirm_password'] ?? null) ? $_POST['confirm_password'] : '';
        if (!$this->auth->verifyCurrentPassword($rawPassword)) {
            // フラッシュメッセージでエラーを伝えて詳細画面に戻す
            $session = new \FuryoDacho\Core\Session();
            $session->setFlash('error', 'パスワードが正しくありません。');
            $this->response->redirect('/index.php?page=ledger.show&id=' . $id);
            return;
        }

        $ledgerModel = new Ledger($this->pdo);
        $before      = $ledgerModel->findById($id, $tenantId);

        if ($before === null) {
            $this->response->notFound('台帳が見つかりません。');
            return;
        }

        try {
            $ledgerModel->softDelete($id, $tenantId, $userId);
        } catch (\RuntimeException $e) {
            $this->response->notFound($e->getMessage());
            return;
        }

        // 監査ログ（削除前の値を before_value に記録）
        (new AuditLog($this->pdo))->log(
            $tenantId,
            $userId,
            $this->auth->user()['display_name'],
            null,
            'delete',
            $id,
            $this->sanitizeForLog($before),
            null,
            $this->request->ip()
        );

        (new \FuryoDacho\Core\Session())->setFlash('success', '台帳 #' . $id . '「' . (string)$before['item_name'] . '」を削除しました。（監査ログに削除前の内容が記録されています）');
        $this->response->redirect('/index.php?page=ledger');
    }

    // ----------------------------------------------------------------
    // 内部ユーティリティ
    // ----------------------------------------------------------------

    /**
     * 台帳入力バリデーション
     *
     * @param array $input
     * @return array エラーメッセージ（空配列なら正常）
     */

    /**
     * 指定 branch_id が現在テナントに属するか確認する
     */
    private function branchBelongsToTenant(int $branchId, int $tenantId): bool
    {
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) FROM `branches` WHERE `id` = ? AND `tenant_id` = ?"
        );
        $stmt->execute([$branchId, $tenantId]);
        return (int)$stmt->fetchColumn() > 0;
    }

    private function validateLedgerInput(array &$input): array
    {
        $errors = [];

        // 台帳の入力項目はすべて単一の値。配列等が送られた場合は不正な入力として拒否する
        // （以前は文字列 "Array" として法定帳簿に保存されていた）
        foreach ($input as $key => $value) {
            if (!is_scalar($value) && $value !== null) {
                $errors[$key]      = '入力値の形式が不正です。';
                $errors['general'] = '入力値の形式が不正です。もう一度入力してください。';
                $input[$key]       = '';
            }
        }

        // 必須チェック
        foreach (self::REQUIRED_FIELDS as $field) {
            if (!isset($input[$field]) || $input[$field] === '') {
                $errors[$field] = $this->fieldLabel($field) . ' は必須です。';
            }
        }

        // 取引種別は定義済みの値のみ（以前は検証が無く、不正な値でDBエラー
        // 「台帳を登録できませんでした」になるか、厳格モードでないDBでは空の種別が保存されていた）
        if (empty($errors['transaction_type']) && isset($input['transaction_type'])
            && !in_array($input['transaction_type'], ['buy', 'exchange', 'consignment', 'other'], true)) {
            $errors['transaction_type'] = '取引種別の値が無効です。';
        }

        // 型チェック（エラーがない場合のみ実施）
        if (empty($errors['quantity']) && isset($input['quantity'])) {
            if (!ctype_digit((string)$input['quantity']) || (int)$input['quantity'] <= 0) {
                $errors['quantity'] = '数量は正の整数で入力してください。';
            } elseif (strlen(ltrim((string)$input['quantity'], '0')) > 9) {
                // DBの列（INT UNSIGNED）に収まる範囲に制限する
                $errors['quantity'] = '数量は999,999,999以下で入力してください。';
            }
        }

        if (empty($errors['transaction_amount']) && isset($input['transaction_amount'])) {
            if (!is_numeric($input['transaction_amount']) || (float)$input['transaction_amount'] <= 0) {
                $errors['transaction_amount'] = '取引金額は正の数値で入力してください。';
            } elseif (round((float)$input['transaction_amount']) >= 1e12) { // 小数は列で丸められるため丸め後で判定
                // DBの列（DECIMAL(12,0)）に収まる範囲に制限する
                $errors['transaction_amount'] = '取引金額は999,999,999,999円以下で入力してください。';
            }
        }

        // 相手方区分（個人／法人）
        $cpType = $input['counterpart_type'] ?? 'individual';
        if (!in_array($cpType, ['individual', 'corporate'], true)) {
            $errors['counterpart_type'] = '相手方区分の値が不正です。';
            $cpType = 'individual';
        }

        if ($cpType === 'corporate') {
            // 法人: 担当者名が必須（職業・年齢は不要）
            if (empty($input['counterpart_contact_name']) || trim((string)$input['counterpart_contact_name']) === '') {
                $errors['counterpart_contact_name'] = '法人の場合は担当者名が必須です。';
            }
        } else {
            // 個人: 職業・年齢が必須（古物営業法上の記録事項）
            if (empty($input['counterpart_occupation']) || trim((string)$input['counterpart_occupation']) === '') {
                $errors['counterpart_occupation'] = '相手方職業 は必須です。';
            }
            if (!isset($input['counterpart_age']) || $input['counterpart_age'] === '') {
                $errors['counterpart_age'] = '相手方年齢 は必須です。';
            }
        }

        if (empty($errors['counterpart_age']) && isset($input['counterpart_age']) && $input['counterpart_age'] !== '') {
            if (!ctype_digit((string)$input['counterpart_age']) || (int)$input['counterpart_age'] <= 0) {
                $errors['counterpart_age'] = '相手方年齢は正の整数で入力してください。';
            } elseif ((int)$input['counterpart_age'] > 150) {
                $errors['counterpart_age'] = '相手方年齢は150以下で入力してください。';
            }
        }

        // マイナンバーカードの場合、個人番号は法令上記録禁止のため番号を強制的に破棄。
        // 「未登録（本人確認をスキップ）」の場合も書類番号だけが残らないよう破棄する
        if (in_array(($input['id_document_type'] ?? ''), ['my_number', ''], true)) {
            $input['id_document_number'] = '';
        }

        // 本人確認書類種別: 書類の種別か「未登録（本人確認をスキップ）」のどちらかを明示的に選ぶ。
        // 未選択（"__unset"）のまま送信された場合、以前は「値が不正です」とだけ表示され原因が分からなかった
        if (($input['id_document_type'] ?? '') === '__unset') {
            // 再表示では未選択のままにする（「未登録」を選んだ状態で戻すと、誤ってスキップしやすいため）
            $errors['id_document_type'] = '確認書類種別を選択してください（本人確認をしない場合は「未登録（本人確認をスキップ）」を選択）。';
        } elseif (!empty($input['id_document_type']) && !in_array($input['id_document_type'], self::DOC_TYPES, true)) {
            $errors['id_document_type'] = '本人確認書類種別の値が不正です。';
        }

        // 本人確認書類「その他」は書類の内容（例: 社員証）を記録する（確認方法の記録のため必須）
        if (($input['id_document_type'] ?? '') === 'other'
            && trim((string)($input['id_document_type_note'] ?? '')) === '') {
            $errors['id_document_type_note'] = '確認書類種別で「その他」を選択した場合は、書類の内容を入力してください。';
        }

        // 販売予定価格（任意・POSレジの単価の初期値）
        if (isset($input['sale_price']) && $input['sale_price'] !== '') {
            $sp = str_replace([',', '，'], '', mb_convert_kana((string)$input['sale_price'], 'n', 'UTF-8'));
            if (!ctype_digit($sp)) {
                $errors['sale_price'] = '販売予定価格は0以上の整数（円）で入力してください。';
            } elseif (strlen(ltrim($sp, '0')) > 12) {
                $errors['sale_price'] = '販売予定価格は999,999,999,999円以下で入力してください。';
            } else {
                $input['sale_price'] = (string)(int)$sp;
            }
        }

        // 文字数上限（DBの列長。超過するとDBエラーで保存できないため、入力段階で案内する）
        $maxLengths = [
            'transaction_type_note'    => 255,
            'item_category_note'       => 255,
            'item_name'                => 255,
            'counterpart_name'         => 255,
            'counterpart_address'      => 512,
            'counterpart_occupation'   => 255,
            'counterpart_phone'        => 20,
            'counterpart_contact_name' => 255,
            'id_document_number'       => 64,
            'id_document_type_note'    => 255,
        ];
        foreach ($maxLengths as $field => $max) {
            if (empty($errors[$field]) && isset($input[$field]) && is_string($input[$field])
                && mb_strlen($input[$field]) > $max) {
                $errors[$field] = $this->fieldLabel($field) . 'は' . $max . '文字以内で入力してください。';
            }
        }
        // 長文項目（TEXT列: 65,535バイトまで）
        foreach (['item_description' => '品目の説明', 'counterpart_note' => '相手方の備考'] as $field => $label) {
            if (isset($input[$field]) && is_string($input[$field]) && strlen($input[$field]) > 65535) {
                $errors[$field] = $label . 'が長すぎます（全角で約2万文字まで）。';
            }
        }

        // 文字数上限（任意項目）
        if (!empty($input['serial_number']) && mb_strlen((string)$input['serial_number']) > 100) {
            $errors['serial_number'] = 'シリアル番号は100文字以内で入力してください。';
        }
        if (!empty($input['member_code']) && mb_strlen((string)$input['member_code']) > 50) {
            $errors['member_code'] = '会員番号は50文字以内で入力してください。';
        }
        if (!empty($input['counterpart_account']) && mb_strlen((string)$input['counterpart_account']) > 255) {
            $errors['counterpart_account'] = '取引アカウントは255文字以内で入力してください。';
        }

        if (empty($errors['transaction_date']) && isset($input['transaction_date'])) {
            $d = \DateTime::createFromFormat('Y-m-d', $input['transaction_date']);
            if (!$d || $d->format('Y-m-d') !== $input['transaction_date']) {
                $errors['transaction_date'] = '取引年月日は YYYY-MM-DD 形式で入力してください。';
            }
        }

        // 古物の種類: このテナントで有効な値か（法定13区分 / 独自区分 / other）
        if (empty($errors['item_category']) && !empty($input['item_category'])) {
            $catModel = new \FuryoDacho\Models\ItemCategory($this->pdo);
            if (!$catModel->isValidValue($this->auth->getTenantId(), (string)$input['item_category'])) {
                $errors['item_category'] = '古物区分の値が無効です。';
            }
        }

        // 古物の種類 = "other" の場合は自由記述必須
        if (
            isset($input['item_category']) && $input['item_category'] === 'other'
            && (empty($input['item_category_note']) || trim((string)$input['item_category_note']) === '')
        ) {
            $errors['item_category_note'] = '古物の種類で「その他」を選択した場合は自由記述が必須です。';
        }

        // transaction_type = "other" の場合は transaction_type_note 必須
        if (
            isset($input['transaction_type']) && $input['transaction_type'] === 'other'
            && (empty($input['transaction_type_note']) || trim($input['transaction_type_note']) === '')
        ) {
            $errors['transaction_type_note'] = '取引種別がその他の場合は補足説明が必須です。';
        }

        return $errors;
    }

    /**
     * フィールド名を日本語ラベルに変換
     *
     * @param string $field
     * @return string
     */
    private function fieldLabel(string $field): string
    {
        $map = [
            'transaction_date'       => '取引年月日',
            'transaction_type'       => '取引種別',
            'item_category'          => '古物区分',
            'item_name'              => '品名',
            'quantity'               => '数量',
            'transaction_amount'     => '取引金額',
            'counterpart_name'       => '相手方氏名',
            'counterpart_address'    => '相手方住所',
            'counterpart_occupation' => '相手方職業',
            'counterpart_age'        => '相手方年齢',
            'id_document_type'       => '本人確認書類種別',
            'id_document_number'     => '本人確認書類番号',
            'transaction_type_note'  => '取引種別の補足',
            'item_category_note'     => '古物区分の補足',
            'counterpart_phone'      => '相手方電話番号',
            'counterpart_contact_name' => '担当者名',
            'id_document_type_note'  => '確認書類の内容',
            'sale_price'             => '販売予定価格',
        ];
        return $map[$field] ?? $field;
    }

    /**
     * アップロードファイルを暗号化保存して LedgerFile レコードを作成する
     *
     * $_FILES['id_document_file'] と $_FILES['receipt_form_file'] を処理する。
     * ファイルが未選択（UPLOAD_ERR_NO_FILE）の場合はスキップする。
     * エラーが発生した場合は $errors 配列にメッセージを追記する（処理は継続）。
     *
     * @param int   $ledgerId 保存対象の台帳 ID
     * @param int   $tenantId テナント ID
     * @param array &$errors  エラーメッセージ配列（参照渡し）
     */
    private function saveUploadedFiles(int $ledgerId, int $tenantId, array &$errors): void
    {
        $fileFields = [
            'id_document_file'   => 'id_document',
            'receipt_form_file'  => 'purchase_receipt',
        ];

        foreach ($fileFields as $fieldName => $fileType) {
            if (!isset($_FILES[$fieldName])) {
                continue;
            }

            $file = $_FILES[$fieldName];

            // ファイル未選択はスキップ
            if ($file['error'] === UPLOAD_ERR_NO_FILE) {
                continue;
            }

            try {
                $uploader = new FileUpload();
                $saved    = $uploader->save($file, $tenantId, $ledgerId, $fileType);

                $config = require __DIR__ . '/../../config/config.php';

                (new LedgerFile($this->pdo))->create([
                    'ledger_id'         => $ledgerId,
                    'tenant_id'         => $tenantId,
                    'file_type'         => $fileType,
                    'original_filename' => $saved['original_filename'],
                    'stored_filename'   => $saved['stored_filename'],
                    'file_path'         => $saved['file_path'],
                    'iv'                => $saved['iv'],
                    'file_size'         => $saved['file_size'],
                    'mime_type'         => $saved['mime_type'],
                ]);
            } catch (\RuntimeException $e) {
                $errors[$fieldName] = $e->getMessage();
            }
        }

        // ============ 商品画像（複数・任意） ============
        $this->saveItemPhotos($ledgerId, $tenantId, $errors);
    }

    /** 商品画像1点あたりの上限（25MB） */
    private const PHOTO_MAX_SIZE = 26214400;
    /** 商品画像の最大点数 */
    private const PHOTO_MAX_COUNT = 20;
    /** 商品画像として許可するMIME */
    private const PHOTO_MIMES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];

    /**
     * 商品画像（item_photos[]）を保存する
     * 1点25MBまで・台帳あたり20点まで。画像形式のみ。
     */
    private function saveItemPhotos(int $ledgerId, int $tenantId, array &$errors): void
    {
        if (!isset($_FILES['item_photos']) || !is_array($_FILES['item_photos']['name'] ?? null)) {
            return;
        }

        $names = $_FILES['item_photos']['name'];
        $count = count($names);
        if ($count === 0) {
            return;
        }

        $fileModel = new LedgerFile($this->pdo);
        $existing  = $fileModel->countByLedgerAndType($ledgerId, $tenantId, 'item_photo');

        $saved = 0;
        for ($i = 0; $i < $count; $i++) {
            $file = [
                'name'     => $_FILES['item_photos']['name'][$i],
                'type'     => $_FILES['item_photos']['type'][$i],
                'tmp_name' => $_FILES['item_photos']['tmp_name'][$i],
                'error'    => $_FILES['item_photos']['error'][$i],
                'size'     => $_FILES['item_photos']['size'][$i],
            ];

            if ($file['error'] === UPLOAD_ERR_NO_FILE) {
                continue;
            }

            // 点数上限
            if ($existing + $saved >= self::PHOTO_MAX_COUNT) {
                $errors['item_photos'] = '商品画像は1件の台帳につき最大' . self::PHOTO_MAX_COUNT . '点までです。超過分は保存されませんでした。';
                break;
            }

            // PHP側のアップロードエラー（サイズ超過等）
            if ($file['error'] !== UPLOAD_ERR_OK) {
                $errors['item_photos'] = '商品画像「' . $file['name'] . '」のアップロードに失敗しました（サーバーのサイズ上限超過等）。';
                continue;
            }

            // 25MB制限
            if ((int)$file['size'] > self::PHOTO_MAX_SIZE) {
                $errors['item_photos'] = '商品画像「' . $file['name'] . '」は25MBを超えているため保存されませんでした。';
                continue;
            }

            // 画像形式チェック
            $mime = function_exists('finfo_open')
                ? (function ($tmp) { $f = finfo_open(FILEINFO_MIME_TYPE); $m = finfo_file($f, $tmp); finfo_close($f); return $m; })($file['tmp_name'])
                : ($file['type'] ?? '');
            if (!in_array($mime, self::PHOTO_MIMES, true)) {
                $errors['item_photos'] = '商品画像「' . $file['name'] . '」は対応していない形式です（JPEG/PNG/GIF/WebPのみ）。';
                continue;
            }

            try {
                $uploader = new FileUpload();
                $savedFile = $uploader->save($file, $tenantId, $ledgerId, 'item_photo');

                $fileModel->create([
                    'ledger_id'         => $ledgerId,
                    'tenant_id'         => $tenantId,
                    'file_type'         => 'item_photo',
                    'original_filename' => $savedFile['original_filename'],
                    'stored_filename'   => $savedFile['stored_filename'],
                    'file_path'         => $savedFile['file_path'],
                    'iv'                => $savedFile['iv'],
                    'file_size'         => $savedFile['file_size'],
                    'mime_type'         => $savedFile['mime_type'],
                ]);
                $saved++;
            } catch (\RuntimeException $e) {
                $errors['item_photos'] = '商品画像「' . $file['name'] . '」: ' . $e->getMessage();
            }
        }
    }

    /**
     * 監査ログ用に機密情報を除外したデータを返す
     *
     * @param array $data
     * @return array
     */
    private function sanitizeForLog(array $data): array
    {
        $safe = $data;
        // 本人確認書類番号はログに生値を記録しない
        if (isset($safe['id_document_number'])) {
            $safe['id_document_number'] = '***';
        }
        // パスワード系キーを除外
        unset($safe['_csrf_token'], $safe['password'], $safe['confirm_password']);
        return $safe;
    }
}
