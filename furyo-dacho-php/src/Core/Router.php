<?php

namespace FuryoDacho\Core;

/**
 * フロントコントローラーパターン ルーター
 * GETパラメータ ?page=xxx でルーティングを行う。
 * テナント側とシステム管理者側で独立したルートテーブルを持つ。
 */
class Router
{
    private Auth     $auth;
    private Request  $request;
    private Response $response;

    /** @var array<string, array{controller: string, action: string, auth: bool, role: string|null}> */
    private array $tenantRoutes = [];

    /** @var array<string, array{controller: string, action: string, auth: bool}> */
    private array $adminRoutes = [];

    public function __construct()
    {
        $this->auth     = new Auth();
        $this->request  = new Request();
        $this->response = new Response();
    }

    // ----------------------------------------------------------------
    // テナント側ルート定義
    // ----------------------------------------------------------------

    /**
     * テナント側のルートを登録
     *
     * @param string      $page       ?page= の値
     * @param string      $controller コントローラークラス名（FQCN）
     * @param string      $action     メソッド名
     * @param bool        $requireAuth 認証必須か
     * @param string|null $role       必要なロール（null=全ユーザー、'admin'=管理者のみ）
     */
    public function addTenantRoute(
        string  $page,
        string  $controller,
        string  $action,
        bool    $requireAuth = true,
        ?string $role        = null
    ): void {
        $this->tenantRoutes[$page] = compact('controller', 'action', 'requireAuth', 'role');
    }

    /**
     * テナント側リクエストをディスパッチ
     */
    public function dispatchTenant(): void
    {
        $this->registerTenantRoutes();

        $page  = $this->request->page();
        $route = $this->tenantRoutes[$page] ?? null;

        if ($route === null) {
            $this->response->notFound();
            return;
        }

        // 認証チェック
        if ($route['requireAuth']) {
            $this->auth->requireLogin();

            // 初回パスワード変更が未完了の間は他ページへのアクセスを許可しない
            // （以前はログイン直後のリダイレクトのみで、URL直打ちで回避できた）
            if (
                $this->auth->mustChangePassword()
                && !in_array($page, ['change_password', 'logout'], true)
            ) {
                $this->response->redirect('/index.php?page=change_password');
                return;
            }
        }

        // ロールチェック
        if ($route['role'] === 'admin') {
            $this->auth->requireAdminRole();
        }

        $this->invokeController($route['controller'], $route['action']);
    }

    /**
     * テナント側ルートテーブルを定義
     */
    private function registerTenantRoutes(): void
    {
        // 認証
        $this->addTenantRoute('login',           \FuryoDacho\Controllers\AuthController::class, 'login',          false);
        $this->addTenantRoute('logout',          \FuryoDacho\Controllers\AuthController::class, 'logout',         true);
        $this->addTenantRoute('change_password', \FuryoDacho\Controllers\AuthController::class, 'changePassword', true);
        $this->addTenantRoute('account',         \FuryoDacho\Controllers\AuthController::class, 'account',        true);

        // ダッシュボード
        $this->addTenantRoute('dashboard', \FuryoDacho\Controllers\DashboardController::class, 'index', true);

        // 台帳
        $this->addTenantRoute('ledger',         \FuryoDacho\Controllers\LedgerController::class, 'index',  true);
        $this->addTenantRoute('ledger.create',  \FuryoDacho\Controllers\LedgerController::class, 'create', true);
        $this->addTenantRoute('ledger.store',   \FuryoDacho\Controllers\LedgerController::class, 'store',  true);
        $this->addTenantRoute('ledger.show',    \FuryoDacho\Controllers\LedgerController::class, 'show',   true);
        $this->addTenantRoute('ledger.edit',    \FuryoDacho\Controllers\LedgerController::class, 'edit',   true);
        $this->addTenantRoute('ledger.update',  \FuryoDacho\Controllers\LedgerController::class, 'update', true);
        $this->addTenantRoute('ledger.delete',  \FuryoDacho\Controllers\LedgerController::class, 'delete', true);

        // ユーザー管理（管理者のみ）
        $this->addTenantRoute('user',             \FuryoDacho\Controllers\UserController::class, 'index',      true, 'admin');
        $this->addTenantRoute('user.create',      \FuryoDacho\Controllers\UserController::class, 'create',     true, 'admin');
        $this->addTenantRoute('user.store',       \FuryoDacho\Controllers\UserController::class, 'store',      true, 'admin');
        $this->addTenantRoute('user.edit',        \FuryoDacho\Controllers\UserController::class, 'edit',       true, 'admin');
        $this->addTenantRoute('user.update',      \FuryoDacho\Controllers\UserController::class, 'update',     true, 'admin');
        $this->addTenantRoute('user.delete',     \FuryoDacho\Controllers\UserController::class, 'delete',     true, 'admin');
        $this->addTenantRoute('user.deactivate',  \FuryoDacho\Controllers\UserController::class, 'deactivate', true, 'admin');
        $this->addTenantRoute('user.activate',    \FuryoDacho\Controllers\UserController::class, 'activate',   true, 'admin');
        $this->addTenantRoute('user.password',    \FuryoDacho\Controllers\UserController::class, 'resetPassword', true, 'admin');
        $this->addTenantRoute('user.unlock',      \FuryoDacho\Controllers\UserController::class, 'unlock',     true, 'admin');

        // 拠点管理（管理者のみ）
        $this->addTenantRoute('branch',        \FuryoDacho\Controllers\BranchController::class, 'index',      true, 'admin');
        $this->addTenantRoute('branch.create', \FuryoDacho\Controllers\BranchController::class, 'create',     true, 'admin');
        $this->addTenantRoute('branch.store',  \FuryoDacho\Controllers\BranchController::class, 'store',      true, 'admin');
        $this->addTenantRoute('branch.edit',   \FuryoDacho\Controllers\BranchController::class, 'edit',       true, 'admin');
        $this->addTenantRoute('branch.update', \FuryoDacho\Controllers\BranchController::class, 'update',     true, 'admin');
        $this->addTenantRoute('branch.delete', \FuryoDacho\Controllers\BranchController::class, 'delete',     true, 'admin');

        $this->addTenantRoute('ledger.approve',     \FuryoDacho\Controllers\LedgerController::class, 'approve',    true, 'admin');
        $this->addTenantRoute('ledger.sale.store',  \FuryoDacho\Controllers\LedgerController::class, 'saleStore',  true);
        $this->addTenantRoute('ledger.sale.edit',   \FuryoDacho\Controllers\LedgerController::class, 'saleEdit',   true, 'admin');
        $this->addTenantRoute('ledger.sale.update', \FuryoDacho\Controllers\LedgerController::class, 'saleUpdate', true, 'admin');
        $this->addTenantRoute('ledger.sale.delete', \FuryoDacho\Controllers\LedgerController::class, 'saleDelete', true, 'admin');

        // POSレジ（全ユーザー。取消・CSV出力・店舗設定の保存は管理者）
        $pos = \FuryoDacho\Controllers\PosController::class;
        $this->addTenantRoute('pos',               $pos, 'index',        true);
        $this->addTenantRoute('pos.history',       $pos, 'history',      true);
        $this->addTenantRoute('pos.items',         $pos, 'items',        true);
        $this->addTenantRoute('pos.show',          $pos, 'show',         true);
        $this->addTenantRoute('pos.receipt',       $pos, 'receipt',      true);
        $this->addTenantRoute('pos.print.test',    $pos, 'printTest',    true);
        $this->addTenantRoute('pos.daily',         $pos, 'daily',        true);
        $this->addTenantRoute('pos.close',         $pos, 'close',        true);
        $this->addTenantRoute('pos.closing.print', $pos, 'closingPrint', true);
        $this->addTenantRoute('pos.settings',      $pos, 'settings',     true);
        $this->addTenantRoute('pos.settings.save', $pos, 'settingsSave', true, 'admin');
        $this->addTenantRoute('pos.void',          $pos, 'voidTransaction', true, 'admin');
        $this->addTenantRoute('pos.export',        $pos, 'export',       true, 'admin');
        // JSON API: 未ログイン・セッション切れ時はログイン画面へリダイレクトせず 401 JSON を返すため、
        // 認証・初回パスワード変更のチェックはコントローラー側（PosController::requireAuthJson）で行う
        $this->addTenantRoute('pos.search',        $pos, 'search',       false);
        $this->addTenantRoute('pos.checkout',      $pos, 'checkout',     false);
        $this->addTenantRoute('pos.printed',       $pos, 'printed',      false);
        $this->addTenantRoute('pos.member.search', $pos, 'memberSearch', false);
        $this->addTenantRoute('pos.lookup',        $pos, 'lookup',       false);

        // 集計レポート（管理者のみ）
        $this->addTenantRoute('report', \FuryoDacho\Controllers\ReportController::class, 'index', true, 'admin');

        // 会員管理（閲覧・登録・編集は全ユーザー、削除は管理者）
        $this->addTenantRoute('member',        \FuryoDacho\Controllers\MemberController::class, 'index',  true);
        $this->addTenantRoute('member.create', \FuryoDacho\Controllers\MemberController::class, 'create', true);
        $this->addTenantRoute('member.store',  \FuryoDacho\Controllers\MemberController::class, 'store',  true);
        $this->addTenantRoute('member.edit',   \FuryoDacho\Controllers\MemberController::class, 'edit',   true);
        $this->addTenantRoute('member.update', \FuryoDacho\Controllers\MemberController::class, 'update', true);
        $this->addTenantRoute('member.delete', \FuryoDacho\Controllers\MemberController::class, 'delete', true, 'admin');
        $this->addTenantRoute('member.lookup', \FuryoDacho\Controllers\MemberController::class, 'lookup', true);
        $this->addTenantRoute('member.show',   \FuryoDacho\Controllers\MemberController::class, 'show',   true);

        // 古物区分管理（管理者のみ）
        $this->addTenantRoute('category',        \FuryoDacho\Controllers\CategoryController::class, 'index',  true, 'admin');
        $this->addTenantRoute('category.store',  \FuryoDacho\Controllers\CategoryController::class, 'store',  true, 'admin');
        $this->addTenantRoute('category.delete', \FuryoDacho\Controllers\CategoryController::class, 'delete', true, 'admin');

        // アラート
        $this->addTenantRoute('alert',         \FuryoDacho\Controllers\AlertController::class, 'index',   true);
        $this->addTenantRoute('alert.confirm', \FuryoDacho\Controllers\AlertController::class, 'confirm', true, 'admin');

        // 監査ログ（管理者のみ）
        $this->addTenantRoute('audit', \FuryoDacho\Controllers\AuditController::class, 'index', true, 'admin');

        // エクスポート
        $this->addTenantRoute('export',        \FuryoDacho\Controllers\ExportController::class, 'index',  true, 'admin');
        $this->addTenantRoute('export.export', \FuryoDacho\Controllers\ExportController::class, 'export', true, 'admin');

        // ファイルダウンロード（暗号化ファイルを復号して返す）
        $this->addTenantRoute('file.download', \FuryoDacho\Controllers\FileController::class, 'download', true);
    }

    // ----------------------------------------------------------------
    // システム管理者側ルート定義
    // ----------------------------------------------------------------

    /**
     * システム管理者側のルートを登録
     */
    public function addAdminRoute(string $page, string $controller, string $action, bool $requireAuth = true): void
    {
        $this->adminRoutes[$page] = compact('controller', 'action', 'requireAuth');
    }

    /**
     * システム管理者側リクエストをディスパッチ
     */
    public function dispatchAdmin(): void
    {
        $this->registerAdminRoutes();

        $page  = $this->request->page();
        $route = $this->adminRoutes[$page] ?? null;

        if ($route === null) {
            $this->response->notFound();
            return;
        }

        if ($route['requireAuth']) {
            $this->auth->requireSystemAdmin();

            // 初期パスワード（公開値）のままの間は、パスワード変更以外の管理画面を使わせない
            if (
                $this->auth->adminMustChangePassword()
                && !in_array($page, ['password', 'logout'], true)
            ) {
                $this->response->redirect('/admin/index.php?page=password');
                return;
            }
        }

        $this->invokeController($route['controller'], $route['action']);
    }

    /**
     * システム管理者側ルートテーブルを定義
     */
    private function registerAdminRoutes(): void
    {
        $this->addAdminRoute('login',    \FuryoDacho\Controllers\Admin\AdminAuthController::class, 'login',          false);
        $this->addAdminRoute('logout',   \FuryoDacho\Controllers\Admin\AdminAuthController::class, 'logout',         true);
        $this->addAdminRoute('password', \FuryoDacho\Controllers\Admin\AdminAuthController::class, 'changePassword', true);

        $this->addAdminRoute('dashboard', \FuryoDacho\Controllers\Admin\TenantController::class, 'dashboard', true);

        $this->addAdminRoute('tenant',          \FuryoDacho\Controllers\Admin\TenantController::class, 'index',   true);
        $this->addAdminRoute('tenant.create',  \FuryoDacho\Controllers\Admin\TenantController::class, 'create',  true);
        $this->addAdminRoute('tenant.store',   \FuryoDacho\Controllers\Admin\TenantController::class, 'store',   true);
        $this->addAdminRoute('tenant.show',    \FuryoDacho\Controllers\Admin\TenantController::class, 'show',    true);
        $this->addAdminRoute('tenant.edit',    \FuryoDacho\Controllers\Admin\TenantController::class, 'edit',    true);
        $this->addAdminRoute('tenant.update',  \FuryoDacho\Controllers\Admin\TenantController::class, 'update',  true);
        $this->addAdminRoute('tenant.suspend', \FuryoDacho\Controllers\Admin\TenantController::class, 'suspend', true);
        $this->addAdminRoute('tenant.delete',  \FuryoDacho\Controllers\Admin\TenantController::class, 'delete',  true);
        $this->addAdminRoute('tenant.resume',  \FuryoDacho\Controllers\Admin\TenantController::class, 'resume',  true);
        $this->addAdminRoute('tenant.user.password', \FuryoDacho\Controllers\Admin\TenantController::class, 'userPassword', true);
        $this->addAdminRoute('tenant.user.unlock',   \FuryoDacho\Controllers\Admin\TenantController::class, 'userUnlock',   true);
    }

    // ----------------------------------------------------------------
    // 内部ユーティリティ
    // ----------------------------------------------------------------

    /**
     * コントローラーをインスタンス化してアクションを呼び出す
     */
    private function invokeController(string $controllerClass, string $action): void
    {
        if (!class_exists($controllerClass)) {
            $this->response->notFound("Controller not found: {$controllerClass}");
            return;
        }

        $controller = new $controllerClass($this->request, $this->response, $this->auth);

        if (!method_exists($controller, $action)) {
            $this->response->notFound("Action not found: {$action}");
            return;
        }

        $controller->$action();
    }
}
