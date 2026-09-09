<?php
/**
 * ハンバーガーメニュー用カスタムWalker。
 *
 * 子メニューを持つ項目に開閉ボタンを追加し、
 * モバイルでもキーボード/スクリーンリーダーで操作できるようにする。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * グローバルナビ用 Walker。
 */
class Fellow_Walker_Nav extends Walker_Nav_Menu {

	/**
	 * サブメニューの開始タグ。
	 *
	 * @param string   $output HTML出力(参照渡し)。
	 * @param int      $depth  階層の深さ。
	 * @param stdClass $args   wp_nav_menu() の引数。
	 */
	public function start_lvl( &$output, $depth = 0, $args = null ) {
		$indent  = str_repeat( "\t", $depth );
		$output .= "\n{$indent}<ul class=\"sub-menu global-nav__sub\">\n";
	}

	/**
	 * メニュー項目の開始タグ。
	 *
	 * @param string   $output            HTML出力(参照渡し)。
	 * @param WP_Post  $data_object       メニュー項目。
	 * @param int      $depth             階層の深さ。
	 * @param stdClass $args              wp_nav_menu() の引数。
	 * @param int      $current_object_id 現在の項目ID。
	 */
	public function start_el( &$output, $data_object, $depth = 0, $args = null, $current_object_id = 0 ) {
		$item    = $data_object;
		$classes = empty( $item->classes ) ? array() : (array) $item->classes;
		$classes = array_filter( array_map( 'sanitize_html_class', $classes ) );

		$classes[] = 'global-nav__item';

		$has_children = in_array( 'menu-item-has-children', $classes, true );

		$output .= '<li class="' . esc_attr( implode( ' ', $classes ) ) . '">';

		$atts = array(
			'href'  => ! empty( $item->url ) ? $item->url : '',
			'class' => 'global-nav__link',
		);

		if ( in_array( 'current-menu-item', $classes, true ) ) {
			$atts['aria-current'] = 'page';
		}

		$attributes = '';

		foreach ( $atts as $attr => $value ) {
			if ( '' === $value ) {
				continue;
			}

			$value       = ( 'href' === $attr ) ? esc_url( $value ) : esc_attr( $value );
			$attributes .= ' ' . $attr . '="' . $value . '"';
		}

		$title = apply_filters( 'the_title', $item->title, $item->ID );

		$output .= '<a' . $attributes . '>' . esc_html( $title ) . '</a>';

		if ( $has_children ) {
			$output .= sprintf(
				'<button type="button" class="global-nav__toggle" aria-expanded="false"><span class="screen-reader-text">%s</span></button>',
				/* translators: %s: 親メニュー名。 */
				esc_html( sprintf( __( '%s のサブメニューを開閉', 'fellow' ), $title ) )
			);
		}
	}
}
