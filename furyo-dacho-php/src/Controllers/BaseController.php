<?php

namespace FuryoDacho\Controllers;

use FuryoDacho\Core\Auth;
use FuryoDacho\Core\Request;
use FuryoDacho\Core\Response;
use FuryoDacho\Models\BaseModel;

/**
 * コントローラー基底クラス
 * 共通の依存関係（Request / Response / Auth / PDO）を保持する。
 */
abstract class BaseController
{
    protected Request  $request;
    protected Response $response;
    protected Auth     $auth;
    protected \PDO     $pdo;

    public function __construct(Request $request, Response $response, Auth $auth)
    {
        $this->request  = $request;
        $this->response = $response;
        $this->auth     = $auth;
        $this->pdo      = BaseModel::connect();
    }

    /**
     * ビューをレンダリングする
     *
     * @param string $view   views/ 以下のパス（例: 'ledger/index'）
     * @param array  $data   ビューに渡す変数
     * @param string $layout レイアウトファイル名（'main' or 'admin'）
     */
    protected function render(string $view, array $data = [], string $layout = 'main'): void
    {
        // レイアウト共通変数を注入（コントローラーが明示的に渡した値を優先）
        $data += $this->layoutData($layout);

        // ビューで使えるよう変数を展開
        extract($data, EXTR_SKIP);

        $viewPath   = __DIR__ . '/../../views/' . $view . '.php';
        $layoutPath = __DIR__ . '/../../views/layouts/' . $layout . '.php';

        if (!file_exists($viewPath)) {
            $this->response->notFound("View not found: {$view}");
            return;
        }

        // コンテンツをバッファリング
        ob_start();
        require $viewPath;
        $content = ob_get_clean();

        // Some existing tenant views render their own full layout. Avoid wrapping
        // those pages a second time while keeping admin partial views supported.
        if (stripos($content, '<!DOCTYPE') !== false) {
            echo $content;
            return;
        }

        // レイアウトに埋め込む
        if (file_exists($layoutPath)) {
            require $layoutPath;
        } else {
            echo $content;
        }
    }

    /**
     * レイアウト（views/layouts/main.php 等）が参照する共通変数を組み立てる
     *
     * 以前はこれらの変数がどのコントローラーからも渡されておらず、
     * ヘッダーのユーザー名が空欄・サイドバーの「管理」セクション
     * （ユーザー管理／拠点管理／アラート／監査ログ）が管理者にも
     * 一切表示されないという不具合があった。
     */
    private function layoutData(string $layout): array
    {
        $common = [
            'csrf_token' => $this->generateCsrfToken(),
            'activePage' => $this->request->page(),
        ];

        if ($layout === 'admin') {
            $admin = $this->auth->adminUser();
            $common['adminName'] = $admin['username'] ?? '';
            return $common;
        }

        if ($this->auth->isLoggedIn()) {
            $user = $this->auth->user();
            $common['userName']      = $user['display_name'] ?? '';
            $common['userRole']      = $user['role'] ?? '';
            // ビュー（user/index 等）が参照する権限・自ユーザーID
            $common['isAdmin']       = ($user['role'] ?? '') === 'admin';
            $common['currentUserId'] = (int)($user['id'] ?? 0);

            // ヘッダーに表示する事業者名（テナント名）
            try {
                $stmt = $this->pdo->prepare("SELECT `name` FROM `tenants` WHERE `id` = ?");
                $stmt->execute([$this->auth->getTenantId()]);
                $common['tenantName'] = (string)($stmt->fetchColumn() ?: '');
            } catch (\Throwable $e) {
                $common['tenantName'] = '';
            }

            // サイドバーのアラートバッジ（管理者のみ表示されるため管理者のみ取得）
            if (($user['role'] ?? '') === 'admin') {
                try {
                    $common['alertCount'] = (new \FuryoDacho\Models\Alert($this->pdo))
                        ->countUnconfirmed($this->auth->getTenantId());
                } catch (\Throwable $e) {
                    $common['alertCount'] = 0;
                }

                // 承認待ち台帳の件数（本人確認スキップ+未認証相手）
                try {
                    $stmt = $this->pdo->prepare(
                        "SELECT COUNT(*) FROM `ledgers`
                         WHERE `tenant_id` = ? AND `approval_status` = 'pending' AND `deleted_at` IS NULL"
                    );
                    $stmt->execute([$this->auth->getTenantId()]);
                    $common['approvalCount'] = (int)$stmt->fetchColumn();
                } catch (\Throwable $e) {
                    $common['approvalCount'] = 0;
                }
            }
        }

        return $common;
    }

    /**
     * セッションが有効であることを保証する
     * （タイムアウトで destroy された直後などに $_SESSION へ書き込んでも
     *   保存されない問題を防ぐ）
     */
    private function ensureSessionStarted(): void
    {
        if (session_status() !== PHP_SESSION_ACTIVE) {
            session_start(['use_strict_mode' => 1]);
        }
    }

    /**
     * CSRFトークンを検証する
     */
    protected function verifyCsrf(): void
    {
        $this->ensureSessionStarted();

        $token        = (string)($_POST['_csrf_token'] ?? '');
        $sessionToken = $_SESSION['_csrf_token'] ?? '';

        // hash_equals でタイミング攻撃を防ぐ
        if ($token === '' || $sessionToken === '' || !hash_equals($sessionToken, $token)) {
            $this->response->errorPage(403, '不正なリクエスト', 'セッションの有効期限が切れたか、不正なリクエストです。ページを再読み込みしてもう一度お試しください。');
            exit;
        }
    }

    /**
     * CSRFトークンを取得する（未生成の場合のみ新規生成）
     *
     * 以前は呼び出しのたびにトークンを再生成していたため、
     * 複数タブでフォームを開くと先に開いたタブの送信が必ず403になる
     * 問題があった。セッション内で1つのトークンを使い回す方式に変更。
     */
    protected function generateCsrfToken(): string
    {
        $this->ensureSessionStarted();

        if (empty($_SESSION['_csrf_token'])) {
            $_SESSION['_csrf_token'] = bin2hex(random_bytes(32));
        }
        return $_SESSION['_csrf_token'];
    }
}
