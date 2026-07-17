=== fellow ===
Contributors: setsna
Requires at least: 6.0
Tested up to: 6.7
Requires PHP: 8.0
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html
Tags: blog, news, one-column, custom-colors, custom-logo, custom-menu, featured-images, threaded-comments, translation-ready

レビュー/ブログ向けの軽量WordPressテーマ。カード型一覧・レビュースコアダイヤル・プラグイン非依存のパンくず/目次を備えます。

== Description ==

fellow は共用サーバー(XREA等)でも軽快に動くことを重視した、レビュー/ブログ向けテーマです。

* カード型の記事一覧と、ブログトップの注目記事ブロック
* レビュースコアダイヤル(0.0〜10.0)。プラグイン不要、未入力なら非表示
* プラグイン非依存のパンくず(BreadcrumbList の JSON-LD 付き)
* 本文見出しから自動生成される目次(デスクトップは追従サイドバー、モバイルは折りたたみ)
* ヘッダー検索のトグルUI(JS無効環境でも動作)
* ビルドツール非依存。CSS/JS 各1ファイルのみ

== Installation ==

1. 管理画面の「外観 > テーマ > 新規追加 > テーマのアップロード」から zip をアップロード
2. テーマを有効化
3. 「外観 > メニュー」で「ヘッダーメニュー」「フッター「サイト」メニュー」を割り当て
4. 「外観 > カスタマイズ」でアクセントカラー・ロゴ・SNSリンク等を設定
5. レビュー記事では投稿編集画面サイドバーの「レビュースコア」に 0.0〜10.0 を入力

== Frequently Asked Questions ==

= レビュー機能を使わない場合は? =

「外観 > fellow 設定」でレビュースコア機能ごとオフにできます。
スコアを入力しなければ、記事単位でも自動的に非表示になります。

= 目次を出したくない記事は? =

目次は本文中の見出し(h2/h3)が2つ以上ある場合のみ自動表示されます。

== Changelog ==

= 0.1.0 =
* 初回リリース(アーキテクチャに基づくスキャフォールド)

== Copyright ==

fellow WordPress Theme, (C) 2026 setsna
fellow is distributed under the terms of the GNU GPL v2 or later.
同梱素材のライセンスは LICENSE ファイルを参照してください。
