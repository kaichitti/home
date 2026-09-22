<?php
/**
 * アセット読み込みとフロントエンドの軽量化。
 *
 * - main.css を1本だけ読み込む(style.css はヘッダー情報のみ)
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
 * 配布物に圧縮版があればそちらのURLを返す。
 *
 * ソースは読みやすさのため圧縮しない方針なので、リポジトリには
 * main.css / main.js しか無い。CI が zip を作るときに .min を生成するため、
 * 配布された状態では圧縮版が使われる。無ければ元のファイルに落ちる。
 *
 * @param string $relative テーマ直下からの相対パス(例: assets/css/main.css)。
 * @return string
 */
function fellow_asset_uri( $relative ) {
	$min = preg_replace( '/\.(css|js)$/', '.min.$1', $relative );

	if ( $min !== $relative && file_exists( get_theme_file_path( $min ) ) ) {
		return get_theme_file_uri( $min );
	}

	return get_theme_file_uri( $relative );
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
	wp_enqueue_style(
		'fellow-main',
		fellow_asset_uri( 'assets/css/main.css' ),
		array(),
		$version
	);
	wp_add_inline_style( 'fellow-main', fellow_inline_css() );

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
