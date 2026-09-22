<?php
/**
 * コアブロックに追加するスタイルバリエーション。
 *
 * パターンが「構造ごと差し込む」ものなのに対し、こちらは既にあるブロックの
 * 見た目だけを切り替える。ブロックのサイドバーから選べる。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * ブロックスタイルを登録する。
 */
function fellow_register_block_styles() {
	if ( ! function_exists( 'register_block_style' ) ) {
		return;
	}

	$styles = array(
		'core/quote' => array(
			array( 'fellow-quote-plain', __( '線だけ', 'fellow' ) ),
		),
		'core/list'  => array(
			array( 'fellow-list-check', __( 'チェック', 'fellow' ) ),
			array( 'fellow-list-note', __( '注意', 'fellow' ) ),
		),
		'core/image' => array(
			array( 'fellow-image-bordered', __( '枠線つき', 'fellow' ) ),
		),
		'core/table' => array(
			array( 'fellow-table-compact', __( 'コンパクト', 'fellow' ) ),
		),
		'core/separator' => array(
			array( 'fellow-separator-dots', __( 'ドット', 'fellow' ) ),
		),
	);

	foreach ( $styles as $block => $variations ) {
		foreach ( $variations as $variation ) {
			register_block_style(
				$block,
				array(
					'name'  => $variation[0],
					'label' => $variation[1],
				)
			);
		}
	}
}
add_action( 'init', 'fellow_register_block_styles' );
