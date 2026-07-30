# ARCHITECTURE.md — fellow テーマ 技術構成

対象: setsna.com 用の改修 兼 買い切り配布用WordPressテーマ「fellow」
前提: XREA共用サーバー(Composer/WP-CLI/SSH無し)、PHP 8系、GPL準拠、¥9,800買い切り販売

---

## 1. ディレクトリ構成

```
fellow/
├── style.css                 # テーマヘッダー情報(必須)
├── screenshot.png            # 配布用サムネイル(1200x900)
├── functions.php              # エントリポイント、他ファイルをrequireするだけ
├── index.php                  # フォールバック(投稿一覧)
├── front-page.php             # トップページ(固定フロントページ設定時)
├── home.php                   # ブログトップ(最新記事一覧)
├── single.php                 # 記事詳細
├── page.php                   # 固定ページ
├── archive.php                # カテゴリー/タグ/年別アーカイブ共通
├── search.php                 # 検索結果
├── 404.php
├── header.php
├── footer.php
├── comments.php               # 使わない場合もテーマチェック対応で用意
├── inc/
│   ├── setup.php              # add_theme_support, メニュー登録, 画像サイズ
│   ├── enqueue.php             # CSS/JS読み込み、フォントの自己ホスト設定
│   ├── customizer.php          # カスタマイザー定義
│   ├── review-meta.php         # レビュースコア用メタボックス
│   ├── template-tags.php       # パンくず, TOC, 関連記事などの関数群
│   ├── walker-nav.php          # ハンバーガーメニュー用カスタムWalker
│   └── theme-options-page.php  # 配布版のみ:テーマ全体設定(検索ON/OFF等)
├── template-parts/
│   ├── content-card.php         # 記事カード(一覧・関連記事共通)
│   ├── content-featured.php     # トップの注目記事ブロック
│   └── score-dial.php           # スコアダイヤルの描画パーツ
├── assets/
│   ├── css/main.css              # ビルド後の1ファイルCSS(Sass等は使わない)
│   ├── css/editor.css            # ブロックエディタ用(add_editor_style で読み込み)
│   ├── js/main.js                # ハンバーガー/検索トグル/TOCスクロール追従
│   └── fonts/                    # 自己ホストWebフォント(woff2)
├── languages/
│   └── fellow.pot
└── LICENSE                    # GPLv2 or later
```

**方針**: XREAはComposer/CLIが使えないため、ビルドツール(webpack等)への依存はゼロにする。CSS/JSは手書き+手動minifyで`assets/`に直接配置し、`git pull`や`zip`アップロードだけで動く状態を常に維持する。

---

## 2. テンプレート階層の考え方

WordPress標準の階層に素直に従い、「セツナのブログ」の情報構造(ヘッダー→パンくず→本文→シェア→著者→前後記事→関連記事→PR→カテゴリー/アーカイブ→フッター)をテンプレート側で固定する。

| 画面 | テンプレート | 備考 |
|---|---|---|
| トップ(記事一覧) | `home.php` | 注目記事1件 + 最新記事リスト |
| 記事詳細 | `single.php` | TOCはサイドバー、スマホは本文上に折りたたみ |
| カテゴリー/タグ/年別 | `archive.php` | `get_the_archive_title()`を日本語向けに上書き |
| 検索結果 | `search.php` | ヘッダーの検索ボックスから遷移 |
| 固定ページ(プロフィール等) | `page.php` | サイドバーなしのシンプル1カラム |
| 404 | `404.php` | 検索ボックス+人気カテゴリーへの導線 |

`content-card.php` を `home.php`(一覧)・`archive.php`(一覧)・`single.php`(関連記事)の3箇所から共通で呼び出すことで、カード型UIの実装を一元化する。

---

## 3. functions.php の構成方針

`functions.php` 自体にはロジックを書かず、`inc/` 配下を読み込むだけにする(配布時の可読性・保守性のため)。

```php
require get_template_directory() . '/inc/setup.php';
require get_template_directory() . '/inc/enqueue.php';
require get_template_directory() . '/inc/customizer.php';
require get_template_directory() . '/inc/review-meta.php';
require get_template_directory() . '/inc/template-tags.php';
require get_template_directory() . '/inc/walker-nav.php';
if ( is_admin() ) {
    require get_template_directory() . '/inc/theme-options-page.php';
}
```

**setup.php で行うこと**
- `add_theme_support('title-tag')` / `post-thumbnails` / `html5` / `align-wide`
- ナビゲーションメニュー登録:`primary`(ヘッダー) / `footer-site`(フッター「サイト」列)
- カスタム画像サイズ:カード用(4:3)、記事詳細アイキャッチ用(16:9)
- ウィジェットエリア登録:`footer-widgets`。**1つも登録しないとWordPressが「外観 > ウィジェット」を `wp_die()` で拒否する**ため、配布テーマでは最低1つ持たせる。未設定なら `is_active_sidebar()` 判定で列ごと出力しない
- エディタスタイル:`add_theme_support('editor-styles')` + `add_editor_style()` の**両方**が必要。`add_editor_style()` が立てるのは単数形の `editor-style`(旧エディタ用)で、ブロックエディタは複数形の `editor-styles` を見ている

**enqueue.php で行うこと**
- `assets/css/main.css` を1本だけ読み込み(WordPress側のブロックライブラリCSS等は`wp_dequeue_style`で除去し軽量化)
- Webフォントは配布時のライセンス確認の上、自己ホスト(`@font-face`)を基本にし、CDN依存を避ける
- 絵文字スクリプト(`wp-emoji-release.min.js`)を`remove_action`で無効化
- 検索/ハンバーガー/TOC追従用のJSは1ファイルにまとめ、`defer`属性で読み込み

---

## 4. カスタマイザー実装方針(customizer.php)

配布テーマとして最低限、以下をCustomizer APIで可変にする。

| セクション | 項目 | 実装 |
|---|---|---|
| カラー | アクセントカラー | `WP_Customize_Color_Control`、デフォルト`#C2EEF2` |
| ロゴ/サイト名 | ロゴ画像 or テキストロゴ | `add_theme_support('custom-logo')` |
| SNSリンク | X / RSS / Feedly URL | テキストフィールド、空なら非表示 |
| レイアウト | 本文の文字数幅(65〜75文字) | セレクトボックス、CSS変数`--measure`を出し分け |
| 機能 | ヘッダー検索ボックスの表示/非表示 | チェックボックス(前回「検索欲しい」「ジャンルは不要」のような好みの違いに配布先も対応できるようにする) |
| 機能 | ヘッダー固定(sticky)切り替え | チェックボックス |

出力方法は `wp_add_inline_style` でCSS変数(`:root{--accent: ...}`)を動的生成し、`main.css`側は変数参照のみにする。テーマファイル自体を書き換えずに見た目を変えられるようにするのが配布版の生命線。

---

## 5. レビュースコア(スコアダイヤル)の実装

ACF等のプラグイン依存を避け、素の `add_meta_box` + `post_meta` で実装する(配布時にプラグイン必須にしないため)。

- メタキー:`_fellow_review_score`(0.0〜10.0、小数第1位)
- 投稿編集画面にメタボックス追加、未入力なら関連UIごと非表示(レビュー記事以外にも使うテーマのため)
- `template-parts/score-dial.php` 側で `get_post_meta()` の有無を判定し、値がなければダイヤルごと描画しない
- 配布先が「レビュー機能を使わない」ブログでも自然に成立する設計(3週間前の「配布版ではオフにできるように」という論点への回答)

---

## 6. カテゴリー・アーカイブ・パンくず

- パンくず:`template-tags.php`内に自前関数(`fellow_breadcrumb()`)を実装。プラグイン非依存。構造化データ(`BreadcrumbList`)もついでにJSON-LDで出力し、SEO面を補強
- フッターのカテゴリー一覧:`wp_list_categories()` をラップした関数で表示件数を制御
- フッターの年別アーカイブ:`wp_get_archives(['type' => 'yearly'])` をラップ
- 検索ボックス:`get_search_form()` をカスタムテンプレートで上書き、ヘッダー内にトグルUIとして設置(JSで`.open`クラス切り替えのみ、非表示時はネイティブの`<form>`として機能するのでJS無効環境でも壊れない)
- タグ:記事本文下に `fellow_entry_tags()` で表示(タグ未設定なら非出力)。タグアーカイブだけ用意して流入経路を作らないのを避ける
- 入れ子リストの注意:`wp_list_categories()` が出す `ul.children` には、ブラウザ既定の `ul ul { list-style-type: circle }` が**直接**当たるため、親の `list-style: none` の継承では消えない。`.footer-list ul` に明示的に指定する

**抜粋の扱い(日本語特有の注意)**
`wp_trim_words()` は空白で単語を区切るため、空白をほとんど使わない日本語ではほぼ切り詰められず本文全体が出てしまう。`fellow_get_excerpt()` を用意し、**文字数**(`mb_substr`)で切る。手動抜粋が無い場合は本文の最初の段落だけを使い、見出しの文字列が抜粋に混ざるのを防ぐ。

---

## 7. パフォーマンス方針(XREA共有サーバー前提)

- 画像は`loading="lazy"`をデフォルト付与、アイキャッチのみ`fetchpriority="high"`でLCP対策
- CSS/JSは合計でも数十KB以内を目標(Tailwind等のユーティリティ大量出力フレームワークは使わない)
- クエリ数を絞るため、関連記事の取得は「カテゴリー内からランダムではなく、直近日付順」でシンプルに(ランダム取得はDB負荷が上がりやすいため配布先の低スペック環境を考慮)
- 4桁の`wp_enqueue`重複を避けるため、`enqueue.php`内で条件分岐(`is_single()`時のみTOC用JSを読み込む、等)

---

## 8. 配布パッケージとして必要なもの

- **Theme Check プラグイン**でのエラー・警告ゼロ化(テーマ販売サイト・自前配布いずれでも信頼性の担保になる)
- **翻訳対応**:全文言を`__()`/`esc_html_e()`でラップし、`languages/fellow.pot`を同梱(日本語圏中心でも将来の多言語展開の余地を残す)
- **ライセンス表記**:`style.css`ヘッダーに `License: GPL v2 or later`、同梱画像・アイコン素材のライセンスを`LICENSE`に明記
- **README/ドキュメント**:購入者向けに「初期設定手順」「カスタマイザー項目の説明」を別途Markdown or PDFで用意(サポートコストを下げる目的)
- **バージョニング**:`style.css`の`Version:`をセマンティックバージョニングで管理し、アップデート提供は「永年無料」を謳う前提で運用コストを見込んでおく

---

## 動作確認の状況

WordPress 6.8(PHP 8.4)にzipからインストールして検証済み。

- [x] `inc/setup.php` と `header.php` / `footer.php` の実装
- [x] カスタマイザーの動作確認(アクセントカラーが `:root{--accent}` として反映されることを確認)
- [x] スコアダイヤルのメタボックスと表示条件分岐(0.0が消えないこと、未入力で非描画になることを確認)
- [x] Theme Check通過(REQUIRED 0 / WARNING 0)
- [x] 全テンプレートを `WP_DEBUG` 有効で描画し、PHP警告・Notice ゼロを確認
- [x] 保存処理の境界値・不正入力・nonce・権限チェック

**対応バージョンの下限は 6.3**。`wp_enqueue_script()` に `strategy => 'defer'` を渡すのが6.3以降の機能で、6.2以下では致命的エラーにはならないが `defer` が黙って落ちる(実機で確認済み)。

### 残っている検討事項

- `screenshot.png` はデモ記事を入れた実描画。販売時は実サイトの内容で撮り直す
- Theme Check の RECOMMENDED として `register_block_pattern` / `register_block_style` / `custom-header` / `custom-background` / `wp-block-styles` が残るが、いずれも該当しない機能か、ブロックCSS除去の方針と矛盾するため見送り
