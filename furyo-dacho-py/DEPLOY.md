# XREA デプロイ手順（Python版）

Python版は、PHP版と **同じ画面・同じ機能・同じデータベース** で動く書き換え版です。
PHP は使わず、XREA の Python 3（3.6 以上）で CGI として動きます。

- 追加のインストールは不要です。MySQL 接続用の部品（PyMySQL）は `lib/` に同梱しています。
  暗号化（AES-256-GCM）とパスワード照合（bcrypt）は、サーバーに元からある OpenSSL・libcrypt・Apache の
  apr-util を使います（古い CentOS 7 系のサーバーでも動きます）。
- 画面の URL は `/index.cgi`（事業者側）と `/admin/index.cgi`（システム管理者側）です。
  旧PHP版の `/index.php`・`/admin/index.php` を開いた場合は自動で新しい URL へ転送されます。

## 1. ファイル転送

### 構成A（かんたん・推奨）: 一式をそのまま置く
- FTP で `furyo-dacho-py/` の **中身すべて**（`.htaccess` などの「.」で始まるファイルも含む）を `public_html/` に転送する。
- `app/` `views/` `lib/` `config/` `database/` `storage/` などは `.htaccess` で外部から見えないようにしてある。
- 公開フォルダの直下（ドメインの一番上）に置くこと。サブフォルダに置く構成には対応していない（PHP版と同じ）。

### 構成B: アプリ本体を公開フォルダの外に置く
```
/virtual/アカウント名/
├── furyo-dacho/          ← アプリ本体（furyo-dacho-py の中身。非公開）
├── furyo-dacho-uploads/  ← アップロードファイル保存場所（非公開）
└── public_html/          ← 公開フォルダ
    ├── index.cgi         ← public/index.cgi をコピー
    ├── admin/index.cgi   ← public/admin/index.cgi をコピー
    └── .htaccess         ← public/.htaccess をコピー
```
`public_html/` に置いた **index.cgi と admin/index.cgi の両方** の `APP_DIR = ...` の行を
アプリ本体の実際のパスに書き換える（setup.cgi・migrate.cgi・check.cgi を使うときも同じ）。
```python
APP_DIR = '/virtual/アカウント名/furyo-dacho'
```

### 転送時の注意（重要）
- **.cgi ファイルは改行コードを変えずに転送する**（FTP ソフトの「バイナリモード」）。Windows の改行（CRLF）に
  なると「500 Internal Server Error」になる。
- **権限（パーミッション）**: `index.cgi`・`admin/index.cgi`・`setup.cgi`・`migrate.cgi`・`check.cgi` は **755**。
  フォルダは 755（他人が書き込めない設定にする。707 や 777 にすると動かない）。
- `config/` と `storage/` の中（`uploads/` `sessions/` `logs/` `tmp/`）はプログラムが書き込むため、
  自分（FTP のユーザー）が書き込める状態にしておく（通常は転送したままでよい）。

### Python の場所
各 .cgi の 1 行目は `#!/usr/bin/env python3` になっている。XREA で動かない場合は、サーバーパネルで
Python 3 の場所を確認し、1 行目をその場所に書き換える（例: `#!/usr/bin/python3`）。

## 2. MySQL の準備（XREA サーバーパネル）
- MySQL データベースを作成し、ユーザーと権限を設定する（PHP版と同じ）。

## 3. 初期セットアップ（新規導入の場合）
1. `https://ドメイン/check.cgi` を開き、すべて OK になっているか確認する（任意）。
2. `https://ドメイン/setup.cgi` を開き、画面の指示に従う。
   - Step 1 環境チェック → Step 2 DB接続テスト → Step 3 DB初期化 → Step 4 設定ファイル（`config/.env`）の作成 → Step 5 完了
   - アップロードフォルダは公開フォルダの外（例: `/virtual/アカウント名/furyo-dacho-uploads`）を推奨。
3. 完了したら **setup.cgi と check.cgi をサーバーから削除する**。
   （`config/.env` がある状態では setup.cgi は動かないようにしてあるが、念のため削除する）

`config/.env` を手で作る場合は `.env.example` を参考にする。暗号化キーは次のコマンド等で作る。
```
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## 4. 初回ログイン（PHP版と同じ）
- 事業者側: `https://ドメイン/`
  - テナントコード: honsha / メール: admin@example.com / パスワード: Admin7777（初回ログイン時に変更必須）
- システム管理者: `https://ドメイン/admin/`
  - ユーザー名: admin / パスワード: Admin7777（初回ログイン時に変更必須。12文字以上・英字と数字を含む）

※ ログインは5回連続で失敗すると30分ロックされます（詳細は PHP版と同じ。下の「運用上の注意」を参照）。

## 5. PHP版からの移行
データベース・添付ファイル・パスワードはそのまま引き継げます。

1. **バックアップを取る**（サーバーパネルで DB のバックアップ、`config/.env` とアップロードフォルダのコピー）。
2. Python版のファイルを転送する（「1. ファイル転送」）。PHP版と同じ場所に置く場合は、PHP版の `.htaccess` は
   Python版の `.htaccess` で上書きする。
3. **PHP版の `config/.env` を、Python版の `config/.env` にそのままコピーする。**
   - `ENCRYPTION_KEY` は絶対に変えないこと（変えると保存済みの本人確認書類・画像が開けなくなる）。
   - `UPLOAD_DIR` もそのまま（PHP版のアップロードフォルダを引き続き使う）。PHP版で `UPLOAD_DIR` を
     設定していなかった場合は、PHP版の `storage/uploads/` の中身を Python版の `storage/uploads/` にコピーする。
4. `/admin/` にシステム管理者でログインしてから `https://ドメイン/migrate.cgi` を開き、
   「最新の状態です」と表示されれば完了（未適用の変更があれば「実行」を押す）。終わったら **migrate.cgi を削除**。
5. 動作を確認したら、PHP版のファイル（`index.php`・`admin/index.php`・`src/`・`setup.php`・`migrate.php`・
   `check.php` など）を削除する。

- パスワードは PHP版のものでそのままログインできる（同じ bcrypt 形式）。
- ログイン状態は引き継がれないため、全員が一度ログインし直す。
- 各端末のレシートプリンタ・レジ番号の設定（ブラウザに保存）は、同じドメインならそのまま使える。
- 万一 PHP版に戻す場合も、DB・ファイル・パスワードはそのまま使える。

## 6. アップロードの上限
PHP版の `.user.ini`（upload_max_filesize 等）は不要。上限は `config/.env` で変えられる（通常は設定不要）。
- `MAX_FILE_SIZE`: 1ファイルの上限（既定 50MB。商品画像は画面の案内どおり25MBまで）
- `MAX_POST_SIZE`: 1回の送信全体の上限（既定 128MB）

## 7. HTTPS 設定
- XREA の無料SSLを有効にしたら、`.htaccess` の「HTTPSへ転送」の2行の先頭の `#` を外す。
- HSTS を使う場合は `.htaccess` 末尾の該当行の `#` を外す。

## 8. うまく動かないとき
| 症状 | 確認すること |
|---|---|
| 500 Internal Server Error | .cgi の権限が 755 か／改行コードが LF か／1行目の Python の場所 |
| .cgi の中身がそのまま表示される・403 | `.htaccess` の `# Options +ExecCGI` の `#` を外す |
| 「システムエラーが発生しました」画面 | `storage/logs/error.log` にエラーの詳細が記録される |
| DB に接続できない | `config/.env` の DB_HOST / DB_NAME / DB_USER / DB_PASS |
| ログインできない（照合エラー） | check.cgi の「パスワード照合 bcrypt」が OK か |

`check.cgi` はセットアップ後はシステム管理者でログインしているときだけ表示される。確認後は削除すること。

## 9. 運用上の注意（PHP版と同じ）

### ログインのロックを解除したい場合・パスワードを忘れた場合（2026-10-26 から画面で操作可能）
- **テナント内の利用者**: テナントの管理者が「ユーザー管理」で「ロック解除」を押す。パスワードを忘れた
  場合は、そのユーザーの「編集」→「パスワードの再設定」で仮パスワードを設定する（ロックも解除され、
  次回ログイン時に本人のパスワードへの変更が求められる）。
- **オーナー（または管理者全員がログインできない場合）**: システム管理画面（/admin/）→ テナント管理 →
  テナント詳細の利用者一覧で「ロック解除」「パスワード再設定」を行う。
- いずれの操作も監査ログに記録される。

画面から操作できない場合は、phpMyAdmin 等で次を実行する。
（通常は30分で自動解除。過去にログイン成功したことのある回線からはロック中でもログイン可能）

**テナント利用者は①と②の両方を実行する**（①だけでは、同じ回線からの失敗記録による
制限が残り、最大30分ログインできない）。メールアドレスはテナントごとに重複し得るため、
テナントコードも指定する（例の 'honsha' と 'user@example.com' を置き換える）。

```sql
-- ① アカウントロックを解除
UPDATE users SET failed_login_attempts = 0, locked_until = NULL
WHERE tenant_id = (SELECT id FROM tenants WHERE code = 'honsha')
  AND email = 'user@example.com';

-- ② そのユーザーのログイン失敗記録を消去
DELETE FROM login_attempts
WHERE success <> 1
  AND account_hash = (
    SELECT SHA2(CONCAT('tenant|uid:', u.id), 256)
    FROM users u JOIN tenants t ON t.id = u.tenant_id
    WHERE t.code = 'honsha' AND u.email = 'user@example.com'
  );
```

システム管理者のロックは、失敗記録を消去すると解除される（例の 'admin' を置き換える）。

```sql
DELETE FROM login_attempts
WHERE success <> 1
  AND account_hash = (SELECT SHA2(CONCAT('admin|id:', id), 256) FROM system_admins WHERE username = 'admin');
```

※ 事務所などで同じ回線（同じグローバルIP）を複数人で共有している場合、誰かが短時間に
  繰り返しログインに失敗すると（15分間に30回）、その回線の全員が最大15分ログインできなく
  なることがある。急ぎの場合は次のSQLで解除できる。

全利用者の失敗記録をまとめて消去する場合（IP単位の制限・システム管理者のロックも解除）:

```sql
DELETE FROM login_attempts WHERE success <> 1;
-- ※ テナント利用者のアカウントロック（users.locked_until）はこれでは解除されない。
--   全員分をまとめて解除する場合は次も実行する。
UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE locked_until IS NOT NULL;
```

### リバースプロキシ・ロードバランサ配下で運用する場合
監査ログ等に実際の利用者IPを記録したい場合のみ、`config/.env` に次を設定する。

```
TRUST_PROXY=true
# 自前のプロキシのIP（CIDR可・カンマ区切り。設定を推奨）
TRUSTED_PROXIES=10.0.0.1,10.0.0.2
```

※ `.env` では注釈（#）は必ず行頭に書くこと。値の後ろに書くと、他の項目では注釈まで
  値の一部として読み込まれる（この2項目は行末の注釈を取り除くが、解釈できないIPは無視される）。

X-Forwarded-For は、自前のプロキシが末尾に追記した値（右端）から解決する。
利用者のIPがそのまま REMOTE_ADDR に入る構成（自前のプロキシを経由しない構成）では
**設定しないこと**（設定すると利用者がIPを偽装でき、ログイン試行制限を回避されるおそれがある）。

### 拠点ログインコードの重複確認
旧バージョンではテナントごとに同じ拠点ログインコードを登録できたため、重複が残っている
可能性がある。重複したコードではログインできない（別テナントへの誤誘導を防ぐため）。
migrate.cgi に一覧表示されるほか、次のSQLでも確認できる。該当テナントの管理者が
「拠点管理」でコードを変更すること。

```sql
SELECT login_code, COUNT(*) FROM branches
WHERE login_code IS NOT NULL AND login_code <> ''
GROUP BY login_code HAVING COUNT(*) > 1;

SELECT b.login_code FROM branches b JOIN tenants t ON t.code = b.login_code;
```

### DBサーバーのタイムゾーン
アプリはDB接続時にタイムゾーンを日本時間（+09:00）に設定する。
`SELECT @@global.time_zone, @@system_time_zone;` が日本時間以外の場合、2026-10版より前に
記録された登録日時等は9時間ずれている（以後の記録は日本時間で統一される）。

## 10. POSレジとレシートプリンタ

### 初期設定
1. 管理者で「POS設定・プリンタ」→「店舗・レシート・消費税の設定」を保存する
   （店舗名・住所・電話・インボイス登録番号・税率・内税/外税・端数処理）。
2. レジとして使う**各端末**で「POS設定・プリンタ」→「この端末のレシートプリンタ」を設定する
   （設定はその端末のブラウザに保存される）。

### 接続方式の選び方
| 方式 | 対応ブラウザ | 接続確認 | 備考 |
|---|---|---|---|
| ブラウザ印刷 | すべて | できない（常に接続ありとして扱う） | メーカーのドライバでOSに登録したプリンタ（USB/LAN/Bluetooth）。印刷ダイアログが出る |
| USB直結 | Chrome / Edge（https 必須） | 自動 | ESC/POS対応機（Epson TM / Star 等）。自動カット・ドロワー開放対応 |
| シリアル / Bluetooth | Chrome / Edge（https 必須） | 自動 | 通信速度をプリンタの設定に合わせる（既定 38400bps） |
| プリンタなし | すべて | — | 会計のたびに「未接続」ダイアログ →「許可」で画面発行 |

- USB直結・シリアルは**HTTPSで開いている場合のみ**使える（XREAの無料SSLを有効にし、
  `.htaccess` のHTTPSリダイレクトを有効化）。
- Windows でメーカーのプリンタドライバを入れている場合、USB直結では「接続できません」と
  なることがある（ドライバがUSBを占有するため）。その場合は「ブラウザ印刷」を使うか、
  メーカーのユーティリティでドライバを WinUSB に切り替える。
- ブラウザ印刷で印刷ダイアログを省略したい場合は、Chrome を `--kiosk-printing` オプション付きで
  起動し、OSの既定プリンタをレシートプリンタにする。用紙サイズはプリンタドライバ側で
  ロール紙（58mm / 80mm）を選ぶ。
- 「接続を確認」「テスト印刷」で動作を確認してから運用すること。

### レジ番号・レシートの呼出（2026-10-23 追加）
- レジが複数ある場合は、各端末の「POS設定・プリンタ」→「この端末のレジ番号」で別々の番号を設定する
  （既定はレジ01）。レシートに印字され、取引履歴・レジ明細検索・レジ精算をレジ別に見られる。
- 返品・再印刷の際は、レシートのバーコードをPOSレジの検索欄（または「レシート呼出」）で読み取ると
  取引詳細が開く。バーコードを読めない場合はレシート番号を入力する（本日分は連番だけでも可）。
- バーコードスキャナは CODE128 に対応し、読取後に Enter を送る設定（キーボード入力型）にする。

### 販売予定価格（2026-10-26 追加）
- 台帳の登録・編集画面で「販売予定価格（円・任意）」を入力しておくと、POSレジでその商品をカートに入れた時の
  単価に自動入力される（会計時に変更可）。

### 運用上の注意
- 取引の取消（返品）・売上CSV出力・店舗設定の変更は管理者のみ。取消すると在庫が戻る。
- レジ精算は何度でもやり直せる（履歴として残り、最新が有効）。
- 消費税の設定を変えた場合、開いているPOS画面は再読み込みしてから会計する
  （画面とサーバーの合計が一致しない場合は会計を止めて案内する）。
