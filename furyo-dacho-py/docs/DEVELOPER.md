# 開発者向けの説明（Python版）

プログラムを直したり、画面を追加したりする人のための説明です。
導入の手順は [../DEPLOY.md](../DEPLOY.md)、全体の概要は [../README.md](../README.md) を見てください。

## 1. 画面を開いたときの流れ

```
ブラウザ ─ /index.cgi?page=category
   │
   ▼
index.cgi                     … 入口（Apache が CGI として起動。毎回起動して終了する）
   │
   ▼
app/wsgi.py                   … 設定・セッション・リクエストを用意し、page= に対応する処理を呼ぶ
   │  app/routes.py           … 「page 名 → コントローラーと処理名・ログイン要否・必要な権限」の対応表
   ▼
app/controllers/category.py   … 画面ごとの処理（入力の確認・保存・画面の表示）
   │  app/models/*.py         … データベースの読み書き（SQL はここに書く）
   ▼
views/category/index.html     … 画面のテンプレート（HTML）
   │  views/layouts/main.html … 共通の枠（ヘッダー・メニュー・お知らせの表示）
   ▼
ブラウザへ HTML を返す
```

システム管理者側（`/admin/index.cgi`）も同じ流れで、対応表は `app/routes.py` の `ADMIN_ROUTES` です。

## 2. どこに何があるか

| 場所 | 役割 |
|---|---|
| `app/routes.py` | 画面の一覧。ここに無い page 名は「ページが見つかりません」になる |
| `app/core/controller.py` | コントローラーの共通部分（`render`・`redirect`・`verify_csrf`・`flash` など） |
| `app/core/auth.py` | ログイン・権限の確認（`require_login`・`require_admin_role`） |
| `app/core/request.py` | 送信内容の受け取り（前後の空白・制御文字は取り除き済み） |
| `app/core/template.py` | テンプレートの仕組み（書き方は下の 4. を参照） |
| `app/db.py` | データベースへの接続（`query`・`query_one`・`value`・`execute`・`insert`） |
| `app/util.py` | PHP版と同じ結果になる補助関数（`to_int`・`number_format`・`trim` など） |
| `app/helpers/` | 暗号化・パスワード・入力チェック・POS の計算・レシート・CSV など |
| `app/maintenance/` | `setup.cgi`・`migrate.cgi`・`check.cgi` の処理 |

## 3. 画面を 1 つ追加する例

「お知らせ」画面（`page=notice`）を追加する場合：

1. `app/controllers/notice.py` を作る
   ```python
   from ..core.controller import BaseController


   class NoticeController(BaseController):
       def index(self):
           rows = self.db.query("SELECT * FROM `notices` WHERE `tenant_id` = ? ORDER BY `id` DESC",
                                (self.auth.tenant_id(),))
           self.render('notice/index', {'notices': rows, 'activePage': 'notice'})
   ```
2. `app/routes.py` の `TENANT_ROUTES` に 1 行追加する
   ```python
   'notice': ('notice.NoticeController', 'index', True, None),   # ログイン必須・誰でも
   ```
   4 つ目を `'admin'` にすると、テナントの管理者だけが開ける。
3. `views/notice/index.html` を作る（下の 4. を参照）

## 4. テンプレートの書き方

```html
{% set pageTitle = 'お知らせ - 古物台帳管理システム' %}
{% extends 'layouts/main' %}

<h1>お知らせ</h1>
{% if has(var('notices')) %}
  <ul>
  {% for n in notices %}
    <li>{{ n['title'] }}（{{ php_date('Y/m/d', n['created_at']) }}）</li>
  {% endfor %}
  </ul>
{% else %}
  <p>お知らせはありません。</p>
{% endif %}
```

- `{{ 式 }}` … 値を表示する。**自動でエスケープされる**（`<` などがそのまま表示され、スクリプトは動かない）
- `{% if %}` / `{% elif %}` / `{% else %}` / `{% endif %}`、`{% for x in 一覧 %}` / `{% endfor %}`
- `{% set 名前 = 式 %}` … 変数を作る / `{% include 'pos/_printer' %}` … 部品を読み込む
- `{% py %} … {% endpy %}` … 少し長い計算を Python で書く
- `{# … #}` … 注釈（画面には出ない）
- `var('名前', 既定値)` … 渡されていないかもしれない値（PHP の `$x ?? 既定値`）
- `has(値)` … 空でないか（PHP の `!empty()` と同じ判定。`''`・`'0'`・`0`・空の一覧は空）
- `raw(値)` … エスケープせずに出す。**利用者が入力した値には絶対に使わない**
- 使える関数は `app/core/controller.py` の `_view_helpers()` に一覧がある

## 5. 守ること（安全のための約束）

- **SQL には値を直接つなげない。** 必ず `?` を使い、値は別に渡す
  ```python
  self.db.query("SELECT * FROM `members` WHERE `tenant_id` = ? AND `member_code` = ?", (tenant_id, code))
  ```
- **データは必ずテナントで絞る。** `WHERE tenant_id = ?` を忘れると、他の事業者のデータが見えてしまう
- **送信を受け付ける処理の最初で `self.verify_csrf()` を呼ぶ**（なりすまし送信の防止）
- **ログイン・権限は `app/routes.py` で指定する。** 処理の中で追加の確認が必要なら `self.auth.require_admin_role()`
- **入力値は `self.post_string()`・`self.post_int()` で受け取る。** 一覧（配列）が送られてきても安全に扱われる
- 数値・日付は `app/util.py` の `to_int`・`parse_date`・`is_digits` を使う（PHP版と同じく半角数字だけを数字として扱う）
- 画面の表示は必ずテンプレートで行い、`raw()` は使わない

## 6. 手元で動かす・テストする

```
python3 tools/devserver.py 8090              # http://127.0.0.1:8090/index.cgi で動作確認
python3 -m unittest discover -s tests -v     # 自動テスト
```

`config/.env` に開発用の DB を設定してから起動する（`.env.example` を参考に）。

## 7. Python のバージョン

XREA の Python 3.6 で動くように書いています。3.7 以降でしか使えない書き方
（`dataclasses`・`:=`・`from __future__ import annotations` など）は使わないでください。
変更後は Python 3.6 で `python3 -m unittest discover -s tests` が通ることを確認してください。

## 8. 同梱ライブラリ（PyMySQL）の更新

`lib/pymysql/` は [PyMySQL](https://github.com/PyMySQL/PyMySQL)（MIT ライセンス）をそのまま入れたものです。
更新する場合は、新しい版の `pymysql/` フォルダの中身と `LICENSE` を `lib/pymysql/` に置き換え、
Python 3.6 で動くことを確認してください（`check.cgi` に読み込んだ版が表示されます）。
