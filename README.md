# 決済リンク・ゲートウェイ (Stripe + SQLite / Xrea 向け)

Stripe で決済が完了したユーザーだけを、管理者が指定した「秘密のURL」へリダイレクトする軽量ツールです。

- Composer 不使用・PHP 8.x 標準機能のみ（PDO SQLite / cURL or stream_context）
- Xrea の無料SSL環境を想定した相対 URL／環境変数ベースの設計
- 管理画面には簡易パスワード認証（`password_hash` + CSRF トークン）

## ディレクトリ構成

```
/
├── config.php       # Stripe鍵・管理パスワード・DBパスなどの設定
├── index.php        # 管理画面（ログイン・リンク管理・支払一覧）
├── checkout.php     # Stripe Checkout セッション生成 → リダイレクト
├── success.php      # 決済完了後に秘密URLへリダイレクト
├── webhook.php      # Stripe Webhook 受信（署名検証・DB更新）
├── .htaccess        # config.php / DB / ドットファイルの直アクセス禁止
├── lib/
│   ├── db.php       # SQLite 初期化・アクセス
│   ├── stripe.php   # 単一ファイルの軽量 Stripe API クライアント
│   ├── auth.php     # 管理者認証・CSRF
│   └── .htaccess    # lib/ への直アクセス禁止
└── data/
    ├── db.sqlite    # 初回アクセス時に自動生成
    └── .htaccess    # data/ への直アクセス禁止
```

## セットアップ

1. **ファイル配置**
   ソース一式を Xrea の公開ディレクトリ（例: `/public_html/pay/`）へアップロードします。
   `data/` ディレクトリはサーバから書き込み可能である必要があります（`chmod 755` 目安）。

2. **管理パスワードのハッシュを生成**
   ```sh
   php -r "echo password_hash('your-strong-password', PASSWORD_DEFAULT), PHP_EOL;"
   ```
   出力された `$2y$...` を `config.php` の `admin_password_hash`、または環境変数 `PGW_ADMIN_PASSWORD_HASH` に設定します。

3. **Stripe のテスト用キーを設定**
   Stripe ダッシュボード（テストモード）で発行した `sk_test_...` / `pk_test_...` を `config.php` に設定、
   もしくは環境変数 `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` で渡します。

4. **Webhook エンドポイントを登録**
   Stripe ダッシュボードの `Developers → Webhooks` で
   ```
   https://<your-host>/<path>/webhook.php
   ```
   を追加し、以下のイベントを購読します:
   - `checkout.session.completed`
   - `checkout.session.async_payment_succeeded`
   - `checkout.session.async_payment_failed`
   - `checkout.session.expired`

   生成された **Signing secret**（`whsec_...`）を `config.php` の `stripe_webhook_secret`
   もしくは環境変数 `STRIPE_WEBHOOK_SECRET` に設定します。

5. **管理画面にログイン**
   `https://<your-host>/<path>/index.php` を開き、上記で設定したパスワードでログイン。
   決済リンク（商品名・価格・秘密URL）を登録すると、Checkout URL が発行されます。

## 動作フロー

```
買い手 -> /checkout.php?slug=xxx
           |
           | Stripe Checkout Session 作成
           v
       Stripe Checkout 画面で決済
           |
   +-------+---------------------------+
   |                                   |
   v                                   v
 /success.php?t=TOKEN            /webhook.php
 - token で payments を検索        - 署名検証
 - 未 paid の場合は Stripe 直接照会 - checkout.session.completed で
 - paid と判定されたら            payments.status = 'paid'
   redirect -> 秘密URL
```

`webhook.php` が到着しない／遅延する環境でも、`success.php` は Stripe API を直接問い合わせて
`payment_status = paid` を確認するため、単体でフォールバック動作します。

## セキュリティ上の注意

- `config.php` は `.htaccess` でWeb直アクセス禁止にしていますが、機密情報はできる限り
  環境変数（Xrea のコントロールパネルや `.htaccess` の `SetEnv`）で渡してください。
- SQLite ファイルは `data/` 配下に配置しており、`.htaccess` で直接DLを禁止しています。
  バックアップする場合は FTP 経由で取得してください。
- 管理画面は HTTPS 下での利用を前提としています（Cookie は `Secure; HttpOnly; SameSite=Lax`）。
- 本番モードへの切り替えは Stripe 側の切替 + キーの差し替えのみで対応できます。

## ライセンス

元リポジトリの `LICENSE` に従います。
