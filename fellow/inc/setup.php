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
	add_theme_support( 'align-wide' );

	// エディタの見た目を公開画面に寄せる(main.css をそのまま流用すると
	// .entry-content 前提のセレクタが効かないため、ブロック用の専用CSSを持つ)。
	// add_editor_style() が立てるのは 'editor-style'(旧エディタ用)のみで、
	// ブロックエディタは 'editor-styles'(複数形)を見るため両方必要。
	add_theme_support( 'editor-styles' );
	add_editor_style( 'assets/css/editor.css' );
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
 * フッターのウィジェットエリアを登録する。
 *
 * ウィジェットエリアが1つも無いとWordPressは「外観 > ウィジェット」を
 * wp_die() で拒否するため、配布テーマとしては最低1つ持たせる。
 */
function fellow_widgets_init() {
	register_sidebar(
		array(
			'name'          => __( 'フッターウィジェットエリア', 'fellow' ),
			'id'            => 'footer-widgets',
			'description'   => __( 'フッターの列として表示されます。空のときは何も出力されません。', 'fellow' ),
			'before_widget' => '<section id="%1$s" class="widget %2$s">',
			'after_widget'  => '</section>',
			'before_title'  => '<h2 class="site-footer__heading">',
			'after_title'   => '</h2>',
		)
	);
}
add_action( 'widgets_init', 'fellow_widgets_init' );

/**
 * 埋め込みコンテンツの基準幅。
 */
function fellow_content_width() {
	$GLOBALS['content_width'] = 720;
}
add_action( 'after_setup_theme', 'fellow_content_width', 0 );
