<?php
/**
 * ブログトップ最上部のパーツ(紹介の帯 / ピックアップ記事)。
 *
 * どちらも「内容が無ければ何も出さない」方針。設定していない購入者の画面に
 * 空の枠が残らないようにする。アイキャッチを設定しない運用でも成立するよう、
 * 画像には依存せずアクセントカラーと文字で見せる。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * 帯に出す見出しとリード文を解決する。
 *
 * カスタマイザーが空なら、サイト名と「設定 > 一般」のキャッチフレーズで補う。
 *
 * @return array{title:string,lead:string}
 */
function fellow_hero_text() {
	$title = trim( (string) get_theme_mod( 'fellow_hero_title', '' ) );
	$lead  = trim( (string) get_theme_mod( 'fellow_hero_lead', '' ) );

	if ( '' === $title ) {
		$title = get_bloginfo( 'name', 'display' );
	}

	if ( '' === $lead ) {
		$lead = get_bloginfo( 'description', 'display' );
	}

	return array(
		'title' => (string) $title,
		'lead'  => (string) $lead,
	);
}

/**
 * 帯を表示すべきか。
 *
 * ブログトップの1ページ目のみ。見出しもリード文も空なら出さない。
 *
 * @return bool
 */
function fellow_show_hero() {
	if ( ! is_home() || is_paged() ) {
		return false;
	}

	if ( ! get_theme_mod( 'fellow_hero_display', true ) ) {
		return false;
	}

	$text = fellow_hero_text();

	return ( '' !== $text['title'] || '' !== $text['lead'] );
}

/**
 * ピックアップに出す投稿IDを返す。
 *
 * 「先頭に固定」を選んだ場合、WordPress は固定した投稿をトップの1ページ目の
 * 先頭へ回すため、そのまま一覧にも出ると重複する。home.php 側でこのIDを
 * 使って一覧から除外する。
 *
 * @return int[]
 */
function fellow_pickup_ids() {
	static $ids = null;

	if ( null !== $ids ) {
		return $ids;
	}

	$ids = array();

	if ( ! is_home() || is_paged() ) {
		return $ids;
	}

	$source = get_theme_mod( 'fellow_pickup_source', 'sticky' );
	$count  = (int) get_theme_mod( 'fellow_pickup_count', 3 );
	$count  = ( $count >= 2 && $count <= 5 ) ? $count : 3;

	if ( 'none' === $source ) {
		return $ids;
	}

	if ( 'sticky' === $source ) {
		$sticky = get_option( 'sticky_posts' );

		if ( ! is_array( $sticky ) || ! $sticky ) {
			return $ids;
		}

		$query = new WP_Query(
			array(
				'post_type'           => 'post',
				'post__in'            => $sticky,
				'posts_per_page'      => $count,
				'orderby'             => 'date',
				'order'               => 'DESC',
				'ignore_sticky_posts' => true,
				'no_found_rows'       => true,
				'fields'              => 'ids',
			)
		);
	} else {
		$query = new WP_Query(
			array(
				'post_type'           => 'post',
				'posts_per_page'      => $count,
				'ignore_sticky_posts' => true,
				'no_found_rows'       => true,
				'fields'              => 'ids',
			)
		);
	}

	$ids = array_map( 'intval', $query->posts );

	return $ids;
}
