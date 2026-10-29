# 古物台帳管理システム（Python版）

PHP版（`../furyo-dacho-php`）を、**画面・機能・データベースをそのままに** Python 3 で書き換えたものです。
XREA などのレンタルサーバーで CGI として動きます。導入・移行の手順は [DEPLOY.md](DEPLOY.md) を見てください。
操作マニュアルは PHP版と同じです（[docs/manual.pdf](docs/manual.pdf)）。

## Python を選んだ理由
XREA で動かせる言語（PHP・Perl・Python など）の中で、次の点から Python 3 を選びました。

- **外部の部品にほとんど頼らない**: Python の標準ライブラリだけで作り、追加したのは MySQL 接続用の
  PyMySQL（純粋な Python・`lib/` に同梱）だけ。フレームワーク等の「脆弱性が見つかるたびに更新が必要な部品」がない。
- **CGI で動く**: リクエストごとに起動して終了するため、常駐プロセスの乗っ取り・メモリの使い回しの問題が起きにくい。
- **言語自体の安全性**: 文字列の長さ・型が厳密で、PHP で問題になりやすい「型の緩い比較」「文字列が配列になる入力」
  「エラー時に処理が続く」といった事故が起きにくい。
- **読みやすい**: 処理の流れを素直に書けるため、修正・点検がしやすい。

暗号化・パスワードの計算はサーバーに元からある OpenSSL などの実績あるライブラリを使い、自作していません。

## セキュリティ対策（PHP版から引き継ぎ・強化）
- 全画面の出力を自動でエスケープ（XSS 対策）。SQL はすべてプレースホルダ（SQL インジェクション対策）。
- すべての送信フォームに CSRF トークン（PHP版では無かったセットアップ画面にも追加）。
- パスワードは bcrypt（コスト12）。ログイン試行制限・アカウントロック・信頼済み回線の扱いは PHP版と同じ。
- 添付ファイルは AES-256-GCM で暗号化して保存（PHP版と同じ形式・同じ鍵）。
- セッションは 15 分で自動ログアウト。Cookie は HttpOnly・SameSite=Lax（HTTPS では Secure）。
- セキュリティヘッダー（CSP・X-Frame-Options 等）をプログラム側で付与。
- プログラム・設定・保存データのフォルダは `.htaccess` で外部から見えない。

## フォルダ構成
```
index.cgi            事業者側の入口      admin/index.cgi  システム管理者側の入口
setup.cgi            初回セットアップ    migrate.cgi      DBマイグレーション    check.cgi  環境診断
app/                 プログラム本体
  core/              共通部分（リクエスト・セッション・ログイン・画面の描画）
  controllers/       各画面の処理（PHP版 src/Controllers と1対1）
  models/            データベースの読み書き（PHP版 src/Models と1対1）
  helpers/           暗号化・パスワード・入力チェック・POS計算・レシート等（PHP版 src/Helpers に相当）
  maintenance/       setup・migrate・check の処理
views/               画面テンプレート（PHP版 views/ に対応。デザインは同じ）
lib/pymysql/         MySQL 接続ライブラリ（同梱・MIT ライセンス）
database/            テーブル定義（PHP版と同じ）
config/.env          設定（DB・暗号化キー。セットアップで作成）
storage/             アップロード・セッション・ログ（外部から見えない）
public/              公開フォルダを分ける構成用の入口
docs/                操作マニュアル
tests/               自動テスト
tools/devserver.py   手元のパソコンで動かすための簡易サーバー
```

画面テンプレートは HTML に `{{ 値 }}`（自動でエスケープ）・`{% if %}`・`{% for %}` などを書く形式です
（`app/core/template.py` に説明があります）。

## 手元で動かす
```
# config/.env を用意（.env.example を参考。DB は MySQL / MariaDB）
python3 tools/devserver.py 8090
# → http://127.0.0.1:8090/index.cgi
```

## テスト
```
python3 -m unittest discover -s tests -v
```

## 動作確認の内容
- PHP版と Python版に同じ操作（164 項目：ログイン・台帳・会員・販売・POS会計・返品・精算・CSV/PDF出力・
  ユーザー管理・テナント管理・ロック等）を自動で行い、すべて合格。
- 同じデータで 61 画面の HTML を比較し、表示内容が同じことを確認。
- 実際の Apache + CGI（Python 3.6）環境でも、セットアップ画面から全項目の操作まで合格。
- POS の金額計算（2,000 通りの無作為な会計）、レシート・領収書・精算レシート・バーコードの出力が PHP版と一致。
- PHP版で暗号化したファイル・PHP版で設定したパスワードを、そのまま読める・照合できることを確認。

## PHP版との違い（動作に影響しないもの）
- 画面の URL が `index.php` → `index.cgi` に変わる（旧 URL は自動で転送）。
- セットアップ画面（setup.cgi）にも CSRF トークンを追加。
- 送信サイズの上限を超えたときに、専用のメッセージ画面を表示する。
- HTML のフォームの送信先の `&` を `&amp;` と書く（HTML の正しい書き方。ブラウザでの動作は同じ）。
