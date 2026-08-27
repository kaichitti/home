<?php
/**
 * ブロックパターン(記事内パーツ)。
 *
 * 独自ブロックではなくパターンで提供する。コアブロックの組み合わせ+CSSなので
 * JSもビルドも要らず、zipを上げるだけという方針を崩さずに済む。
 * 動きが要るタブだけは、パターン+JSの上乗せ(段階的強化)で実現する。
 *
 * FAQ に FAQPage の構造化データは付けない。Google の FAQ リッチリザルトは
 * 2023年に政府・医療系へ限定されたのち完全に終了しており、
 * 出しても検索結果には反映されないため。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * パターンのカテゴリーを登録する。
 */
function fellow_register_pattern_category() {
	if ( ! function_exists( 'register_block_pattern_category' ) ) {
		return;
	}

	register_block_pattern_category(
		'fellow',
		array( 'label' => __( 'fellow の記事パーツ', 'fellow' ) )
	);
}
add_action( 'init', 'fellow_register_pattern_category', 9 );

/**
 * パターンを登録する。
 */
function fellow_register_block_patterns() {
	if ( ! function_exists( 'register_block_pattern' ) ) {
		return;
	}

	foreach ( fellow_block_patterns() as $slug => $pattern ) {
		register_block_pattern( 'fellow/' . $slug, $pattern );
	}
}
add_action( 'init', 'fellow_register_block_patterns', 10 );

/**
 * パターンの定義を返す。
 *
 * @return array
 */
function fellow_block_patterns() {
	$patterns = array();

	// --- ふきだし ---------------------------------------------------.
	$balloon_body = esc_html__( 'ここに話し言葉が入ります。左のアイコンは画像を差し替えてください。', 'fellow' );
	$balloon_name = esc_html__( '名前', 'fellow' );

	$patterns['balloon-left'] = array(
		'title'      => __( 'ふきだし(左)', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( 'ふきだし', '会話', 'balloon' ),
		'content'    => <<<HTML
<!-- wp:group {"className":"fellow-balloon fellow-balloon--left"} -->
<div class="wp-block-group fellow-balloon fellow-balloon--left"><!-- wp:group {"className":"fellow-balloon__speaker"} -->
<div class="wp-block-group fellow-balloon__speaker"><!-- wp:image {"width":"56px","height":"56px","className":"fellow-balloon__avatar"} -->
<figure class="wp-block-image fellow-balloon__avatar"><img alt="" style="width:56px;height:56px"/></figure>
<!-- /wp:image -->

<!-- wp:paragraph {"className":"fellow-balloon__name"} -->
<p class="fellow-balloon__name">{$balloon_name}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->

<!-- wp:paragraph {"className":"fellow-balloon__body"} -->
<p class="fellow-balloon__body">{$balloon_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->
HTML,
	);

	$patterns['balloon-right'] = array(
		'title'      => __( 'ふきだし(右)', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( 'ふきだし', '会話', 'balloon' ),
		'content'    => <<<HTML
<!-- wp:group {"className":"fellow-balloon fellow-balloon--right"} -->
<div class="wp-block-group fellow-balloon fellow-balloon--right"><!-- wp:group {"className":"fellow-balloon__speaker"} -->
<div class="wp-block-group fellow-balloon__speaker"><!-- wp:image {"width":"56px","height":"56px","className":"fellow-balloon__avatar"} -->
<figure class="wp-block-image fellow-balloon__avatar"><img alt="" style="width:56px;height:56px"/></figure>
<!-- /wp:image -->

<!-- wp:paragraph {"className":"fellow-balloon__name"} -->
<p class="fellow-balloon__name">{$balloon_name}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->

<!-- wp:paragraph {"className":"fellow-balloon__body"} -->
<p class="fellow-balloon__body">{$balloon_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->
HTML,
	);

	// --- ステップ ---------------------------------------------------.
	$step1 = esc_html__( '最初の手順', 'fellow' );
	$step2 = esc_html__( '次の手順', 'fellow' );
	$step3 = esc_html__( '最後の手順', 'fellow' );
	$step_body = esc_html__( 'ここに説明を書きます。', 'fellow' );

	$patterns['steps'] = array(
		'title'      => __( 'ステップ(手順)', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( 'ステップ', '手順', 'step' ),
		'content'    => <<<HTML
<!-- wp:group {"className":"fellow-steps"} -->
<div class="wp-block-group fellow-steps"><!-- wp:group {"className":"fellow-steps__item"} -->
<div class="wp-block-group fellow-steps__item"><!-- wp:heading {"level":3,"className":"fellow-steps__title"} -->
<h3 class="wp-block-heading fellow-steps__title">{$step1}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{$step_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->

<!-- wp:group {"className":"fellow-steps__item"} -->
<div class="wp-block-group fellow-steps__item"><!-- wp:heading {"level":3,"className":"fellow-steps__title"} -->
<h3 class="wp-block-heading fellow-steps__title">{$step2}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{$step_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->

<!-- wp:group {"className":"fellow-steps__item"} -->
<div class="wp-block-group fellow-steps__item"><!-- wp:heading {"level":3,"className":"fellow-steps__title"} -->
<h3 class="wp-block-heading fellow-steps__title">{$step3}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{$step_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group --></div>
<!-- /wp:group -->
HTML,
	);

	// --- FAQ --------------------------------------------------------.
	$q1 = esc_html__( 'よくある質問をここに書きます。', 'fellow' );
	$a1 = esc_html__( '答えをここに書きます。', 'fellow' );

	$patterns['faq'] = array(
		'title'      => __( 'FAQ(質問と回答)', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( 'FAQ', '質問', 'よくある質問' ),
		'content'    => <<<HTML
<!-- wp:group {"className":"fellow-faq"} -->
<div class="wp-block-group fellow-faq"><!-- wp:group {"className":"fellow-faq__item"} -->
<div class="wp-block-group fellow-faq__item"><!-- wp:paragraph {"className":"fellow-faq__q"} -->
<p class="fellow-faq__q">{$q1}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph {"className":"fellow-faq__a"} -->
<p class="fellow-faq__a">{$a1}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->

<!-- wp:group {"className":"fellow-faq__item"} -->
<div class="wp-block-group fellow-faq__item"><!-- wp:paragraph {"className":"fellow-faq__q"} -->
<p class="fellow-faq__q">{$q1}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph {"className":"fellow-faq__a"} -->
<p class="fellow-faq__a">{$a1}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group --></div>
<!-- /wp:group -->
HTML,
	);

	// --- キャプションボックス ----------------------------------------.
	$caption_label = esc_html__( 'ポイント', 'fellow' );
	$caption_body  = esc_html__( '囲みで強調したい内容をここに書きます。', 'fellow' );

	$patterns['caption-box'] = array(
		'title'      => __( 'キャプションボックス', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( '囲み', 'ボックス', 'ポイント' ),
		'content'    => <<<HTML
<!-- wp:group {"className":"fellow-capbox"} -->
<div class="wp-block-group fellow-capbox"><!-- wp:paragraph {"className":"fellow-capbox__label"} -->
<p class="fellow-capbox__label">{$caption_label}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{$caption_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->
HTML,
	);

	$warn_label = esc_html__( '注意', 'fellow' );
	$warn_body  = esc_html__( '読者に気をつけてほしいことをここに書きます。', 'fellow' );

	$patterns['caption-box-warning'] = array(
		'title'      => __( 'キャプションボックス(注意)', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( '囲み', 'ボックス', '注意' ),
		'content'    => <<<HTML
<!-- wp:group {"className":"fellow-capbox fellow-capbox--warning"} -->
<div class="wp-block-group fellow-capbox fellow-capbox--warning"><!-- wp:paragraph {"className":"fellow-capbox__label"} -->
<p class="fellow-capbox__label">{$warn_label}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{$warn_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->
HTML,
	);

	// --- ボックスメニュー --------------------------------------------.
	$menu_title = esc_html__( 'リンク先の見出し', 'fellow' );
	$menu_desc  = esc_html__( '短い説明', 'fellow' );

	$patterns['box-menu'] = array(
		'title'      => __( 'ボックスメニュー', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( 'メニュー', 'リンク', 'ボックス' ),
		'content'    => <<<HTML
<!-- wp:columns {"className":"fellow-boxmenu"} -->
<div class="wp-block-columns fellow-boxmenu"><!-- wp:column {"className":"fellow-boxmenu__item"} -->
<div class="wp-block-column fellow-boxmenu__item"><!-- wp:paragraph {"className":"fellow-boxmenu__title"} -->
<p class="fellow-boxmenu__title"><a href="#">{$menu_title}</a></p>
<!-- /wp:paragraph -->

<!-- wp:paragraph {"className":"fellow-boxmenu__desc"} -->
<p class="fellow-boxmenu__desc">{$menu_desc}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:column -->

<!-- wp:column {"className":"fellow-boxmenu__item"} -->
<div class="wp-block-column fellow-boxmenu__item"><!-- wp:paragraph {"className":"fellow-boxmenu__title"} -->
<p class="fellow-boxmenu__title"><a href="#">{$menu_title}</a></p>
<!-- /wp:paragraph -->

<!-- wp:paragraph {"className":"fellow-boxmenu__desc"} -->
<p class="fellow-boxmenu__desc">{$menu_desc}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:column --></div>
<!-- /wp:columns -->
HTML,
	);

	// --- バナーリンク ------------------------------------------------.
	$banner_title = esc_html__( 'あわせて読みたい記事のタイトル', 'fellow' );
	$banner_label = esc_html__( 'あわせて読みたい', 'fellow' );

	$patterns['banner-link'] = array(
		'title'      => __( 'バナーリンク', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( 'バナー', 'リンク', '関連記事' ),
		'content'    => <<<HTML
<!-- wp:group {"className":"fellow-banner"} -->
<div class="wp-block-group fellow-banner"><!-- wp:paragraph {"className":"fellow-banner__label"} -->
<p class="fellow-banner__label">{$banner_label}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph {"className":"fellow-banner__title"} -->
<p class="fellow-banner__title"><a href="#">{$banner_title}</a></p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->
HTML,
	);

	// --- タブ --------------------------------------------------------.
	$tab1 = esc_html__( 'タブ1', 'fellow' );
	$tab2 = esc_html__( 'タブ2', 'fellow' );
	$tab3 = esc_html__( 'タブ3', 'fellow' );
	$tab_body = esc_html__( 'タブの中身をここに書きます。', 'fellow' );

	$patterns['tabs'] = array(
		'title'      => __( 'タブ切り替え', 'fellow' ),
		'categories' => array( 'fellow' ),
		'keywords'   => array( 'タブ', 'tab', '切り替え' ),
		'description' => __( '見出しがタブの名前になります。JavaScriptが無効な環境では、見出し付きの段組みとして順に表示されます。', 'fellow' ),
		'content'    => <<<HTML
<!-- wp:group {"className":"fellow-tabs"} -->
<div class="wp-block-group fellow-tabs"><!-- wp:group {"className":"fellow-tabs__panel"} -->
<div class="wp-block-group fellow-tabs__panel"><!-- wp:heading {"level":3,"className":"fellow-tabs__label"} -->
<h3 class="wp-block-heading fellow-tabs__label">{$tab1}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{$tab_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->

<!-- wp:group {"className":"fellow-tabs__panel"} -->
<div class="wp-block-group fellow-tabs__panel"><!-- wp:heading {"level":3,"className":"fellow-tabs__label"} -->
<h3 class="wp-block-heading fellow-tabs__label">{$tab2}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{$tab_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->

<!-- wp:group {"className":"fellow-tabs__panel"} -->
<div class="wp-block-group fellow-tabs__panel"><!-- wp:heading {"level":3,"className":"fellow-tabs__label"} -->
<h3 class="wp-block-heading fellow-tabs__label">{$tab3}</h3>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>{$tab_body}</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group --></div>
<!-- /wp:group -->
HTML,
	);

	// --- アコーディオン ----------------------------------------------.
	// コアの details ブロック(WordPress 6.3以降)を使う。JSは不要。
	$acc_summary = esc_html__( 'クリックすると開きます', 'fellow' );
	$acc_body    = esc_html__( '折りたたんでおきたい内容をここに書きます。', 'fellow' );

	$patterns['accordion'] = array(
		'title'       => __( 'アコーディオン(開閉)', 'fellow' ),
		'categories'  => array( 'fellow' ),
		'keywords'    => array( 'アコーディオン', '開閉', '折りたたみ' ),
		'description' => __( 'HTMLの details 要素を使うため、JavaScriptが無効でも開閉できます。', 'fellow' ),
		'content'     => <<<HTML
<!-- wp:details {"className":"fellow-accordion","summary":"{$acc_summary}"} -->
<details class="wp-block-details fellow-accordion"><summary>{$acc_summary}</summary><!-- wp:paragraph -->
<p>{$acc_body}</p>
<!-- /wp:paragraph --></details>
<!-- /wp:details -->
HTML,
	);

	return $patterns;
}
