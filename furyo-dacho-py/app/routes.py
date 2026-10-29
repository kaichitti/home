"""
画面（?page=xxx）と処理の対応表（PHP版 src/Core/Router.php と同じ内容）

各行: ページ名: (コントローラー, 処理名, ログイン必須か, 必要な権限)
  権限 None = ログインしていれば誰でも / 'admin' = テナント管理者のみ
"""

AUTH = 'auth.AuthController'
DASH = 'dashboard.DashboardController'
LEDGER = 'ledger.LedgerController'
USER = 'user.UserController'
BRANCH = 'branch.BranchController'
POS = 'pos.PosController'
REPORT = 'report.ReportController'
MEMBER = 'member.MemberController'
CATEGORY = 'category.CategoryController'
ALERT = 'alert.AlertController'
AUDIT = 'audit.AuditController'
EXPORT = 'export.ExportController'
FILE = 'file.FileController'

TENANT_ROUTES = {
    # 認証
    'login': (AUTH, 'login', False, None),
    'logout': (AUTH, 'logout', True, None),
    'change_password': (AUTH, 'change_password', True, None),
    'account': (AUTH, 'account', True, None),

    # ダッシュボード
    'dashboard': (DASH, 'index', True, None),

    # 台帳
    'ledger': (LEDGER, 'index', True, None),
    'ledger.create': (LEDGER, 'create', True, None),
    'ledger.store': (LEDGER, 'store', True, None),
    'ledger.show': (LEDGER, 'show', True, None),
    'ledger.edit': (LEDGER, 'edit', True, None),
    'ledger.update': (LEDGER, 'update', True, None),
    'ledger.delete': (LEDGER, 'delete', True, None),

    # ユーザー管理（管理者のみ）
    'user': (USER, 'index', True, 'admin'),
    'user.create': (USER, 'create', True, 'admin'),
    'user.store': (USER, 'store', True, 'admin'),
    'user.edit': (USER, 'edit', True, 'admin'),
    'user.update': (USER, 'update', True, 'admin'),
    'user.delete': (USER, 'delete', True, 'admin'),
    'user.deactivate': (USER, 'deactivate', True, 'admin'),
    'user.activate': (USER, 'activate', True, 'admin'),
    'user.password': (USER, 'reset_password', True, 'admin'),
    'user.unlock': (USER, 'unlock', True, 'admin'),

    # 拠点管理（管理者のみ）
    'branch': (BRANCH, 'index', True, 'admin'),
    'branch.create': (BRANCH, 'create', True, 'admin'),
    'branch.store': (BRANCH, 'store', True, 'admin'),
    'branch.edit': (BRANCH, 'edit', True, 'admin'),
    'branch.update': (BRANCH, 'update', True, 'admin'),
    'branch.delete': (BRANCH, 'delete', True, 'admin'),

    'ledger.approve': (LEDGER, 'approve', True, 'admin'),
    'ledger.sale.store': (LEDGER, 'sale_store', True, None),
    'ledger.sale.edit': (LEDGER, 'sale_edit', True, 'admin'),
    'ledger.sale.update': (LEDGER, 'sale_update', True, 'admin'),
    'ledger.sale.delete': (LEDGER, 'sale_delete', True, 'admin'),

    # POSレジ（全ユーザー。取消・CSV出力・店舗設定の保存は管理者）
    'pos': (POS, 'index', True, None),
    'pos.history': (POS, 'history', True, None),
    'pos.items': (POS, 'items', True, None),
    'pos.show': (POS, 'show', True, None),
    'pos.receipt': (POS, 'receipt', True, None),
    'pos.print.test': (POS, 'print_test', True, None),
    'pos.daily': (POS, 'daily', True, None),
    'pos.close': (POS, 'close', True, None),
    'pos.closing.print': (POS, 'closing_print', True, None),
    'pos.settings': (POS, 'settings', True, None),
    'pos.settings.save': (POS, 'settings_save', True, 'admin'),
    'pos.void': (POS, 'void_transaction', True, 'admin'),
    'pos.export': (POS, 'export', True, 'admin'),
    # JSON API: 未ログイン時はログイン画面へ移動せず 401 の JSON を返すため、
    # 認証・初回パスワード変更の確認はコントローラー側（require_auth_json）で行う
    'pos.search': (POS, 'search', False, None),
    'pos.checkout': (POS, 'checkout', False, None),
    'pos.printed': (POS, 'printed', False, None),
    'pos.member.search': (POS, 'member_search', False, None),
    'pos.lookup': (POS, 'lookup', False, None),

    # 集計レポート（管理者のみ）
    'report': (REPORT, 'index', True, 'admin'),

    # 会員管理（閲覧・登録・編集は全ユーザー、削除は管理者）
    'member': (MEMBER, 'index', True, None),
    'member.create': (MEMBER, 'create', True, None),
    'member.store': (MEMBER, 'store', True, None),
    'member.edit': (MEMBER, 'edit', True, None),
    'member.update': (MEMBER, 'update', True, None),
    'member.delete': (MEMBER, 'delete', True, 'admin'),
    'member.lookup': (MEMBER, 'lookup', True, None),
    'member.show': (MEMBER, 'show', True, None),

    # 古物区分管理（管理者のみ）
    'category': (CATEGORY, 'index', True, 'admin'),
    'category.store': (CATEGORY, 'store', True, 'admin'),
    'category.delete': (CATEGORY, 'delete', True, 'admin'),

    # アラート
    'alert': (ALERT, 'index', True, None),
    'alert.confirm': (ALERT, 'confirm', True, 'admin'),

    # 監査ログ（管理者のみ）
    'audit': (AUDIT, 'index', True, 'admin'),

    # エクスポート
    'export': (EXPORT, 'index', True, 'admin'),
    'export.export': (EXPORT, 'export', True, 'admin'),

    # ファイルダウンロード（暗号化ファイルを復号して返す）
    'file.download': (FILE, 'download', True, None),
}

ADMIN_AUTH = 'admin.auth.AdminAuthController'
TENANT = 'admin.tenant.TenantController'

ADMIN_ROUTES = {
    'login': (ADMIN_AUTH, 'login', False),
    'logout': (ADMIN_AUTH, 'logout', True),
    'password': (ADMIN_AUTH, 'change_password', True),

    'dashboard': (TENANT, 'dashboard', True),

    'tenant': (TENANT, 'index', True),
    'tenant.create': (TENANT, 'create', True),
    'tenant.store': (TENANT, 'store', True),
    'tenant.show': (TENANT, 'show', True),
    'tenant.edit': (TENANT, 'edit', True),
    'tenant.update': (TENANT, 'update', True),
    'tenant.suspend': (TENANT, 'suspend', True),
    'tenant.delete': (TENANT, 'delete', True),
    'tenant.resume': (TENANT, 'resume', True),
    'tenant.user.password': (TENANT, 'user_password', True),
    'tenant.user.unlock': (TENANT, 'user_unlock', True),
}
