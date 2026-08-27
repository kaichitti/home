<?php
/**
 * 構造化データ(JSON-LD)。
 *
 * パンくずの BreadcrumbList は template-tags.php 側が出す。
 * ここでは記事の BlogPosting と、レビュースコアがある記事の Review、
 * トップの WebSite を扱う。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * 構造化データを出力すべきか。
 *
 * SEOプラグインも Article 系のスキーマを出すため、検出時は重複を避ける。
 * ただし Review はレビュースコアという本テーマ固有のデータが元なので、
 * プラグインの有無にかかわらず出す。
 *
 * @return bool
 */
function fellow_schema_enabled() {
	if ( ! get_theme_mod( 'fellow_schema', true ) ) {
		return false;
	}

	return '' === fellow_detected_seo_plugin();
}

/**
 * 現在の投稿の著者情報を返す。
 *
 * wp_head はループの外で発火するため、get_the_author() が使う $authordata が
 * まだ設定されておらず空文字になる。投稿IDから直接引く必要がある。
 *
 * @return array{name:string,url:string}
 */
function fellow_schema_author() {
	$post_id   = get_queried_object_id();
	$author_id = (int) get_post_field( 'post_author', $post_id );

	return array(
		'name' => (string) get_the_author_meta( 'display_name', $author_id ),
		'url'  => $author_id ? (string) get_author_posts_url( $author_id ) : '',
	);
}

/**
 * 発行元(publisher)のデータを組み立てる。
 *
 * @return array
 */
function fellow_schema_publisher() {
	$publisher = array(
		'@type' => 'Organization',
		'name'  => get_bloginfo( 'name', 'display' ),
	);

	$logo_id = (int) get_theme_mod( 'custom_logo', 0 );

	if ( $logo_id ) {
		$logo = wp_get_attachment_image_src( $logo_id, 'full' );

		if ( $logo ) {
			$publisher['logo'] = array(
				'@type'  => 'ImageObject',
				'url'    => $logo[0],
				'width'  => (int) $logo[1],
				'height' => (int) $logo[2],
			);
		}
	}

	return $publisher;
}

/**
 * 記事の BlogPosting を組み立てる。
 *
 * @return array
 */
function fellow_schema_blogposting() {
	$author = fellow_schema_author();

	$schema = array(
		'@context'         => 'https://schema.org',
		'@type'            => 'BlogPosting',
		'mainEntityOfPage' => array(
			'@type' => 'WebPage',
			'@id'   => get_permalink(),
		),
		'headline'         => wp_strip_all_tags( get_the_title() ),
		'datePublished'    => get_the_date( DATE_W3C ),
		'dateModified'     => get_the_modified_date( DATE_W3C ),
		'author'           => array(
			'@type' => 'Person',
			'name'  => $author['name'],
			'url'   => $author['url'],
		),
		'publisher'        => fellow_schema_publisher(),
	);

	$description = fellow_get_excerpt( 120 );

	if ( '' !== $description ) {
		$schema['description'] = $description;
	}

	$image = fellow_og_image_url();

	if ( '' !== $image ) {
		$schema['image'] = $image;
	}

	return $schema;
}

/**
 * レビュー記事の Review を組み立てる。
 *
 * スコアが未入力なら null を返す。
 *
 * 注意: Google のレビューのリッチリザルトは itemReviewed が
 * 対応済みのタイプ(Product 等)であることを求める。ここでは Product として
 * 出力するが、実際にリッチリザルトが出るかは Google 側の判断になるため、
 * 公開前にリッチリザルトテストでの確認を推奨する。
 *
 * @return array|null
 */
function fellow_schema_review() {
	$score = fellow_get_review_score();

	if ( null === $score ) {
		return null;
	}

	$item_name = trim( (string) get_post_meta( get_the_ID(), '_fellow_review_item', true ) );

	if ( '' === $item_name ) {
		$item_name = wp_strip_all_tags( get_the_title() );
	}

	$author = fellow_schema_author();

	$item = array(
		'@type' => 'Product',
		'name'  => $item_name,
	);

	$image = fellow_og_image_url();

	if ( '' !== $image ) {
		$item['image'] = $image;
	}

	return array(
		'@context'     => 'https://schema.org',
		'@type'        => 'Review',
		'itemReviewed' => $item,
		'reviewRating' => array(
			'@type'       => 'Rating',
			'ratingValue' => (float) $score,
			'bestRating'  => 10,
			'worstRating' => 0,
		),
		'author'       => array(
			'@type' => 'Person',
			'name'  => $author['name'],
		),
		'datePublished' => get_the_date( DATE_W3C ),
		'url'           => get_permalink(),
	);
}

/**
 * トップページの WebSite を組み立てる。
 *
 * サイト内検索をサイトリンク検索ボックスの候補にする。
 *
 * @return array
 */
function fellow_schema_website() {
	return array(
		'@context'        => 'https://schema.org',
		'@type'           => 'WebSite',
		'name'            => get_bloginfo( 'name', 'display' ),
		'url'             => home_url( '/' ),
		'potentialAction' => array(
			'@type'       => 'SearchAction',
			'target'      => array(
				'@type'       => 'EntryPoint',
				'urlTemplate' => home_url( '/?s={search_term_string}' ),
			),
			'query-input' => 'required name=search_term_string',
		),
	);
}

/**
 * 構造化データを head に出力する。
 */
function fellow_print_schema() {
	$blocks = array();

	if ( is_singular( 'post' ) ) {
		// Review は本テーマ固有のデータが元なので、プラグイン検出時も出す。
		$review = fellow_schema_review();

		if ( $review ) {
			$blocks[] = $review;
		}

		if ( fellow_schema_enabled() ) {
			$blocks[] = fellow_schema_blogposting();
		}
	} elseif ( ( is_home() || is_front_page() ) && fellow_schema_enabled() ) {
		$blocks[] = fellow_schema_website();
	}

	foreach ( $blocks as $block ) {
		printf(
			'<script type="application/ld+json">%s</script>' . "\n",
			wp_json_encode( $block, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE )
		);
	}
}
add_action( 'wp_head', 'fellow_print_schema', 5 );
