<?php

namespace FuryoDacho\Core;

use FuryoDacho\Models\BaseModel;
use FuryoDacho\Models\User;
use FuryoDacho\Models\Tenant;
use FuryoDacho\Models\AuditLog;
use FuryoDacho\Helpers\LoginThrottle;

/**
 * 認証・認可管理クラス
 * - テナントユーザー（role: admin / user）
 * - システム管理者（完全別セッション）
 * - テナント間アクセス制御
 * - ログイン失敗ロック（5回で30分ロック。ただし信頼済みIPは対象外＝ロックDoS対策）
 * - IP単位・アカウント×IP単位のログイン試行制限（LoginThrottle）
 * - セッションタイムアウト管理
 */
class Auth
{
    /**
     * 公開されている初期パスワード（DEPLOY.md・setup.php に記載）。
     * このパスワードのままの利用は認めず、ログイン後に変更を強制する。
     */
    public const DEFAULT_PASSWORD = 'Admin7777';

    /**
     * 存在しないアカウント等への試行でも照合時間を揃えるためのダミー bcrypt ハッシュ
     * （応答時間の差によるアカウント存在判定＝ユーザー列挙を防ぐ）。
     * 実在アカウントのハッシュと同じコストにする必要があるため、PHP の既定コスト
     * （PHP 8.3 までは 10、8.4 以降は 12）ごとに用意し、実行環境の既定に合わせて選ぶ。
     * 実在アカウント側もログイン成功時に既定コストへ再ハッシュする。
     * ※ 毎回 password_hash() で生成すると、それ自体が余分な時間差になるため事前生成している。
     */
    private const DUMMY_HASHES = [
        10 => '$2y$10$rig8Pwvd93RXpWj9JsVL3.v7kJzRKUfY3KTQk9RHjo.O/3UWBRxiS',
        11 => '$2y$11$pnudhXEEIXp2wxDsINMA8.LWLvT1Xx9CLjj8yfigro7rUfGDVSuTm',
        12 => '$2y$12$.5Ru9KcZkaqSGXVtpIfXku74emfoYJgnHpRR4NhUe4A2zuhgtDeo2',
        13 => '$2y$13$7cQBXbT9Mg4yTiPlVMQRcuNlqYaHJP0vR4OfbveZX3SuYJqKH8DKW',
    ];

    private static function dummyHash(): string
    {
        $cost = defined('PASSWORD_BCRYPT_DEFAULT_COST') ? (int)PASSWORD_BCRYPT_DEFAULT_COST : 10;
        return self::DUMMY_HASHES[$cost] ?? self::DUMMY_HASHES[10];
    }

    private Session $session;
    private Session $adminSession;

    public function __construct()
    {
        $configPath         = defined('BASE_PATH')
            ? BASE_PATH . '/config/config.php'
            : __DIR__ . '/../../config/config.php';
        $config             = require $configPath;
        $this->session      = new Session($config['session_name'],       $config['session_timeout']);
        $this->adminSession = new Session($config['admin_session_name'], $config['session_timeout']);
    }

    // ----------------------------------------------------------------
    // テナントユーザー認証
    // ----------------------------------------------------------------

    /**
     * テナントコード + メール + パスワードでログイン
     *
     * @param string $tenantCode テナントコード
     * @param string $email      メールアドレス
     * @param string $password   平文パスワード
     * @return bool ログイン成功か否か
     */
    /**
     * 拠点ログインコードから拠点（と所属テナント）を特定する
     */
    private function findTenantByBranchCode(\PDO $pdo, string $code): ?array
    {
        try {
            // 旧バージョンではテナント間で同じコードを登録できたため、複数該当する
            // 場合は曖昧として扱い、任意のテナントへ誘導しない（ログイン不可）。
            $stmt = $pdo->prepare(
                "SELECT * FROM `branches` WHERE `login_code` = ? LIMIT 2"
            );
            $stmt->execute([$code]);
            $rows = $stmt->fetchAll();
            return count($rows) === 1 ? $rows[0] : null;
        } catch (\PDOException $e) {
            // login_code カラム未追加（マイグレーション未実行）環境では無視
            return null;
        }
    }

    public function login(string $tenantCode, string $email, string $password): bool
    {
        $pdo         = BaseModel::connect();
        $tenantModel = new Tenant($pdo);
        $userModel   = new User($pdo);
        $auditModel  = new AuditLog($pdo);
        $throttle    = new LoginThrottle($pdo);

        $ip = $this->getIpAddress();

        // まずテナントコードで特定。見つからなければ拠点ログインコードで特定する
        // （拠点別にログインコードを配布して運用できるようにするため）
        $tenant       = $tenantModel->findByCode($tenantCode);
        $branchScope  = null; // 拠点コードでログインした場合のみ拠点IDが入る

        if ($tenant === null) {
            $branch = $this->findTenantByBranchCode($pdo, $tenantCode);
            if ($branch !== null) {
                $tenant      = $tenantModel->findById((int)$branch['tenant_id']);
                $branchScope = (int)$branch['id'];
            }
        }

        // ユーザー検索（is_activeフィルタなし・ロック判定は後で行う）
        $user = ($tenant !== null && $tenant['status'] === 'active')
            ? $userModel->findByEmail((int)$tenant['id'], $email)
            : null;

        // 試行制限のアカウント識別子は、特定できたユーザーのIDで作る。
        // DBの照合順序（utf8mb4_unicode_ci）は大文字小文字・全角・アクセント・ゼロ幅文字等の
        // 表記ゆれを同じアカウントとみなすため、入力文字列のままだと表記を変えるだけで
        // 制限を回避できてしまう。テナントコード／拠点コードのどちらで入力しても同一になる。
        $accountKey = $user !== null
            ? LoginThrottle::accountKey('tenant', 'uid:' . $user['id'])
            : LoginThrottle::accountKey('tenant-input', $tenantCode, $email);

        // 照合の前に試行を予約する（IP単位・アカウント×IP単位）。
        // 先に記録してから数えるため、同時に大量のリクエストを送っても上限を超えて照合できない。
        // 拒否時もダミー照合を行う（即答すると、存在するアカウントだけが拒否される
        // 表記ゆれ入力との応答時間差から、メールアドレスの登録有無を推測できるため）。
        $reservation = $throttle->reserve($accountKey, $ip);
        if ($reservation === null) {
            password_verify($password, self::dummyHash());
            return false;
        }

        // 照合前に失敗する経路ではダミー照合を行い、応答時間の差によるアカウント存在判定を防ぐ
        // （予約した行がそのまま失敗記録になる）
        $fail = function () use ($password): bool {
            password_verify($password, self::dummyHash());
            return false;
        };

        if ($user === null) {
            return $fail();
        }

        // 拠点コードでログインした場合、その拠点所属のユーザーのみ許可
        // （オーナー/管理者はどの拠点コードからでもログイン可）
        if ($branchScope !== null
            && $user['role'] !== 'admin'
            && (int)($user['branch_id'] ?? 0) !== $branchScope) {
            return $fail();
        }

        // アカウント有効チェック
        if (!(int)$user['is_active']) {
            return $fail();
        }

        // アカウントロック（5回失敗で30分）
        // 照合の前に「ロック中でなければ失敗回数を1増やす」を1文で原子的に行い、
        // ロック中なら予約できない（並行リクエストでも5回を超えて照合させない）。
        // ロック中でも、過去にこのアカウントでログイン成功したIP（信頼済みIP）からの試行は
        // 照合を許可する（第三者が故意に失敗を重ねて正規ユーザーを締め出すロックDoSの防止）。
        // その経路で成功してもロックは解除しない（解除すると攻撃者に試行回数を再付与するため）。
        $userId = (int)$user['id'];
        $userModel->expireLock($userId); // 期限判定はDB側の時刻で行う
        $viaTrustedDuringLock = false;
        if (!$userModel->reserveAttempt($userId)) {
            if (!$throttle->isTrustedIp($accountKey, $ip)) {
                // ロック中の拒否はパスワードを照合しないため、組合せ単位の制限には数えない
                // （数えるとロック中の再試行で制限が延び、ロック解除後も締め出される）。
                // IP単位の制限には数える（存在しないアカウントへの試行と扱いを揃える）
                $throttle->markRefused((int)$reservation);
                return $fail();
            }
            $viaTrustedDuringLock = true;
        }

        // パスワード照合（失敗回数は予約済みのため、失敗時の追加処理は不要）
        if (!password_verify($password, $user['password_hash'])) {
            return false;
        }

        // 認証成功
        if (!$viaTrustedDuringLock) {
            $userModel->resetFailedAttempts($userId);
        }
        $userModel->updateLastLogin($userId);
        $throttle->recordSuccess($accountKey, $ip);

        // ハッシュのコストが現在の既定と違えば再ハッシュする（照合時間を揃えるため）。
        // 照合中に別の操作でパスワードが変更された場合は上書きしない（旧ハッシュ一致時のみ更新）
        if (password_needs_rehash($user['password_hash'], PASSWORD_BCRYPT)) {
            try {
                $userModel->updatePasswordHash(
                    $userId,
                    password_hash($password, PASSWORD_BCRYPT),
                    (string)$user['password_hash']
                );
            } catch (\Throwable $e) {
                // 再ハッシュ失敗はログインを妨げない
            }
        }

        // 公開されている初期パスワード（Admin7777）のままなら、変更するまで他の画面を使わせない。
        // 以前のバージョンは初期パスワードへの再設定を許していたため、ログイン時にも判定する。
        $mustChange = (int)$user['must_change_password'] === 1
            || hash_equals(self::DEFAULT_PASSWORD, $password);
        if ($mustChange && (int)$user['must_change_password'] !== 1) {
            try {
                $userModel->requirePasswordChange($userId);
            } catch (\Throwable $e) {
                // セッション側で強制するため続行
            }
        }

        // セッション再生成（固定化攻撃対策）
        $this->session->regenerate();
        $this->session->set('tenant_id',    (int)$tenant['id']);
        $this->session->set('user_id',      (int)$user['id']);
        $this->session->set('role',         $user['role']);
        $this->session->set('display_name', $user['display_name']);
        $this->session->set('branch_id',    $user['branch_id'] !== null ? (int)$user['branch_id'] : null);
        $this->session->set('must_change_password', $mustChange ? 1 : 0);

        // 監査ログ記録
        $auditModel->log(
            (int)$tenant['id'],
            (int)$user['id'],
            $user['display_name'],
            null,
            'login',
            null,
            null,
            null,
            $ip
        );

        return true;
    }

    /**
     * ログアウト処理
     */
    public function logout(): void
    {
        $this->session->destroy();
    }

    /**
     * ログイン済みかチェック（セッションタイムアウト管理含む）
     *
     * ログイン時にセッションへ焼き込んだ is_active / role を、リクエストごとに
     * 1回だけDBと突き合わせて再評価する。これにより、管理者がユーザーを
     * 無効化・削除・降格した場合に、当該ユーザーの既存セッションへも
     * （タイムアウトを待たず）即時反映される。
     */
    public function isLoggedIn(): bool
    {
        if (!($this->session->isValid() && $this->session->get('user_id') !== null)) {
            return false;
        }

        static $revalidated = false;
        if (!$revalidated) {
            $revalidated = true;
            try {
                $pdo  = BaseModel::connect();
                $stmt = $pdo->prepare(
                    "SELECT `is_active`, `role` FROM `users` WHERE `id` = ? AND `tenant_id` = ?"
                );
                $stmt->execute([
                    (int)$this->session->get('user_id'),
                    (int)$this->session->get('tenant_id'),
                ]);
                $row = $stmt->fetch();

                if ($row === false || (int)$row['is_active'] !== 1) {
                    // 削除・無効化されたアカウント → セッションを破棄
                    $this->session->destroy();
                    return false;
                }

                // ロール変更（昇格/降格）をセッションへ反映
                if (($row['role'] ?? null) !== null) {
                    $this->session->set('role', $row['role']);
                }
            } catch (\Throwable $e) {
                // DBの一時障害時は可用性を優先し、セッションの有効性のみで判定する
            }
        }

        return true;
    }

    /**
     * 後方互換: check() は isLoggedIn() に委譲
     */
    public function check(): bool
    {
        return $this->isLoggedIn();
    }

    /**
     * 未認証の場合はログインページへリダイレクトして終了
     */
    public function requireAuth(): void
    {
        if (!$this->isLoggedIn()) {
            header('Location: /index.php?page=login');
            exit;
        }
    }

    /**
     * 後方互換: requireLogin() は requireAuth() に委譲
     */
    public function requireLogin(): void
    {
        $this->requireAuth();
    }

    /**
     * role=admin 以外はアクセス拒否
     */
    public function requireAdmin(): void
    {
        $this->requireAuth();
        if ($this->getRole() !== 'admin') {
            // 以前はプレーンテキスト「権限がありません。」だけを返していたため、
            // 他のエラー画面と同じデザインのページで案内する
            (new Response())->forbidden('この画面は管理者のみ利用できます。必要な場合は管理者に依頼してください。');
        }
    }

    /**
     * 後方互換: requireAdminRole() は requireAdmin() に委譲
     */
    public function requireAdminRole(): void
    {
        $this->requireAdmin();
    }

    /**
     * ログイン中のテナントIDを取得
     */
    public function getTenantId(): int
    {
        return (int)$this->session->get('tenant_id');
    }

    /**
     * 後方互換: tenantId() は getTenantId() に委譲
     */
    public function tenantId(): ?int
    {
        $id = $this->session->get('tenant_id');
        return $id !== null ? (int)$id : null;
    }

    /**
     * ログイン中のユーザーIDを取得
     */
    public function getUserId(): int
    {
        return (int)$this->session->get('user_id');
    }

    /**
     * ログイン中のロールを取得
     */
    public function getRole(): string
    {
        return (string)$this->session->get('role', '');
    }

    /**
     * テナント管理者権限チェック
     */
    public function isAdmin(): bool
    {
        return $this->isLoggedIn() && $this->getRole() === 'admin';
    }

    /**
     * テナントIDの一致チェック（テナント間アクセス制御）
     */
    public function belongsToTenant(int $resourceTenantId): bool
    {
        return $this->isLoggedIn() && $this->getTenantId() === $resourceTenantId;
    }

    /**
     * must_change_password フラグを取得
     */
    public function mustChangePassword(): bool
    {
        return (bool)$this->session->get('must_change_password', false);
    }

    /**
     * must_change_password フラグをセッション上で更新する
     * （パスワード変更完了後にクリアしないと、強制リダイレクトから抜けられない）
     */
    public function setMustChangePassword(bool $value): void
    {
        $this->session->set('must_change_password', $value ? 1 : 0);
    }

    /**
     * ログイン中のユーザー情報を取得（後方互換）
     */
    public function user(): ?array
    {
        if (!$this->isLoggedIn()) {
            return null;
        }
        return [
            'id'           => $this->getUserId(),
            'tenant_id'    => $this->getTenantId(),
            'branch_id'    => $this->session->get('branch_id'),
            'display_name' => $this->session->get('display_name'),
            'role'         => $this->getRole(),
        ];
    }

    /**
     * セッションにユーザー情報をセット（後方互換・配列形式）
     */
    public function loginWithArray(array $user): void
    {
        $this->session->regenerate();
        $this->session->set('user_id',      $user['id']);
        $this->session->set('tenant_id',    $user['tenant_id']);
        $this->session->set('branch_id',    $user['branch_id'] ?? null);
        $this->session->set('display_name', $user['display_name']);
        $this->session->set('role',         $user['role']);
    }

    // ----------------------------------------------------------------
    // システム管理者認証（別セッション・別URL）
    // ----------------------------------------------------------------

    /**
     * システム管理者ログイン（system_admins テーブルを照合）
     *
     * @param string|array $username ユーザー名（文字列）、または後方互換用の管理者配列
     * @param string       $password 平文パスワード（配列形式の場合は無視）
     * @return bool ログイン成功か否か
     */
    public function adminLogin($username, string $password = ''): bool
    {
        // 配列形式で呼ばれた場合（後方互換: Auth::adminLogin($adminArray)）
        if (is_array($username)) {
            $this->adminSession->regenerate();
            $this->adminSession->set('admin_id',   $username['id']);
            $this->adminSession->set('admin_name', $username['username']);
            return true;
        }

        $pdo      = BaseModel::connect();
        $throttle = new LoginThrottle($pdo);
        $ip       = $this->getIpAddress();
        $username = (string)$username;

        // ユーザー名は半角英数字と . _ - のみ受け付ける。DBの照合順序は全角・アクセント・
        // ゼロ幅文字などの表記ゆれを 'admin' と同一視するため、入口で弾いておく。
        $admin = false;
        if (preg_match('/\A[A-Za-z0-9._-]{1,64}\z/', $username) === 1) {
            $stmt = $pdo->prepare("SELECT * FROM `system_admins` WHERE `username` = ?");
            $stmt->execute([$username]);
            $admin = $stmt->fetch();
        }

        // 試行制限は特定できた管理者のIDで識別する（大文字小文字の違い等でも同一アカウント）。
        // 以前は入力文字列で識別しており、表記を変えるだけでロックを回避できた。
        $accountKey = $admin !== false
            ? LoginThrottle::accountKey('admin', 'id:' . $admin['id'])
            : LoginThrottle::accountKey('admin-input', $username);

        // 照合の前に試行を予約する（IP単位・アカウント×IP単位。並行リクエストでも上限を超えない）
        $reservation = $throttle->reserve($accountKey, $ip);
        if ($reservation === null) {
            password_verify($password, self::dummyHash()); // 応答時間を揃える
            return false;
        }

        // アカウント単位のロック（30分間に5回失敗。今回の予約自身は数えない）。
        // 信頼済みIP（過去にこのアカウントでログイン成功したIP）は対象外（ロックDoS対策）。
        // ロック中の拒否は照合しないため「直近30分の失敗」には数えない（数えるとロック中の
        // 再試行で失敗数が増え続け、ロックがいつまでも解けない）。IP単位の制限には数える
        if ($throttle->isAccountLocked($accountKey, (int)$reservation)
            && !$throttle->isTrustedIp($accountKey, $ip)) {
            $throttle->markRefused((int)$reservation);
            password_verify($password, self::dummyHash());
            return false;
        }

        if ($admin === false) {
            // 応答時間の差によるユーザー名の存在判定を防ぐためダミー照合を行う
            password_verify($password, self::dummyHash());
            return false;
        }

        if (!password_verify($password, $admin['password_hash'])) {
            return false; // 予約した行がそのまま失敗記録になる
        }

        $throttle->recordSuccess($accountKey, $ip);

        // ハッシュのコストが現在の既定と違えば再ハッシュする（照合時間を揃えるため）
        if (password_needs_rehash($admin['password_hash'], PASSWORD_BCRYPT)) {
            try {
                // 照合中にパスワードが変更された場合は上書きしない（旧ハッシュ一致時のみ更新）
                $pdo->prepare("UPDATE `system_admins` SET `password_hash` = ? WHERE `id` = ? AND `password_hash` = ?")
                    ->execute([password_hash($password, PASSWORD_BCRYPT), $admin['id'], $admin['password_hash']]);
            } catch (\Throwable $e) {
                // 再ハッシュ失敗はログインを妨げない
            }
        }

        // 最終ログイン日時を更新
        $upd = $pdo->prepare("UPDATE `system_admins` SET `last_login_at` = NOW() WHERE `id` = ?");
        $upd->execute([$admin['id']]);

        $this->adminSession->regenerate();
        $this->adminSession->set('admin_id',   (int)$admin['id']);
        $this->adminSession->set('admin_name', $admin['username']);

        // 公開されている初期パスワード（Admin7777）のままなら、変更するまで
        // 他の管理画面を使えないようにする（Router::dispatchAdmin で強制）
        $this->adminSession->set(
            'admin_must_change_password',
            hash_equals(self::DEFAULT_PASSWORD, $password) ? 1 : 0
        );

        return true;
    }

    /**
     * システム管理者がパスワード変更を強制されている状態か
     */
    public function adminMustChangePassword(): bool
    {
        return (bool)$this->adminSession->get('admin_must_change_password', false);
    }

    /**
     * システム管理者のパスワード変更強制フラグを更新する
     */
    public function setAdminMustChangePassword(bool $value): void
    {
        $this->adminSession->set('admin_must_change_password', $value ? 1 : 0);
    }

    /**
     * システム管理者ログアウト
     */
    public function adminLogout(): void
    {
        $this->adminSession->destroy();
    }

    /**
     * システム管理者がログイン済みか
     */
    public function isAdminLoggedIn(): bool
    {
        return $this->adminSession->isValid() && $this->adminSession->get('admin_id') !== null;
    }

    /**
     * 後方互換: checkAdmin() は isAdminLoggedIn() に委譲
     */
    public function checkAdmin(): bool
    {
        return $this->isAdminLoggedIn();
    }

    /**
     * システム管理者認証ガード
     */
    public function requireAdminAuth(): void
    {
        if (!$this->isAdminLoggedIn()) {
            header('Location: /admin/index.php?page=login');
            exit;
        }
    }

    /**
     * 後方互換: requireSystemAdmin() は requireAdminAuth() に委譲
     */
    public function requireSystemAdmin(): void
    {
        $this->requireAdminAuth();
    }

    /**
     * ログイン中のシステム管理者情報を取得
     */
    public function adminUser(): ?array
    {
        if (!$this->isAdminLoggedIn()) {
            return null;
        }
        return [
            'id'       => $this->adminSession->get('admin_id'),
            'username' => $this->adminSession->get('admin_name'),
        ];
    }

    // ----------------------------------------------------------------
    // パスワード照合
    // ----------------------------------------------------------------

    /**
     * 現在ログイン中のユーザーのパスワードを照合する
     * 台帳削除時のパスワード再入力確認に使用する。
     *
     * @param string $plainPassword 入力された平文パスワード
     * @return bool 一致する場合 true
     */
    public function verifyCurrentPassword(string $plainPassword): bool
    {
        if (!$this->isLoggedIn()) {
            return false;
        }

        $pdo  = BaseModel::connect();
        $stmt = $pdo->prepare(
            "SELECT `password_hash` FROM `users` WHERE `id` = ? AND `tenant_id` = ? AND `is_active` = 1"
        );
        $stmt->execute([$this->getUserId(), $this->getTenantId()]);
        $row = $stmt->fetch();

        if ($row === false) {
            return false;
        }

        return password_verify($plainPassword, $row['password_hash']);
    }

    // ----------------------------------------------------------------
    // 内部ユーティリティ
    // ----------------------------------------------------------------

    /**
     * クライアントのIPアドレスを取得（Request::ip() と同じ共通実装）
     *
     * 既定では REMOTE_ADDR のみを信頼する。TRUST_PROXY=true のときだけ、
     * X-Forwarded-For の偽装できない右端（自前プロキシが追記した値）から解決する。
     * ログイン試行制限・信頼済みIP判定の入力になるため、偽装可能な値は使わない。
     */
    private function getIpAddress(): string
    {
        return \FuryoDacho\Helpers\ClientIp::resolve();
    }
}
