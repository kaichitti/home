<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Models\Member;
use FuryoDacho\Models\AuditLog;
use FuryoDacho\Core\Session;

/**
 * 会員管理コントローラー
 * 相手方情報・本人確認情報の引用元となる会員を管理する。
 * 閲覧・登録・編集は全ユーザー、削除は管理者のみ。
 */
class MemberController extends BaseController
{
    private const DOC_TYPES = [
        'driver_license', 'my_number', 'passport', 'health_insurance',
        'residence_card', 'residence_status', 'special_permanent', 'other',
    ];

    public function index(): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        $keyword  = trim((string)$this->request->get('keyword', ''));
        $page     = max(1, (int)$this->request->get('p', 1));
        $perPage  = 50;

        $model   = new Member($this->pdo);
        $members = $model->search($tenantId, $keyword, $perPage, ($page - 1) * $perPage);
        $total   = $model->countAll($tenantId, $keyword);

        // POSでの購入実績（回数・累計額・最終購入日）
        $stats = [];
        try {
            \FuryoDacho\Models\PosSchema::ensure($this->pdo);
            $stats = (new \FuryoDacho\Models\PosTransaction($this->pdo))->memberStats($tenantId, array_column($members, 'id'));
        } catch (\Throwable $e) {
            $stats = [];
        }

        $this->render('member/index', [
            'members'    => $members,
            'stats'      => $stats,
            'keyword'    => $keyword,
            'total'      => $total,
            'page'       => $page,
            'totalPages' => max(1, (int)ceil($total / $perPage)),
        ]);
    }

    /**
     * 会員詳細（基本情報・POSでの購入履歴・買取（台帳）履歴）
     */
    public function show(): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        $id       = (int)$this->request->get('id');
        $member   = (new Member($this->pdo))->findById($id, $tenantId);
        if ($member === null) {
            $this->response->notFound('会員が見つかりません（削除された可能性があります）。');
            return;
        }

        \FuryoDacho\Models\PosSchema::ensure($this->pdo);
        $txModel = new \FuryoDacho\Models\PosTransaction($this->pdo);
        $stats   = $txModel->memberStats($tenantId, [$id])[$id] ?? ['count' => 0, 'total' => 0, 'last_at' => null];
        $recent  = $txModel->search($tenantId, ['member_id' => $id], 1, 20);

        // 買取（台帳）: 会員番号で紐付いた台帳（スナップショットのため会員番号変更前の記録は含まれない）
        $stmt = $this->pdo->prepare(
            "SELECT `id`, `transaction_date`, `transaction_type`, `item_name`, `quantity`, `transaction_amount`
             FROM `ledgers`
             WHERE `tenant_id` = ? AND `member_code` = ? AND `deleted_at` IS NULL
             ORDER BY `transaction_date` DESC, `id` DESC LIMIT 20"
        );
        $stmt->execute([$tenantId, $member['member_code']]);
        $ledgers = $stmt->fetchAll();
        $stmt = $this->pdo->prepare(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(`transaction_amount`), 0) AS total FROM `ledgers`
             WHERE `tenant_id` = ? AND `member_code` = ? AND `deleted_at` IS NULL"
        );
        $stmt->execute([$tenantId, $member['member_code']]);
        $buy = $stmt->fetch() ?: ['cnt' => 0, 'total' => 0];

        $this->render('member/show', [
            'member'     => $member,
            'stats'      => $stats,
            'recent'     => $recent['rows'],
            'recentTotal'=> $recent['total'],
            'ledgers'    => $ledgers,
            'buyCount'   => (int)$buy['cnt'],
            'buyTotal'   => (int)$buy['total'],
            'activePage' => 'member',
        ]);
    }

    public function create(): void
    {
        $this->auth->requireAuth();
        $this->render('member/form', ['member' => null, 'errors' => []]);
    }

    public function store(): void
    {
        $this->auth->requireAuth();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $input    = $this->collectInput();
        $model    = new Member($this->pdo);

        // 会員番号が空欄なら自動採番（M-0001 形式。台帳からの同時登録と同じ規則）
        $autoCode = false;
        if ($input['member_code'] === '') {
            $input['member_code'] = $model->generateCode($tenantId);
            $autoCode = true;
        }

        $errors = $this->validate($tenantId, $input);

        if (!empty($errors)) {
            if ($autoCode) {
                $input['member_code'] = '';
            }
            $this->render('member/form', ['member' => null, 'errors' => $errors, 'input' => $input]);
            return;
        }

        try {
            $newId = $model->create($tenantId, $input);
        } catch (\PDOException $e) {
            // 同時に同じ番号が登録された場合など（一意制約違反）は入力内容を残して再表示する
            error_log('MemberController::store failed: ' . $e->getMessage());
            $this->render('member/form', [
                'member' => null,
                'errors' => ['member_code' => (int)($e->errorInfo[1] ?? 0) === 1062
                    ? 'この会員番号はすでに登録されています。'
                    : '会員を登録できませんでした。入力内容を確認してください。'],
                'input'  => $autoCode ? array_merge($input, ['member_code' => '']) : $input,
            ]);
            return;
        }

        (new AuditLog($this->pdo))->log(
            $tenantId, $this->auth->getUserId(), $this->auth->user()['display_name'],
            null, 'create', $newId, null,
            ['member_code' => $input['member_code'], 'name' => $input['name'], 'kind' => 'member'],
            $this->request->ip()
        );

        (new Session())->setFlash('success', '会員「' . $input['member_code'] . '」（' . $input['name'] . '）を登録しました。' . ($autoCode ? '（会員番号は自動採番）' : ''));
        $this->response->redirect('/index.php?page=member.show&id=' . $newId);
    }

    public function edit(): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        $id       = (int)$this->request->get('id');
        $member   = (new Member($this->pdo))->findById($id, $tenantId);

        if ($member === null) {
            $this->response->notFound('会員が見つかりません。');
            return;
        }

        $this->render('member/form', ['member' => $member, 'errors' => []]);
    }

    public function update(): void
    {
        $this->auth->requireAuth();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = (int)$this->request->post('id');
        $model    = new Member($this->pdo);
        $member   = $model->findById($id, $tenantId);

        if ($member === null) {
            $this->response->notFound('会員が見つかりません。');
            return;
        }

        $input  = $this->collectInput();
        $errors = $this->validate($tenantId, $input, $id);

        if (!empty($errors)) {
            $this->render('member/form', ['member' => $member, 'errors' => $errors, 'input' => $input]);
            return;
        }

        try {
            $model->update($id, $tenantId, $input);
        } catch (\PDOException $e) {
            error_log('MemberController::update failed: ' . $e->getMessage());
            $this->render('member/form', [
                'member' => $member,
                'errors' => ['member_code' => (int)($e->errorInfo[1] ?? 0) === 1062
                    ? 'この会員番号はすでに登録されています。'
                    : '会員情報を保存できませんでした。入力内容を確認してください。'],
                'input'  => $input,
            ]);
            return;
        }

        (new AuditLog($this->pdo))->log(
            $tenantId, $this->auth->getUserId(), $this->auth->user()['display_name'],
            null, 'edit', $id,
            ['member_code' => $member['member_code'], 'name' => $member['name'], 'kind' => 'member'],
            ['member_code' => $input['member_code'], 'name' => $input['name'], 'kind' => 'member'],
            $this->request->ip()
        );

        (new Session())->setFlash('success', '会員「' . $input['member_code'] . '」の情報を更新しました。');
        $this->response->redirect('/index.php?page=member.show&id=' . $id);
    }

    public function delete(): void
    {
        $this->auth->requireAdmin();
        $this->verifyCsrf();

        $tenantId = $this->auth->getTenantId();
        $id       = (int)$this->request->post('id');
        $model    = new Member($this->pdo);
        $member   = $model->findById($id, $tenantId);
        $session  = new Session();

        if ($member === null) {
            $session->setFlash('error', '会員が見つかりません。');
            $this->response->redirect('/index.php?page=member');
            return;
        }

        $model->delete($id, $tenantId);

        (new AuditLog($this->pdo))->log(
            $tenantId, $this->auth->getUserId(), $this->auth->user()['display_name'],
            null, 'delete', $id,
            ['member_code' => $member['member_code'], 'name' => $member['name'], 'kind' => 'member'],
            null,
            $this->request->ip()
        );

        $session->setFlash('success', '会員「' . $member['member_code'] . '」を削除しました。（過去の台帳記録は変わりません）');
        $this->response->redirect('/index.php?page=member');
    }

    /**
     * 会員番号から会員情報をJSONで返す（台帳フォームの引用ボタン用）
     */
    public function lookup(): void
    {
        $this->auth->requireAuth();

        $tenantId = $this->auth->getTenantId();
        $code     = trim((string)$this->request->get('code', ''));

        header('Content-Type: application/json; charset=UTF-8');

        // 会員番号の総当たりによる会員情報の列挙を防ぐ（1分間に30回まで）
        if (!\FuryoDacho\Helpers\RateLimiter::hit('member.lookup', 30, 60)) {
            http_response_code(429);
            echo json_encode(
                ['found' => false, 'message' => '短時間に照会が集中しています。しばらく待ってから再度お試しください。'],
                JSON_UNESCAPED_UNICODE
            );
            exit;
        }

        if ($code === '') {
            echo json_encode(['found' => false, 'message' => '会員番号を入力してください。'], JSON_UNESCAPED_UNICODE);
            exit;
        }

        $member = (new Member($this->pdo))->findByCode($tenantId, $code);

        if ($member === null) {
            echo json_encode(['found' => false, 'message' => '会員番号「' . $code . '」は登録されていません。'], JSON_UNESCAPED_UNICODE);
            exit;
        }

        echo json_encode([
            'found'  => true,
            'member' => [
                'member_code'        => $member['member_code'],
                'counterpart_type'   => $member['counterpart_type'],
                'name'               => $member['name'],
                'address'            => $member['address'] ?? '',
                'occupation'         => $member['occupation'] ?? '',
                'age'                => $member['age'] !== null ? (string)$member['age'] : '',
                'phone'              => $member['phone'] ?? '',
                'contact_name'       => $member['contact_name'] ?? '',
                'account'            => $member['account'] ?? '',
                'id_document_type'   => $member['id_document_type'] ?? '',
                // 本人確認書類番号はPIIのため応答に含めない（全ログインユーザーへの
                // 露出・列挙を防止）。登録の有無のみ真偽値で返す。
                'has_id_document_number' => !empty($member['id_document_number']),
            ],
        ], JSON_UNESCAPED_UNICODE);
        exit;
    }

    // ----------------------------------------------------------------

    private function collectInput(): array
    {
        $type = $this->request->post('counterpart_type', 'individual');
        $str  = function (string $key): string {
            $v = $this->request->post($key, '');
            return is_string($v) ? trim($v) : '';
        };
        return [
            'member_code'        => $str('member_code'),
            'counterpart_type'   => in_array($type, ['individual', 'corporate'], true) ? $type : 'individual',
            'name'               => $str('name'),
            'address'            => $str('address'),
            'occupation'         => $str('occupation'),
            'age'                => $str('age'),
            'phone'              => $str('phone'),
            'contact_name'       => $str('contact_name'),
            'account'            => $str('account'),
            'id_document_type'   => $str('id_document_type'),
            // マイナンバーカードの個人番号は法令上記録禁止のため強制的に破棄
            // 種別が未選択の場合も書類番号だけが残らないよう破棄する
            'id_document_number' => in_array($str('id_document_type'), ['my_number', ''], true)
                ? ''
                : $str('id_document_number'),
            'note'               => $str('note'),
        ];
    }

    private function validate(int $tenantId, array $input, ?int $excludeId = null): array
    {
        $errors = [];

        if ($input['member_code'] === '') {
            $errors['member_code'] = '会員番号を入力してください。';
        } elseif (mb_strlen($input['member_code']) > 50) {
            $errors['member_code'] = '会員番号は50文字以内で入力してください。';
        } elseif ((new Member($this->pdo))->existsCode($tenantId, $input['member_code'], $excludeId)) {
            $errors['member_code'] = 'この会員番号はすでに登録されています。';
        }

        if ($input['name'] === '') {
            $errors['name'] = $input['counterpart_type'] === 'corporate' ? '名称（会社名）を入力してください。' : '氏名を入力してください。';
        }

        if ($input['counterpart_type'] === 'corporate' && $input['contact_name'] === '') {
            $errors['contact_name'] = '法人の場合は担当者名を入力してください。';
        }

        // 文字数上限（DBの列長。超えると DB エラーで保存できないため入力段階で案内する）
        $maxLengths = [
            'name'               => [255, '氏名・名称'],
            'address'            => [512, '住所'],
            'occupation'         => [255, '職業'],
            'phone'              => [20,  '電話番号'],
            'contact_name'       => [255, '担当者名'],
            'account'            => [255, '取引アカウント'],
            'id_document_number' => [64,  '書類番号'],
        ];
        foreach ($maxLengths as $field => [$max, $label]) {
            if (empty($errors[$field]) && mb_strlen($input[$field]) > $max) {
                $errors[$field] = $label . 'は' . $max . '文字以内で入力してください。';
            }
        }
        if (strlen($input['note']) > 65535) {
            $errors['note'] = '備考が長すぎます（全角で約2万文字まで）。';
        }

        if ($input['age'] !== '' && (!ctype_digit($input['age']) || (int)$input['age'] > 150)) {
            $errors['age'] = '年齢は0〜150の数値で入力してください。';
        }

        if ($input['id_document_type'] !== '' && !in_array($input['id_document_type'], self::DOC_TYPES, true)) {
            $errors['id_document_type'] = '本人確認書類種別の値が不正です。';
        }

        return $errors;
    }
}
