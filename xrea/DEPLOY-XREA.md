# ぷらチャット XREA 設置手順

XREA（エクスリア）のレンタルサーバーに設置して運用するための手順です。

## なぜPerl CGI版なのか

XREAは**共用サーバーのため常駐プログラム（デーモン）が禁止**されており、
さらに以下の制限があります。

| 制限 | 内容 |
| --- | --- |
| 常駐プログラム | 禁止 |
| 実行時間 | 30秒を超えるタスクは強制終了 |
| CPU使用率 | 15%を超えるタスクは強制終了 |
| ポート開放 | 不可（ファイアウォールで遮断） |

このため、Node.js版（リポジトリ直下の `server.js`）は**XREAでは動作しません**。
XREA上ではこのPerl CGI版を使ってください。1リクエストごとにプロセスが起動して
すぐ終わるので、上記の制限に抵触しません。

Perlの**コアモジュールのみ**を使うため、CPANの追加インストールは不要です。
（`CGI.pm` はPerl 5.22でコアから外れたため使用していません）

---

## 1. 用意するもの

- XREA Plus（有料プラン）のアカウント … cronとSSHが使えます
- FTPクライアント または SSH
- 独自ドメイン、またはXREAのサブドメイン
- 無料SSL（Let's Encrypt）の有効化 … コントロールパネルから設定できます

> XREA Free（無料）でも動作しますが、cronが使えないため掃除処理は
> アクセス時の確率実行に頼ることになります（`gc_probability` の設定で調整）。

---

## 2. ファイルの配置

サーバー上の構成例です（`<user>` はXREAのアカウント名）。

```
/virtual/<user>/
├── purachat-data/            ← データ保存先（public_htmlの外・重要）
│   ├── rooms/
│   ├── sessions/
│   ├── pm/
│   ├── counter.json
│   └── contact.log
└── public_html/
    ├── chat/                 ← ここにアップロードする
    │   ├── index.cgi
    │   ├── ChatLib.pm
    │   ├── information.txt
    │   └── .htaccess
    └── chat-cron/
        └── gc.pl
```

アップロードするファイル（このリポジトリの `xrea/` 配下）:

| ローカル | サーバー |
| --- | --- |
| `xrea/public_html/index.cgi` | `/virtual/<user>/public_html/chat/index.cgi` |
| `xrea/public_html/ChatLib.pm` | `/virtual/<user>/public_html/chat/ChatLib.pm` |
| `xrea/public_html/information.txt` | `/virtual/<user>/public_html/chat/information.txt` |
| `xrea/public_html/.htaccess` | `/virtual/<user>/public_html/chat/.htaccess` |
| `xrea/cron/gc.pl` | `/virtual/<user>/public_html/chat-cron/gc.pl` |

> **FTPでアップロードする場合は必ず「アスキーモード」**にしてください。
> バイナリモードだと改行コードがCRLFのままになり、`500 Internal Server Error`
> の原因になります。

---

## 3. パーミッション設定

```bash
chmod 755 /virtual/<user>/public_html/chat/index.cgi
chmod 644 /virtual/<user>/public_html/chat/ChatLib.pm
chmod 644 /virtual/<user>/public_html/chat/information.txt
chmod 644 /virtual/<user>/public_html/chat/.htaccess
chmod 755 /virtual/<user>/public_html/chat-cron/gc.pl

mkdir -p /virtual/<user>/purachat-data
chmod 700 /virtual/<user>/purachat-data
```

`700` で動かない場合（CGIが別ユーザーで実行される構成のとき）は `755` を試し、
それでも書き込めない場合のみ `777` にしてください。

---

## 4. データディレクトリの指定

`ChatLib.pm` の `data_dir` を、**public_html の外**の絶対パスに設定します。

```perl
my %CFG = (
  ...
  data_dir => '/virtual/<user>/purachat-data',   # ← ここを書き換える
```

未設定の場合は `ChatLib.pm` の1つ上の階層の `purachat-data` が使われます。
念のためデータディレクトリには自動でアクセス拒否の `.htaccess` が作られますが、
**public_html の外に置くのが確実です。**

---

## 5. Perlのパス確認

`index.cgi` と `gc.pl` の1行目は `#!/usr/bin/perl` です。
XREAは通常このパスで動きますが、違う場合はSSHで確認して書き換えてください。

```bash
which perl
perl -v
```

---

## 6. HTTPSの設定

1. XREAのコントロールパネルで**無料SSL（Let's Encrypt）を有効化**します
2. `ChatLib.pm` の `https_only` が `1` であることを確認します（既定値）
   - CookieにSecure属性が付き、HTTPでは送信されなくなります
3. `.htaccess` のHTTPS強制リダイレクトが有効になっていることを確認します

**SSLを使わない場合**は、`.htaccess` のリダイレクトブロックをコメントアウトし、
`ChatLib.pm` の `https_only` を `0` にしてください（この場合、パスワードや
発言が平文で流れるため推奨しません）。

---

## 7. cronの設定（XREA Plus）

コントロールパネルの「cron設定」から、5分おきに掃除スクリプトを実行します。

```
*/5 * * * *  /usr/bin/perl /virtual/<user>/public_html/chat-cron/gc.pl
```

cronがやること:

- 期限切れセッションの削除
- 放置ユーザーの自動退室
- 無人になった部屋の削除
- 古い個人チャットの削除

cronを設定した場合は、`ChatLib.pm` の `gc_probability` を `0` にすると
リクエスト時の確率的GCが止まり、レスポンスが軽くなります。

---

## 8. 動作確認

ブラウザで `https://<あなたのドメイン>/chat/` を開きます。

- [ ] TOPページが表示され、部屋が4つ並んでいる
- [ ] 名前が「ゲスト＋数字」で自動設定されている
- [ ] 名前と色を保存できる
- [ ] 部屋に入室してチャットができる
- [ ] ログが自動更新される（既定10秒）
- [ ] 入力中の文字が自動更新で消えない
- [ ] 部屋を作成できる
- [ ] 管理パスワードで管理画面に入れる

---

## 9. トラブルシューティング

### 500 Internal Server Error

| 原因 | 対処 |
| --- | --- |
| 改行コードがCRLF | FTPのアスキーモードで再アップロード、または `perl -pi -e 's/\r$//' index.cgi` |
| パーミッション | `index.cgi` を `755` に |
| Perlのパスが違う | 1行目の `#!/usr/bin/perl` を `which perl` の結果に合わせる |
| `ChatLib.pm` が読めない | `index.cgi` と同じディレクトリに置く |

エラーの詳細はコントロールパネルのエラーログで確認できます。

### 「データを保存できません」「部屋が作れない」

データディレクトリの書き込み権限を確認してください。

```bash
ls -ld /virtual/<user>/purachat-data
```

### ページは出るが文字化けする

`.htaccess` に `AddDefaultCharset` の指定が別途入っていないか確認してください。
このCGIは `Content-Type: text/html; charset=UTF-8` を自分で出力します。

### 動作が重い / CPU制限に引っかかる

- 自動更新の間隔を長くしてください（利用者が [30秒] を選べます）
- `ChatLib.pm` の `min_auto` を大きくすると、5秒を選べないようにできます
- `gc_probability` を `0` にしてcronに任せてください

---

## 10. 設定項目（ChatLib.pm）

| 項目 | 既定値 | 説明 |
| --- | --- | --- |
| `data_dir` | `../purachat-data` | データ保存先（絶対パス推奨） |
| `https_only` | `1` | CookieにSecure属性を付ける |
| `max_message` | `500` | 発言の最大文字数 |
| `max_rooms` | `200` | 部屋数の上限 |
| `max_joined_rooms` | `5` | 同時入室できる部屋数 |
| `idle_timeout` | `600` | 自動退室までの秒数 |
| `post_window` / `post_limit` | `10` / `5` | 連投制限（10秒に5回） |
| `create_window` / `create_limit` | `300` / `3` | 部屋作成・問い合わせの制限 |
| `auth_window` / `auth_limit` | `60` / `5` | 管理パスワード試行の制限 |
| `min_auto` / `default_auto` | `5` / `10` | 自動更新の下限・既定値 |
| `rdns_timeout` | `2` | 逆引きのタイムアウト秒数（0で逆引きしない） |
| `gc_probability` | `100` | リクエスト時GCの分母（cron利用時は0推奨） |

---

## 11. 組み込み済みのセキュリティ対策

| 対策 | 内容 |
| --- | --- |
| IP偽装の防止 | `X-Forwarded-For` を信用せず `REMOTE_ADDR` のみ使用 |
| CSRF対策 | すべてのPOSTでトークンを検証 |
| セッションCookie | `HttpOnly` / `SameSite=Lax` / `Secure`（HTTPS時） |
| パスワード | ソルト付きSHA-256で保存（平文は保持しない） |
| 管理画面 | 認証後はトークンで操作（パスワードをHTMLに残さない） |
| 総当たり対策 | 管理パスワードの試行回数を制限（発言とは別枠） |
| 連投・荒らし対策 | 発言・部屋作成・問い合わせにレート制限 |
| XSS対策 | 出力を全てHTMLエスケープ |
| パストラバーサル対策 | 部屋ID・セッションID・pidを厳格に検証 |
| ヘッダインジェクション対策 | リダイレクト先から改行を除去 |
| 排他制御 | `flock` ＋ アトミックな `rename` で書き込み |
| ソースの保護 | `.pm` `.pl` `.json` `.log` へのアクセスを `.htaccess` で拒否 |
| GETでの状態変更禁止 | 発言・入室・管理操作はPOSTのみ受付 |

---

## 12. 運用上の注意

- **IPアドレスとプロバイダの開示**：昔のチャットサイトの再現として、参加者の
  ユーザー詳細でIPアドレスとリモートホストを表示します。日本で一般公開する場合は
  **プライバシーポリシーの掲示を強く推奨**します。開示をやめる場合は
  `index.cgi` の `page_user` から該当行を削除してください。
- **NGワードフィルタ・通報機能はありません。** 公開規模に応じて追加を検討してください。
- **画像投稿は外部URLの埋め込み**です。管理画面で部屋ごとにON/OFFできます。
- チャットのログはサーバー上のファイルに保存されます（部屋ごとに直近100件）。
  削除依頼への対応方法を決めておいてください。
- `contact.log` には問い合わせ内容とIPが記録されます。取り扱いにご注意ください。

---

## 13. 更新情報の掲載

`information.txt` を編集すると、TOPページと `/chat/?mode=info` に反映されます。
1行が1件で、上に書いたものが新しい扱いです。編集後のアップロードだけで反映され、
再起動などは不要です。
