<?php
/**
 * SEO用のメタ情報(description / OGP / Twitter Card / noindex)。
 *
 * SEOプラグインを入れている環境では同じタグが二重に出てしまうため、
 * 既知のプラグインを検出したらテーマ側は何も出さない。
 * canonical は WordPress コアの rel_canonical が出すのでここでは触らない。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * 既知のSEOプラグインが有効かどうか。
 *
 * 判定は各プラグインが定義する定数・クラスで行う。
 * 新しいプラグインには追従できないため、カスタマイザーの
 * 手動スイッチを最終的な逃げ道として用意してある。
 *
 * @return string 検出したプラグイン名。無ければ空文字。
 */
function fellow_detected_seo_plugin() {
	$constants = array(
		'WPSEO_VERSION'             => 'Yoast SEO',
		'RANK_MATH_VERSION'         => 'Rank Math SEO',
		'AIOSEO_VERSION'            => 'All in One SEO',
		'AIOSEOP_VERSION'           => 'All in One SEO Pack',
		'THE_SEO_FRAMEWORK_VERSION' => 'The SEO Framework',
		'SEOPRESS_VERSION'          => 'SEOPress',
		'SLIM_SEO_VER'              => 'Slim SEO',
		'SSP_VERSION'               => 'SEO SIMPLE PACK',
	);

	foreach ( $constants as $constant => $name ) {
		if ( defined( $constant ) ) {
			return $name;
		}
	}

	$classes = array(
		'SEO_SIMPLE_PACK' => 'SEO SIMPLE PACK',
		'All_in_One_SEO_Pack' => 'All in One SEO Pack',
	);

	foreach ( $classes as $class => $name ) {
		if ( class_exists( $class ) ) {
			return $name;
		}
	}

	return '';
}

/**
 * テーマ側でメタ情報を出力すべきか。
 *
 * @return bool
 */
function fellow_seo_meta_enabled() {
	if ( ! get_theme_mod( 'fellow_seo_meta', true ) ) {
		return false;
	}

	return '' === fellow_detected_seo_plugin();
}

/**
 * 画面ごとの説明文を組み立てる。
 *
 * @return string
 */
function fellow_meta_description() {
	$description = '';

	if ( is_singular() ) {
		$post = get_post();

		if ( $post ) {
			$description = has_excerpt( $post ) ? $post->post_excerpt : fellow_get_excerpt( 120 );
		}
	} elseif ( is_category() || is_tag() || is_tax() ) {
		$description = term_description();
	} elseif ( is_author() ) {
		$description = get_the_author_meta( 'description', (int) get_query_var( 'author' ) );
	} elseif ( is_home() || is_front_page() ) {
		$description = get_bloginfo( 'description', 'display' );
	}

	$description = trim( wp_strip_all_tags( (string) $description, true ) );
	$description = preg_replace( '/\s+/u', ' ', $description );

	if ( '' === $description ) {
		$description = get_bloginfo( 'description', 'display' );
	}

	if ( function_exists( 'mb_strlen' ) && mb_strlen( $description ) > 120 ) {
		$description = rtrim( mb_substr( $description, 0, 120 ) ) . '…';
	}

	return (string) $description;
}

/**
 * OGP画像のURLを返す。
 *
 * アイキャッチを設定しない運用でも空にならないよう、
 * カスタマイザーの既定画像へフォールバックする。
 *
 * @return string
 */
function fellow_og_image_url() {
	if ( is_singular() && has_post_thumbnail() ) {
		$url = get_the_post_thumbnail_url( get_the_ID(), 'full' );

		if ( $url ) {
			return (string) $url;
		}
	}

	$fallback = (int) get_theme_mod( 'fellow_og_image', 0 );

	if ( $fallback ) {
		$url = wp_get_attachment_image_url( $fallback, 'full' );

		if ( $url ) {
			return (string) $url;
		}
	}

	return '';
}

/**
 * 現在の画面を noindex にすべきか。
 *
 * 検索結果と404は常に noindex(重複コンテンツになりやすいため)。
 * タグ・日付・著者アーカイブはカスタマイザーで選べるようにする。
 *
 * @return bool
 */
function fellow_should_noindex() {
	if ( is_search() || is_404() ) {
		return true;
	}

	if ( is_singular() && get_post_meta( get_the_ID(), '_fellow_noindex', true ) ) {
		return true;
	}

	if ( is_tag() && get_theme_mod( 'fellow_noindex_tag', false ) ) {
		return true;
	}

	if ( ( is_date() || is_author() ) && get_theme_mod( 'fellow_noindex_date_author', false ) ) {
		return true;
	}

	return false;
}

/**
 * 現在の画面の正規URLを返す(OGP用)。
 *
 * @return string
 */
function fellow_current_url() {
	if ( is_singular() ) {
		return (string) get_permalink();
	}

	if ( is_category() || is_tag() || is_tax() ) {
		$link = get_term_link( get_queried_object() );

		return is_wp_error( $link ) ? '' : (string) $link;
	}

	if ( is_home() || is_front_page() ) {
		return (string) home_url( '/' );
	}

	return '';
}

/**
 * head にメタ情報を出力する。
 */
function fellow_print_head_meta() {
	// noindex はプラグインの有無にかかわらずテーマの設定を尊重する。
	if ( fellow_should_noindex() ) {
		echo '<meta name="robots" content="noindex,follow">' . "\n";
	}

	if ( ! fellow_seo_meta_enabled() ) {
		return;
	}

	$description = fellow_meta_description();
	$image       = fellow_og_image_url();
	$url         = fellow_current_url();
	$title       = wp_get_document_title();

	if ( '' !== $description ) {
		printf( '<meta name="description" content="%s">' . "\n", esc_attr( $description ) );
	}

	printf( '<meta property="og:title" content="%s">' . "\n", esc_attr( $title ) );
	printf( '<meta property="og:type" content="%s">' . "\n", is_singular() ? 'article' : 'website' );
	printf( '<meta property="og:site_name" content="%s">' . "\n", esc_attr( get_bloginfo( 'name', 'display' ) ) );
	printf( '<meta property="og:locale" content="%s">' . "\n", esc_attr( get_locale() ) );

	if ( '' !== $url ) {
		printf( '<meta property="og:url" content="%s">' . "\n", esc_url( $url ) );
	}

	if ( '' !== $description ) {
		printf( '<meta property="og:description" content="%s">' . "\n", esc_attr( $description ) );
	}

	if ( '' !== $image ) {
		printf( '<meta property="og:image" content="%s">' . "\n", esc_url( $image ) );
		echo '<meta name="twitter:card" content="summary_large_image">' . "\n";
	} else {
		echo '<meta name="twitter:card" content="summary">' . "\n";
	}

	$twitter = get_theme_mod( 'fellow_twitter_site', '' );

	if ( $twitter ) {
		printf( '<meta name="twitter:site" content="%s">' . "\n", esc_attr( '@' . ltrim( $twitter, '@' ) ) );
	}
}
add_action( 'wp_head', 'fellow_print_head_meta', 1 );
