<?php
/**
 * アセット読み込みとフロントエンドの軽量化。
 *
 * - main.css を1本だけ読み込む(style.css はヘッダー情報のみ)。既定では HTML に埋め込む
 * - カスタマイザー値は wp_add_inline_style で CSS 変数として注入
 * - ブロックライブラリCSS・絵文字スクリプトを除去
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * style.css ヘッダーからテーマバージョンを取得する(キャッシュバスター用)。
 *
 * @return string
 */
function fellow_theme_version() {
	static $version = null;

	if ( null === $version ) {
		$version = (string) wp_get_theme( get_template() )->get( 'Version' );
	}

	return $version;
}

/**
 * 配布物に圧縮版があればそちらの相対パスを返す。
 *
 * ソースは読みやすさのため圧縮しない方針なので、リポジトリには
 * main.css / main.js しか無い。CI が zip を作るときに .min を生成するため、
 * 配布された状態では圧縮版が使われる。無ければ元のファイルに落ちる。
 *
 * @param string $relative テーマ直下からの相対パス(例: assets/css/main.css)。
 * @return string
 */
function fellow_asset_file( $relative ) {
	$min = preg_replace( '/\.(css|js)$/', '.min.$1', $relative );

	if ( $min !== $relative && file_exists( get_theme_file_path( $min ) ) ) {
		return $min;
	}

	return $relative;
}

/**
 * fellow_asset_file() の URL 版。
 *
 * @param string $relative テーマ直下からの相対パス。
 * @return string
 */
function fellow_asset_uri( $relative ) {
	return get_theme_file_uri( fellow_asset_file( $relative ) );
}

/**
 * main.css を <link> ではなく <style> として HTML に埋め込むか。
 *
 * @return bool
 */
function fellow_inline_main_css() {
	return (bool) get_theme_mod( 'fellow_inline_css', true );
}

/**
 * CSS / JS の読み込み。
 */
function fellow_enqueue_assets() {
	$version = fellow_theme_version();

	/*
	 * 親テーマの style.css はヘッダー情報しか持たない(実体は main.css)。
	 * それでも読み込むと、中身の無いCSSのために描画をブロックする往復が
	 * 1回増える。子テーマが無いときは読み込まない。
	 */
	$main_css = fellow_asset_file( 'assets/css/main.css' );

	wp_enqueue_style(
		'fellow-main',
		get_theme_file_uri( $main_css ),
		array(),
		$version
	);
	wp_add_inline_style( 'fellow-main', fellow_inline_css() );

	/*
	 * CSS を HTML に埋め込む。
	 *
	 * <link> で読むと、ブラウザは HTML を受け取ってから CSS を取りに行き、
	 * それが届くまで何も描画しない。回線の遅いスマホではこの往復1回が
	 * そのまま初回描画(FCP)の遅れになる。埋め込めば HTML と一緒に届く。
	 *
	 * 埋め込み自体はコアの wp_maybe_inline_styles() に任せる
	 * (ブロックのCSSを埋め込むのと同じ仕組み)。'path' を渡すと、
	 * サイズ上限の範囲でコアが <style> に差し替える。
	 *
	 * ページごとに CSS を毎回受け取ることになるが、圧縮後で約8KB
	 * (gzip 時)なので、検索から1ページだけ読んで帰る読者が多いブログでは
	 * 往復を減らす方が効く。キャッシュ系プラグインが古い CSS だけを
	 * 配り続ける、という食い違いも起きなくなる。
	 */
	if ( fellow_inline_main_css() ) {
		wp_style_add_data( 'fellow-main', 'path', get_theme_file_path( $main_css ) );
	}

	/*
	 * 子テーマの style.css は上書き用のCSSを持つので読み込む。
	 * main.css より後に出さないと、同じ詳細度の指定で上書きできない。
	 */
	if ( is_child_theme() ) {
		wp_enqueue_style(
			'fellow-child',
			get_stylesheet_uri(),
			array( 'fellow-main' ),
			(string) wp_get_theme()->get( 'Version' )
		);
	}

	// ハンバーガー/検索トグル/TOC追従を1ファイルに集約し defer で読み込む。
	// TOC等のページ限定機能は main.js 側で対象要素の有無を判定する。
	wp_enqueue_script(
		'fellow-main',
		fellow_asset_uri( 'assets/js/main.js' ),
		array(),
		$version,
		array(
			'strategy'  => 'defer',
			'in_footer' => true,
		)
	);

	if ( is_singular() && comments_open() && get_option( 'thread_comments' ) ) {
		wp_enqueue_script( 'comment-reply' );
	}
}
add_action( 'wp_enqueue_scripts', 'fellow_enqueue_assets' );

/**
 * main.css が埋め込みの上限に収まるよう、上限を main.css の分だけ広げる。
 *
 * コアの上限(既定 20KB)は埋め込む CSS の合計に対するもので、main.css は
 * 圧縮後でも約37KBあり単独で超える。既存の上限はそのまま残し、
 * プラグインが同じ仕組みで埋め込む CSS の枠を奪わないよう上乗せにする。
 *
 * @param int $limit 埋め込む CSS の合計上限(バイト)。
 * @return int
 */
function fellow_styles_inline_size_limit( $limit ) {
	if ( ! fellow_inline_main_css() ) {
		return $limit;
	}

	$size = wp_filesize( get_theme_file_path( fellow_asset_file( 'assets/css/main.css' ) ) );

	return (int) $limit + (int) $size;
}
add_filter( 'styles_inline_size_limit', 'fellow_styles_inline_size_limit' );

/**
 * JS有効の印(.js)を head 内で即座に付与する。
 *
 * main.js は defer かつフッター読み込みのため、そこで付与すると
 * ハンバーガーメニューや検索フォームが「開いた状態」で一瞬描画されてしまう。
 * CSSより先に効かせる必要があるので、head の先頭で同期実行する。
 */
function fellow_print_js_detection() {
	wp_print_inline_script_tag(
		"document.documentElement.classList.add('js');",
		array( 'id' => 'fellow-js-detection' )
	);
}
add_action( 'wp_head', 'fellow_print_js_detection', 0 );

/**
 * ブロックエディタにもカスタマイザーのCSS変数を渡す。
 *
 * add_editor_style() は静的ファイルしか受け付けないため、
 * 動的な値はエディタ設定に直接追加する。エディタ側のスタイルは
 * セレクタが .editor-styles-wrapper に置換されるので body{} に入れる。
 *
 * @param array $settings ブロックエディタ設定。
 * @return array
 */
function fellow_editor_custom_properties( $settings ) {
	$settings['styles'][] = array(
		'css' => 'body{' . fellow_css_custom_properties() . '}',
	);

	return $settings;
}
add_filter( 'block_editor_settings_all', 'fellow_editor_custom_properties' );

/**
 * コアが出力するブロックライブラリ等のCSSを除去して軽量化する。
 */
function fellow_dequeue_core_styles() {
	wp_dequeue_style( 'wp-block-library' );
	wp_dequeue_style( 'wp-block-library-theme' );
	wp_dequeue_style( 'classic-theme-styles' );
	wp_dequeue_style( 'global-styles' );
}
add_action( 'wp_enqueue_scripts', 'fellow_dequeue_core_styles', 100 );

/**
 * 絵文字関連のスクリプト/スタイルを無効化する。
 */
function fellow_disable_emoji() {
	remove_action( 'wp_head', 'print_emoji_detection_script', 7 );
	remove_action( 'wp_print_styles', 'print_emoji_styles' );
	remove_action( 'admin_print_scripts', 'print_emoji_detection_script' );
	remove_action( 'admin_print_styles', 'print_emoji_styles' );
	remove_filter( 'the_content_feed', 'wp_staticize_emoji' );
	remove_filter( 'comment_text_rss', 'wp_staticize_emoji' );
	remove_filter( 'wp_mail', 'wp_staticize_emoji_for_email' );
	add_filter( 'emoji_svg_url', '__return_false' );
}
add_action( 'init', 'fellow_disable_emoji' );

/**
 * リンクにマウスを乗せた時点で、次のページの HTML を先読みする。
 *
 * WordPress 6.8 以降はコアが Speculation Rules を出力するが、既定は
 * 「クリックした瞬間(conservative)」なので先読みの効果がほとんど無い。
 * 「マウスを約0.2秒乗せたら(moderate)」に早め、クリックまでの間に
 * サーバーの応答待ちを済ませる。共用サーバーでは応答待ちが遅さの
 * 大部分を占めるため、体感の差が大きい。
 *
 * prefetch(HTMLの取得のみ)にとどめ、prerender(裏で描画まで行う)は
 * 使わない。prerender はページ内のスクリプトを実行するため、
 * 広告やアクセス解析が「見られていないページ」を数えるおそれがある。
 * ログイン中はコアが先読み自体を止める。
 *
 * @param array|null $config コアの設定。null なら先読みは無効化されている。
 * @return array|null
 */
function fellow_speculation_rules_configuration( $config ) {
	if ( ! is_array( $config ) ) {
		return $config;
	}

	return array(
		'mode'      => 'prefetch',
		'eagerness' => 'moderate',
	);
}
add_filter( 'wp_speculation_rules_configuration', 'fellow_speculation_rules_configuration' );
