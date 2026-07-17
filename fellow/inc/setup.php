<?php
/**
 * テーマセットアップ:theme support、メニュー登録、画像サイズ。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * テーマの基本サポートを宣言する。
 */
function fellow_setup() {
	load_theme_textdomain( 'fellow', get_template_directory() . '/languages' );

	add_theme_support( 'title-tag' );
	add_theme_support( 'post-thumbnails' );
	add_theme_support( 'automatic-feed-links' );
	add_theme_support( 'responsive-embeds' );
	add_theme_support(
		'html5',
		array(
			'search-form',
			'comment-form',
			'comment-list',
			'gallery',
			'caption',
			'style',
			'script',
		)
	);
	add_theme_support(
		'custom-logo',
		array(
			'height'      => 80,
			'width'       => 320,
			'flex-height' => true,
			'flex-width'  => true,
		)
	);

	register_nav_menus(
		array(
			'primary'     => __( 'ヘッダーメニュー', 'fellow' ),
			'footer-site' => __( 'フッター「サイト」メニュー', 'fellow' ),
		)
	);

	// カード用(4:3)と記事詳細アイキャッチ用(16:9)。
	add_image_size( 'fellow-card', 800, 600, true );
	add_image_size( 'fellow-eyecatch', 1280, 720, true );
}
add_action( 'after_setup_theme', 'fellow_setup' );

/**
 * 埋め込みコンテンツの基準幅。
 */
function fellow_content_width() {
	$GLOBALS['content_width'] = 720;
}
add_action( 'after_setup_theme', 'fellow_content_width', 0 );
