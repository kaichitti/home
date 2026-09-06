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
	/*
	 * 登録順に意味がある。テーマ切替時、WordPress は前テーマのウィジェットを
	 * 「最初に登録されたエリア」へ移すため(retrieve_widgets)、サイドバーを
	 * 先頭にしておくと引き継いだウィジェットが自然な位置に収まる。
	 */
	register_sidebar(
		array(
			'name'          => __( 'サイドバー', 'fellow' ),
			'id'            => 'sidebar-main',
			'description'   => __( '記事詳細と記事一覧・アーカイブの横に表示されます。空のときはサイドバー自体が出ず、本文が全幅になります。', 'fellow' ),
			'before_widget' => '<section id="%1$s" class="widget %2$s">',
			'after_widget'  => '</section>',
			'before_title'  => '<h2 class="widget__title">',
			'after_title'   => '</h2>',
		)
	);

	register_sidebar(
		array(
			'name'          => __( 'サイドバー(スクロール追従)', 'fellow' ),
			'id'            => 'sidebar-sticky',
			'description'   => __( 'サイドバーの下部に置かれ、スクロールしても画面内に留まります。目次や人気記事の設置に向いています。', 'fellow' ),
			'before_widget' => '<section id="%1$s" class="widget %2$s">',
			'after_widget'  => '</section>',
			'before_title'  => '<h2 class="widget__title">',
			'after_title'   => '</h2>',
		)
	);

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
 * 初回有効化時に、フッターへ引き継がれたウィジェットを使用停止中へ戻す。
 *
 * fellow はフッターにカテゴリーとアーカイブを既に固定表示しているため、
 * 他テーマから同じ内容のウィジェットが流れ込むと二重に並んでしまう。
 * サイドバーを先に登録しているので通常はそちらへ移るが、
 * 登録順に依存しない保険としてフッター側だけを空にしておく。
 *
 * 削除ではなく「使用停止中のウィジェット」へ移すだけなので、
 * 必要なら「外観 > ウィジェット」から元に戻せる。
 * 一度きりの処理で、利用者が自分で配置したウィジェットには触れない。
 */
function fellow_reset_inherited_widgets() {
	if ( get_theme_mod( 'fellow_widgets_initialized' ) ) {
		return;
	}

	set_theme_mod( 'fellow_widgets_initialized', true );

	$sidebars = (array) get_option( 'sidebars_widgets', array() );

	if ( empty( $sidebars['footer-widgets'] ) ) {
		return;
	}

	$inactive = isset( $sidebars['wp_inactive_widgets'] ) ? (array) $sidebars['wp_inactive_widgets'] : array();

	$sidebars['wp_inactive_widgets'] = array_merge( $inactive, (array) $sidebars['footer-widgets'] );
	$sidebars['footer-widgets']      = array();

	update_option( 'sidebars_widgets', $sidebars );
}
// retrieve_widgets() が優先度10で走るため、その後に実行する。
add_action( 'after_switch_theme', 'fellow_reset_inherited_widgets', 20 );

/**
 * 初回有効化時、サイドバーが空ならテーマ既定のウィジェットを置く。
 *
 * テーマ選択画面に出る見本(screenshot.png)は、メニューもサイドバーも
 * 設定済みの状態を写している。ところが有効化した直後のサイトは
 * サイドバーが空で、その場合サイドバー自体が描画されない作りのため、
 * 「見本とまるで違う」という印象になる。その差を埋めるための処理。
 *
 * 既にウィジェットが置かれている場合は何もしない。
 * 置いた内容は「外観 > ウィジェット」から自由に変更・削除できる。
 */
function fellow_seed_default_widgets() {
	if ( get_theme_mod( 'fellow_default_widgets_placed' ) ) {
		return;
	}

	set_theme_mod( 'fellow_default_widgets_placed', true );

	$sidebars = (array) get_option( 'sidebars_widgets', array() );

	// 利用者が既に何か置いている(他テーマから引き継いだ場合も含む)なら触らない。
	if ( ! empty( $sidebars['sidebar-main'] ) ) {
		return;
	}

	$defaults = array(
		'search'       => array(
			'title' => __( 'サイト内検索', 'fellow' ),
		),
		'categories'   => array(
			'title'        => __( 'カテゴリー', 'fellow' ),
			'count'        => 0,
			'hierarchical' => 1,
			'dropdown'     => 0,
		),
		'archives'     => array(
			'title'    => __( 'アーカイブ', 'fellow' ),
			'count'    => 0,
			'dropdown' => 0,
		),
		'recent-posts' => array(
			'title'     => __( '最近の記事', 'fellow' ),
			'number'    => 5,
			'show_date' => 0,
		),
	);

	$placed = array();

	foreach ( $defaults as $base => $instance ) {
		$option = 'widget_' . $base;
		$stored = (array) get_option( $option, array() );

		// 既存インスタンスと衝突しない番号を選ぶ。
		$index = 2;
		foreach ( array_keys( $stored ) as $key ) {
			if ( is_numeric( $key ) && (int) $key >= $index ) {
				$index = (int) $key + 1;
			}
		}

		$stored[ $index ]       = $instance;
		$stored['_multiwidget'] = 1;

		update_option( $option, $stored );

		$placed[] = $base . '-' . $index;
	}

	$sidebars['sidebar-main'] = $placed;

	update_option( 'sidebars_widgets', $sidebars );
}
// 引き継ぎウィジェットの整理(優先度20)より後に走らせる。
add_action( 'after_switch_theme', 'fellow_seed_default_widgets', 21 );

/**
 * 埋め込みコンテンツの基準幅。
 */
function fellow_content_width() {
	$GLOBALS['content_width'] = 720;
}
add_action( 'after_setup_theme', 'fellow_content_width', 0 );
