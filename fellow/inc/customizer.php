<?php
/**
 * カスタマイザー定義。
 *
 * テーマファイルを書き換えずに見た目を変えられるよう、
 * 値はすべて CSS 変数(fellow_inline_css)経由で反映する。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * デフォルトのアクセントカラー。
 */
const FELLOW_DEFAULT_ACCENT = '#C2EEF2';

/**
 * チェックボックス用サニタイズ。
 *
 * @param mixed $checked 入力値。
 * @return bool
 */
function fellow_sanitize_checkbox( $checked ) {
	return (bool) $checked;
}

/**
 * ピックアップの取得元のサニタイズ。
 *
 * @param mixed $value 入力値。
 * @return string
 */
function fellow_sanitize_pickup_source( $value ) {
	return in_array( $value, array( 'sticky', 'recent', 'none' ), true ) ? $value : 'sticky';
}

/**
 * ピックアップ件数のサニタイズ。
 *
 * @param mixed $value 入力値。
 * @return int
 */
function fellow_sanitize_pickup_count( $value ) {
	$value = (int) $value;

	return ( $value >= 2 && $value <= 5 ) ? $value : 3;
}

/**
 * サイドバー位置のサニタイズ。
 *
 * @param mixed $value 入力値。
 * @return string
 */
function fellow_sanitize_sidebar_position( $value ) {
	return in_array( $value, array( 'right', 'left', 'none' ), true ) ? $value : 'right';
}

/**
 * 記事一覧レイアウトのサニタイズ。
 *
 * @param mixed $value 入力値。
 * @return string
 */
function fellow_sanitize_list_layout( $value ) {
	return in_array( $value, array( 'list', 'card' ), true ) ? $value : 'list';
}

/**
 * 本文幅セレクト用サニタイズ(65〜75文字、5刻み)。
 *
 * @param mixed $value 入力値。
 * @return int
 */
function fellow_sanitize_measure( $value ) {
	$value = (int) $value;

	return in_array( $value, array( 65, 70, 75 ), true ) ? $value : 70;
}

/**
 * セクション・設定・コントロールの登録。
 *
 * @param WP_Customize_Manager $wp_customize カスタマイザーマネージャ。
 */
function fellow_customize_register( $wp_customize ) {
	// --- カラー -------------------------------------------------------.
	$wp_customize->add_setting(
		'fellow_accent_color',
		array(
			'default'           => FELLOW_DEFAULT_ACCENT,
			'sanitize_callback' => 'sanitize_hex_color',
		)
	);
	$wp_customize->add_control(
		new WP_Customize_Color_Control(
			$wp_customize,
			'fellow_accent_color',
			array(
				'label'   => __( 'アクセントカラー', 'fellow' ),
				'section' => 'colors',
			)
		)
	);

	// --- SNSリンク(空欄なら非表示) ---------------------------------.
	$wp_customize->add_section(
		'fellow_sns',
		array(
			'title'    => __( 'SNSリンク', 'fellow' ),
			'priority' => 90,
		)
	);

	$sns_fields = array(
		'fellow_sns_x'      => __( 'X(旧Twitter)URL', 'fellow' ),
		'fellow_sns_rss'    => __( 'RSS URL', 'fellow' ),
		'fellow_sns_feedly' => __( 'Feedly URL', 'fellow' ),
	);

	foreach ( $sns_fields as $setting_id => $label ) {
		$wp_customize->add_setting(
			$setting_id,
			array(
				'default'           => '',
				'sanitize_callback' => 'esc_url_raw',
			)
		);
		$wp_customize->add_control(
			$setting_id,
			array(
				'label'       => $label,
				'section'     => 'fellow_sns',
				'type'        => 'url',
				'description' => __( '空欄にすると表示されません。', 'fellow' ),
			)
		);
	}

	// --- レイアウト ---------------------------------------------------.
	$wp_customize->add_section(
		'fellow_layout',
		array(
			'title'    => __( 'レイアウト', 'fellow' ),
			'priority' => 95,
		)
	);

	$wp_customize->add_setting(
		'fellow_sidebar_position',
		array(
			'default'           => 'right',
			'sanitize_callback' => 'fellow_sanitize_sidebar_position',
		)
	);
	$wp_customize->add_control(
		'fellow_sidebar_position',
		array(
			'label'       => __( 'サイドバーの位置', 'fellow' ),
			'section'     => 'fellow_layout',
			'type'        => 'select',
			'choices'     => array(
				'right' => __( '右サイドバー(2カラム)', 'fellow' ),
				'left'  => __( '左サイドバー(2カラム)', 'fellow' ),
				'none'  => __( 'サイドバーなし(1カラム)', 'fellow' ),
			),
			'description' => __( '記事詳細と記事一覧・アーカイブに適用されます。固定ページは常に1カラムです。ウィジェットが未設定の場合も1カラムになります。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_list_layout',
		array(
			'default'           => 'list',
			'sanitize_callback' => 'fellow_sanitize_list_layout',
		)
	);
	$wp_customize->add_control(
		'fellow_list_layout',
		array(
			'label'       => __( '記事一覧のレイアウト', 'fellow' ),
			'section'     => 'fellow_layout',
			'type'        => 'select',
			'choices'     => array(
				'list' => __( 'リスト型(サムネイルは右に小さく)', 'fellow' ),
				'card' => __( 'カード型(2列・サムネイルは上に大きく)', 'fellow' ),
			),
			'description' => __( 'トップ・カテゴリー・タグ・検索結果に適用されます。カード型はアイキャッチを設定した記事が多いブログ向けです。未設定の記事では画像枠を出さないため、混在すると高さが不揃いに見えます。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_measure',
		array(
			'default'           => 70,
			'sanitize_callback' => 'fellow_sanitize_measure',
		)
	);
	$wp_customize->add_control(
		'fellow_measure',
		array(
			'label'       => __( '本文の1行あたり文字数', 'fellow' ),
			'section'     => 'fellow_layout',
			'type'        => 'select',
			'choices'     => array(
				65 => __( '65文字(狭め)', 'fellow' ),
				70 => __( '70文字(標準)', 'fellow' ),
				75 => __( '75文字(広め)', 'fellow' ),
			),
			'description' => __( '記事本文の最大行長を切り替えます。', 'fellow' ),
		)
	);

	// --- トップページ ---------------------------------------------------.
	$wp_customize->add_section(
		'fellow_front',
		array(
			'title'       => __( 'トップページ', 'fellow' ),
			'priority'    => 94,
			'description' => __( 'ブログトップの最上部に表示する内容を設定します。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_hero_display',
		array(
			'default'           => true,
			'sanitize_callback' => 'fellow_sanitize_checkbox',
		)
	);
	$wp_customize->add_control(
		'fellow_hero_display',
		array(
			'label'       => __( 'ヘッダー下に紹介の帯を表示する', 'fellow' ),
			'section'     => 'fellow_front',
			'type'        => 'checkbox',
			'description' => __( '見出しもリード文も空のときは、チェックが入っていても表示されません。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_hero_title',
		array(
			'default'           => '',
			'sanitize_callback' => 'sanitize_text_field',
		)
	);
	$wp_customize->add_control(
		'fellow_hero_title',
		array(
			'label'       => __( '帯の見出し', 'fellow' ),
			'section'     => 'fellow_front',
			'type'        => 'text',
			'description' => __( '空欄にするとサイト名が入ります。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_hero_lead',
		array(
			'default'           => '',
			'sanitize_callback' => 'sanitize_text_field',
		)
	);
	$wp_customize->add_control(
		'fellow_hero_lead',
		array(
			'label'       => __( '帯のリード文', 'fellow' ),
			'section'     => 'fellow_front',
			'type'        => 'text',
			'description' => __( '空欄にすると「設定 > 一般」のキャッチフレーズが入ります。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_category_nav_display',
		array(
			'default'           => true,
			'sanitize_callback' => 'fellow_sanitize_checkbox',
		)
	);
	$wp_customize->add_control(
		'fellow_category_nav_display',
		array(
			'label'       => __( 'カテゴリー導線を表示する', 'fellow' ),
			'section'     => 'fellow_front',
			'type'        => 'checkbox',
			'description' => __( '記事の多いカテゴリーを最大8件、上部に並べます。スマホでは横スクロールになります。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_pickup_source',
		array(
			'default'           => 'sticky',
			'sanitize_callback' => 'fellow_sanitize_pickup_source',
		)
	);
	$wp_customize->add_control(
		'fellow_pickup_source',
		array(
			'label'       => __( 'ピックアップ記事に出す記事', 'fellow' ),
			'section'     => 'fellow_front',
			'type'        => 'select',
			'choices'     => array(
				'sticky' => __( '「先頭に固定」した記事', 'fellow' ),
				'recent' => __( '最新の記事', 'fellow' ),
				'none'   => __( '表示しない', 'fellow' ),
			),
			'description' => __( 'ピックアップに出した記事は、下の一覧には重複して出ません。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_pickup_count',
		array(
			'default'           => 3,
			'sanitize_callback' => 'fellow_sanitize_pickup_count',
		)
	);
	$wp_customize->add_control(
		'fellow_pickup_count',
		array(
			'label'   => __( 'ピックアップ記事の件数', 'fellow' ),
			'section' => 'fellow_front',
			'type'    => 'select',
			'choices' => array(
				2 => __( '2件', 'fellow' ),
				3 => __( '3件', 'fellow' ),
				4 => __( '4件', 'fellow' ),
				5 => __( '5件', 'fellow' ),
			),
		)
	);

	// --- SEO -------------------------------------------------------------.
	$wp_customize->add_section(
		'fellow_seo',
		array(
			'title'       => __( 'SEO', 'fellow' ),
			'priority'    => 93,
			'description' => __( 'SEOプラグインを入れている場合、テーマ側のメタタグ出力は自動的に止まります(二重に出るのを避けるため)。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_seo_meta',
		array(
			'default'           => true,
			'sanitize_callback' => 'fellow_sanitize_checkbox',
		)
	);
	$wp_customize->add_control(
		'fellow_seo_meta',
		array(
			'label'       => __( 'メタタグ(description / OGP / Twitter Card)を出力する', 'fellow' ),
			'section'     => 'fellow_seo',
			'type'        => 'checkbox',
			'description' => __( 'SEOプラグインが検出された場合は、この設定にかかわらず出力しません。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_schema',
		array(
			'default'           => true,
			'sanitize_callback' => 'fellow_sanitize_checkbox',
		)
	);
	$wp_customize->add_control(
		'fellow_schema',
		array(
			'label'       => __( '構造化データ(BlogPosting / WebSite)を出力する', 'fellow' ),
			'section'     => 'fellow_seo',
			'type'        => 'checkbox',
			'description' => __( 'レビュースコアの構造化データ(Review)は、この設定とは別に常に出力されます。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_og_image',
		array(
			'default'           => 0,
			'sanitize_callback' => 'absint',
		)
	);
	$wp_customize->add_control(
		new WP_Customize_Media_Control(
			$wp_customize,
			'fellow_og_image',
			array(
				'label'       => __( 'SNSシェア用の既定画像', 'fellow' ),
				'section'     => 'fellow_seo',
				'mime_type'   => 'image',
				'description' => __( 'アイキャッチが無い記事や一覧ページで使われます。1200x630px 程度を推奨。', 'fellow' ),
			)
		)
	);

	$wp_customize->add_setting(
		'fellow_twitter_site',
		array(
			'default'           => '',
			'sanitize_callback' => 'sanitize_text_field',
		)
	);
	$wp_customize->add_control(
		'fellow_twitter_site',
		array(
			'label'       => __( 'X(旧Twitter)のユーザー名', 'fellow' ),
			'section'     => 'fellow_seo',
			'type'        => 'text',
			'description' => __( '@ は付けても付けなくても構いません。シェア時のカードに表示されます。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_noindex_tag',
		array(
			'default'           => false,
			'sanitize_callback' => 'fellow_sanitize_checkbox',
		)
	);
	$wp_customize->add_control(
		'fellow_noindex_tag',
		array(
			'label'       => __( 'タグアーカイブを noindex にする', 'fellow' ),
			'section'     => 'fellow_seo',
			'type'        => 'checkbox',
			'description' => __( 'カテゴリーと内容が重なりやすい場合に有効です。', 'fellow' ),
		)
	);

	$wp_customize->add_setting(
		'fellow_noindex_date_author',
		array(
			'default'           => false,
			'sanitize_callback' => 'fellow_sanitize_checkbox',
		)
	);
	$wp_customize->add_control(
		'fellow_noindex_date_author',
		array(
			'label'   => __( '日付・著者アーカイブを noindex にする', 'fellow' ),
			'section' => 'fellow_seo',
			'type'    => 'checkbox',
		)
	);

	// --- 機能 -----------------------------------------------------------.
	$wp_customize->add_section(
		'fellow_features',
		array(
			'title'    => __( 'fellow 機能設定', 'fellow' ),
			'priority' => 96,
		)
	);

	$wp_customize->add_setting(
		'fellow_show_search',
		array(
			'default'           => true,
			'sanitize_callback' => 'fellow_sanitize_checkbox',
		)
	);
	$wp_customize->add_control(
		'fellow_show_search',
		array(
			'label'   => __( 'ヘッダーに検索ボックスを表示する', 'fellow' ),
			'section' => 'fellow_features',
			'type'    => 'checkbox',
		)
	);

	$wp_customize->add_setting(
		'fellow_sticky_header',
		array(
			'default'           => true,
			'sanitize_callback' => 'fellow_sanitize_checkbox',
		)
	);
	$wp_customize->add_control(
		'fellow_sticky_header',
		array(
			'label'   => __( 'ヘッダーを画面上部に固定する', 'fellow' ),
			'section' => 'fellow_features',
			'type'    => 'checkbox',
		)
	);
}
add_action( 'customize_register', 'fellow_customize_register' );

/**
 * カスタマイザー値をCSS変数の宣言リストとして返す(セレクタは含まない)。
 *
 * 公開画面では :root{} に、ブロックエディタでは body{} に入れる必要があるため、
 * 宣言部分だけを共通化する。
 *
 * @return string 例: '--accent:#C2EEF2;--measure:70ch;'
 */
function fellow_css_custom_properties() {
	$accent  = sanitize_hex_color( get_theme_mod( 'fellow_accent_color', FELLOW_DEFAULT_ACCENT ) );
	$measure = fellow_sanitize_measure( get_theme_mod( 'fellow_measure', 70 ) );

	if ( ! $accent ) {
		$accent = FELLOW_DEFAULT_ACCENT;
	}

	return sprintf( '--accent:%1$s;--measure:%2$dch;', $accent, $measure );
}

/**
 * カスタマイザー値をCSS変数として出力する(公開画面用)。
 *
 * main.css 側は変数参照のみを行う。
 *
 * @return string
 */
function fellow_inline_css() {
	return ':root{' . fellow_css_custom_properties() . '}';
}

/**
 * ヘッダー検索ボックスを表示するか。
 *
 * @return bool
 */
function fellow_show_search() {
	return (bool) get_theme_mod( 'fellow_show_search', true );
}

/**
 * ヘッダーを固定表示するか。
 *
 * @return bool
 */
function fellow_is_sticky_header() {
	return (bool) get_theme_mod( 'fellow_sticky_header', true );
}

/**
 * 設定済みのSNSリンクを返す(空欄は除外)。
 *
 * @return array{label:string,url:string,slug:string}[]
 */
function fellow_sns_links() {
	$defs = array(
		'x'      => array( __( 'X', 'fellow' ), 'fellow_sns_x' ),
		'rss'    => array( __( 'RSS', 'fellow' ), 'fellow_sns_rss' ),
		'feedly' => array( __( 'Feedly', 'fellow' ), 'fellow_sns_feedly' ),
	);

	$links = array();

	foreach ( $defs as $slug => $def ) {
		$url = get_theme_mod( $def[1], '' );

		if ( '' === $url ) {
			continue;
		}

		$links[] = array(
			'label' => $def[0],
			'url'   => $url,
			'slug'  => $slug,
		);
	}

	return $links;
}
