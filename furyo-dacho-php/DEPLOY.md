# XREA デプロイ手順

## 1. ファイル転送
- FTPで furyo-dacho/ の全ファイルをサーバーへアップロード
- public/ の中身を DocumentRoot（public_html/）へ配置
- src/ config/ views/ storage/ database/ は public_html/ の外へ配置

## 2. ディレクトリ構成（XREA）
/home/アカウント名/
├── furyo-dacho/          ← アプリケーション本体（非公開）
│   ├── src/
│   ├── config/
│   ├── views/
│   ├── storage/
│   └── database/
├── furyo-dacho-uploads/  ← アップロードファイル保存場所（非公開）
└── public_html/          ← Webルート（公開）
    ├── index.php         ← public/index.php をコピー
    ├── admin/
    │   └── index.php     ← public/admin/index.php をコピー
    └── .htaccess         ← public/.htaccess をコピー

## 3. エントリポイントのパス修正（重要・2ファイル）
public_html/ にコピーした **index.php と admin/index.php の両方** の
先頭付近にある BASE_PATH をサーバー上の実パスに修正：

```php
if (!defined('BASE_PATH')) {
    define('BASE_PATH', '/virtual/アカウント名/furyo-dacho');
}
```

※ XREA の実パスは通常 `/virtual/アカウント名/` 配下。
   check.php をアップロードしてアクセスすると実パスを確認できる。
※ アプリ一式を public_html/ 直下にそのまま置く構成なら修正不要
  （その場合は src/ config/ 等が .htaccess でアクセス拒否される）。

## 4. MySQL設定（XREAコントロールパネル）
- コントロールパネルでMySQLデータベースを作成
- ユーザーと権限を設定
- `config/.env` にXREAで作成したDB情報を設定

例:
```
APP_ENV=production
APP_DEBUG=false
DB_HOST=localhost
DB_NAME=rin7_データベース名
DB_USER=rin7_ユーザー名
DB_PASS=DBパスワード
ENCRYPTION_KEY=64文字以上のランダム文字列
```

`DB_USER` が未設定の場合、本番環境では `root` へフォールバックせずエラーにします。

## 4.5. 旧バージョンからの移行時のみ
- 2026-07-08版へ更新する場合: migrate.php を index.php と同じ場所へ
  アップロードし、ブラウザで /migrate.php を開いて「実行」を押す
  （分離構成の場合は冒頭の MIGRATE_BASE をアプリ本体パスに書き換える）。
  完了後 migrate.php は必ず削除。phpMyAdmin 派は
  `database/migrate_20260708_item_category.sql` の実行でも可。
- 2026-07-09版（第2弾含む）へ更新する場合: 同様に migrate.php をアップロードして実行
  （会員管理・シリアル番号・個人法人切替・本人確認任意化のDB変更が適用される）。
  migrate.php は冪等のため、過去分も含めて未適用の変更だけが適用される。
旧バージョンで登録したデータがある場合、「&」等がHTMLエンコードされた
状態でDBに保存されている。バックアップ取得後、
`database/fix_double_encoding.sql` を phpMyAdmin 等で1回実行して平文に戻す。
（新規導入の場合は不要）

- 2026-10版（セキュリティ強化・第2弾）へ更新する場合も migrate.php を実行する。
  ログイン試行履歴テーブル（login_attempts）の作成と、主拠点・オーナーが未設定の
  テナントの補正が適用される。※ migrate.php の実行にはシステム管理者ログインが必要
  （先に /admin/ でログインしてから migrate.php を開く。初期パスワードのままの場合は
  先にパスワードを変更すること）。
  phpMyAdmin 派は `database/migrate_20261022_login_throttle.sql` を実行（補正は migrate.php のみ）。

- 2026-10-26版（総点検・機能追加）へ更新する場合も migrate.php を実行する。
  台帳に「本人確認書類『その他』の内容」と「販売予定価格」の2列が追加される
  （未実行でも台帳を扱う画面を開いた時点で自動追加される）。
  phpMyAdmin 派は `database/migrate_20261026_ledger_columns.sql` を実行。

## 5. 初期セットアップ
- setup.php を public_html/ にアップロード
- 分離構成（手順2）の場合は setup.php 冒頭の SETUP_BASE を
  アプリ本体のパスに書き換える:
  `define('SETUP_BASE', '/virtual/アカウント名/furyo-dacho');`
- https://yourdomain.com/setup.php にアクセス
- 画面の指示に従いDB初期化
- 完了後 setup.php を必ず削除

## 6. HTTPS設定
- public/.htaccess のHTTPSリダイレクト行のコメントを解除

## 7. 初回ログイン
※ テナントの管理者がユーザーを追加する場合は、登録画面で入力した初期パスワードが設定される
  （本人に伝え、初回ログイン時に本人のパスワードへ変更してもらう）。

- テナント側: https://yourdomain.com/
  - テナントコード: honsha
  - メール: admin@example.com
  - パスワード: Admin7777（初回ログイン時に変更必須）
- システム管理者: https://yourdomain.com/admin/
  - ユーザー名: admin
  - パスワード: Admin7777（初回ログイン時に変更必須。変更するまで他の管理画面は
    使えません。新しいパスワードは12文字以上・英字と数字を含むこと）
  - 以後もナビの「パスワード変更」からいつでも変更できます。

※ ログインは5回連続で失敗すると30分ロックされます。ただし、過去にそのアカウントで
  ログインに成功したことのあるIP（いつもの店舗・事務所の回線）からは、ロック中でも
  正しいパスワードでログインできます（第三者による故意のロック＝締め出しの防止）。
  また同一IPから短時間に多数失敗した場合は、そのIPからの試行を一時的に拒否します。


## 商品画像アップロードのサーバー設定（XREA）
商品画像（1点25MBまで）を使うには、PHPのアップロード上限を引き上げる必要がある。
XREAではアプリのルートに `.user.ini` を置くか、コントロールパネルのPHP設定で:

```
upload_max_filesize = 26M
post_max_size = 128M
max_file_uploads = 25
```

を設定する（post_max_size は複数枚同時アップロードを考慮して大きめに）。
未設定の場合、上限を超えたファイルは「サーバーのサイズ上限超過」エラーになる。

## 8. 運用上の注意（2026-10 追加）

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
migrate.php に一覧表示されるほか、次のSQLでも確認できる。該当テナントの管理者が
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

## 9. POSレジとレシートプリンタ（2026-10-22 追加）

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
  `public/.htaccess` のHTTPSリダイレクトを有効化）。
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
