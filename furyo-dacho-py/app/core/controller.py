"""
コントローラーの共通部分（PHP版 src/Controllers/BaseController.php と同じ役割）

- render(): 画面テンプレートを描画して返す（レイアウト共通の値を自動で渡す）
- verify_csrf(): フォーム送信の CSRF トークンを確認する
- redirect()/json()/error_page()/not_found()/forbidden(): その場で処理を終えて返す
"""
import secrets

from .. import config, util
from . import response as resp
from . import template
from .response import ResponseDone


def _pos_filter_query(filters, extra=None):
    from ..controllers.pos import filter_query
    return filter_query(filters, extra)


def _view_helpers():
    """テンプレートで使える関数"""
    from ..helpers import receipt_layout
    from ..models import item_category, pos_setting
    return {
        'php_date': util.php_date,
        'item_label': item_category.label,
        'item_category_statutory': item_category.STATUTORY,
        'max_upload_mb': lambda: int(config.get()['max_file_size'] // 1048576),
        'is_numeric': util.is_numeric,
        'php_round': util.php_round,
        'str': str, 'int': int, 'float': float, 'len': len, 'max': max, 'min': min, 'abs': abs,
        'range': range, 'any': any, 'all': all, 'enumerate': enumerate, 'sorted': sorted, 'isinstance': isinstance, 'dict': dict, 'list': list,
        'strtotime': util.strtotime,
        'raw': template.raw,
        'g': template.g,
        'h': util.html_escape,
        'number_format': util.number_format,
        'yen': util.yen,
        'to_int': util.to_int,
        'is_empty': util.is_empty,
        'has': lambda v: not util.is_empty(v),
        'json_for_script': util.json_for_script,
        'jp_datetime': util.jp_datetime,
        'mb_strimwidth': util.mb_strimwidth,
        'rawurlencode': util.rawurlencode,
        'urlencode': util.urlencode,
        'json_loads': util.json_loads,
        'http_build_query': util.http_build_query,
        'php_float_str': util.php_float_str,
        'today_str': util.today_str,
        'now_str': util.now_str,
        'now': util.now,
        'PAYMENT_LABELS': receipt_layout.PAYMENT_LABELS,
        'pos_filter_query': _pos_filter_query,
        'POS_TAX_MODES': pos_setting.TAX_MODES,
        'POS_TAX_ROUNDINGS': pos_setting.TAX_ROUNDINGS,
    }


class BaseController:
    def __init__(self, ctx):
        self.ctx = ctx
        self.request = ctx.request
        self.auth = ctx.auth
        self.session = ctx.session
        self.cfg = ctx.cfg

    @property
    def db(self):
        return self.ctx.db

    # ------------------------------------------------------------------
    # 画面
    # ------------------------------------------------------------------
    def render_html(self, view, data=None, layout='main'):
        """テンプレートを描画した HTML 文字列を返す"""
        values = self._layout_data(layout)
        values.update(data or {})
        values.setdefault('layout', layout)
        renderer = template.Renderer(_view_helpers())
        return renderer.render(view, values)

    def render(self, view, data=None, layout='main', status=200):
        raise ResponseDone(resp.html(self.render_html(view, data, layout), status))

    def _layout_data(self, layout):
        common = {
            'csrf_token': self.csrf_token(),
            'activePage': self.request.page(),
            'session': self.session,
        }
        if layout == 'admin':
            admin = self.auth.admin_user() or {}
            common['adminName'] = admin.get('username') or ''
            return common
        if self.auth.is_logged_in():
            user = self.auth.user() or {}
            role = user.get('role') or ''
            common['userName'] = user.get('display_name') or ''
            common['userRole'] = role
            common['isAdmin'] = role == 'admin'
            common['currentUserId'] = int(user.get('id') or 0)
            try:
                common['tenantName'] = str(self.db.value("SELECT `name` FROM `tenants` WHERE `id` = ?",
                                                         (self.auth.tenant_id(),)) or '')
            except Exception:
                common['tenantName'] = ''
            if role == 'admin':
                from ..models.alert import Alert
                try:
                    common['alertCount'] = Alert(self.db).count_unconfirmed(self.auth.tenant_id())
                except Exception:
                    common['alertCount'] = 0
                try:
                    common['approvalCount'] = int(self.db.value(
                        """SELECT COUNT(*) FROM `ledgers`
                           WHERE `tenant_id` = ? AND `approval_status` = 'pending' AND `deleted_at` IS NULL""",
                        (self.auth.tenant_id(),)) or 0)
                except Exception:
                    common['approvalCount'] = 0
        return common

    # ------------------------------------------------------------------
    # CSRF
    # ------------------------------------------------------------------
    def csrf_token(self):
        """CSRF トークン（セッション内で1つを使い回す。複数タブで開いても送信できるように）"""
        token = self.session.get('_csrf_token')
        if not token:
            token = secrets.token_hex(32)
            self.session.set('_csrf_token', token)
        return token

    def verify_csrf(self):
        if self.request.too_large:
            self.error_page(413, '送信サイズが大きすぎます',
                            '送信されたデータが大きすぎるため受け付けられませんでした。ファイルを小さくするか、枚数を減らしてもう一度お試しください。')
        token = self.request.raw_post('_csrf_token')
        stored = self.session.get('_csrf_token') or ''
        if token == '' or stored == '' or not secrets.compare_digest(str(stored), token):
            self.error_page(403, '不正なリクエスト',
                            'セッションの有効期限が切れたか、不正なリクエストです。ページを再読み込みしてもう一度お試しください。')

    # ------------------------------------------------------------------
    # 処理を終えて返す
    # ------------------------------------------------------------------
    def redirect(self, url):
        raise ResponseDone(resp.redirect(url))

    def json(self, data, status=200, no_store=False):
        raise ResponseDone(resp.json_response(data, status, no_store))

    def text(self, message, status=200):
        raise ResponseDone(resp.text(message, status))

    def error_page(self, status, title, message):
        raise ResponseDone(resp.error_page(status, title, message, self.ctx.area == 'admin'))

    def not_found(self, message='ページが見つかりません。'):
        self.error_page(404, 'ページが見つかりません', message)

    def forbidden(self, message='アクセスが拒否されました。'):
        self.error_page(403, 'アクセスできません', message)

    def flash(self, key, message):
        self.session.set_flash(key, message)

    # ------------------------------------------------------------------
    # 入力値
    # ------------------------------------------------------------------
    def post_string(self, key):
        """POST の文字列項目（前後の空白を除く。配列などが送られた場合は空文字）"""
        return util.trim(self.request.post_str(key))

    def post_int(self, key):
        return util.to_int(self.request.post(key))

    def get_int(self, key):
        return util.to_int(self.request.get(key))

    def user_name(self):
        """ログイン中のユーザーの表示名（監査ログ用）"""
        return (self.auth.user() or {}).get('display_name') or ''
