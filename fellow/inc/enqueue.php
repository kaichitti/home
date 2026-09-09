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
 * CSS / JS の読み込み。
 */
function fellow_enqueue_assets() {
	$version = fellow_theme_version();

	wp_enqueue_style( 'fellow-base', get_stylesheet_uri(), array(), $version );
	wp_enqueue_style(
		'fellow-main',
		get_template_directory_uri() . '/assets/css/main.css',
		array( 'fellow-base' ),
		$version
	);
	wp_add_inline_style( 'fellow-main', fellow_inline_css() );

	// ハンバーガー/検索トグル/TOC追従を1ファイルに集約し defer で読み込む。
	// TOC等のページ限定機能は main.js 側で対象要素の有無を判定する。
	wp_enqueue_script(
		'fellow-main',
		get_template_directory_uri() . '/assets/js/main.js',
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
