<?php
/**
 * 目次(TOC)。
 *
 * 本文内の目次ボックスとサイドバーの追従目次の2箇所に同じ内容を出す必要があるため、
 * 見出しの解析とID付与はサーバーサイドで一度だけ行い、両方へ供給する。
 * JS無効環境でも目次が機能し、生成による表示のガタつきも起きない。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * 目次を出すのに必要な最小の見出し数。
 */
const FELLOW_TOC_MIN_HEADINGS = 2;

/**
 * 解析済みの見出しリストを保持・取得する。
 *
 * @param int        $post_id 投稿ID。0なら現在の投稿。
 * @param array|null $set     保存する場合の見出しリスト。
 * @return array{level:int,id:string,text:string}[]
 */
function fellow_toc_items( $post_id = 0, $set = null ) {
	static $store = array();

	if ( ! $post_id ) {
		// サイドバーはループの外で描画されるため、単一ページでは
		// クエリ対象のIDを使う方が確実。
		$post_id = is_singular() ? get_queried_object_id() : get_the_ID();
	}

	if ( null !== $set ) {
		$store[ $post_id ] = $set;
	}

	return isset( $store[ $post_id ] ) ? $store[ $post_id ] : array();
}

/**
 * 本文の h2 / h3 にIDを振り、目次データを組み立て、本文内に目次ボックスを挿入する。
 *
 * @param string $content 本文HTML。
 * @return string
 */
function fellow_process_content_headings( $content ) {
	if ( ! is_singular( 'post' ) || ! in_the_loop() || ! is_main_query() ) {
		return $content;
	}

	$items = array();
	$index = 0;

	$content = preg_replace_callback(
		'#<h([23])(\s[^>]*)?>(.*?)</h\1>#is',
		function ( $matches ) use ( &$items, &$index ) {
			$level = (int) $matches[1];
			$attrs = isset( $matches[2] ) ? $matches[2] : '';
			$inner = $matches[3];

			/*
			 * 記事内パーツ(タブ・ステップ等)の見出しは目次に入れない。
			 * タブの名前やステップの番号が章立てとして並ぶと目次が読めなくなる。
			 * fellow-toc-skip を付ければ任意の見出しも除外できる。
			 */
			if ( preg_match( '/\bfellow-(?:tabs__label|steps__title|toc-skip)\b/', $attrs ) ) {
				return $matches[0];
			}

			// 既にIDがあればそれを使う(アンカーリンクを壊さないため)。
			if ( preg_match( '#\sid=["\']([^"\']+)["\']#i', $attrs, $id_match ) ) {
				$id = $id_match[1];
			} else {
				++$index;
				$id     = 'fellow-heading-' . $index;
				$attrs .= ' id="' . esc_attr( $id ) . '"';
			}

			$text = trim( wp_strip_all_tags( $inner ) );

			if ( '' !== $text ) {
				$items[] = array(
					'level' => $level,
					'id'    => $id,
					'text'  => $text,
				);
			}

			return '<h' . $level . $attrs . '>' . $inner . '</h' . $level . '>';
		},
		$content
	);

	if ( count( $items ) < FELLOW_TOC_MIN_HEADINGS ) {
		fellow_toc_items( 0, array() );
		return $content;
	}

	fellow_toc_items( 0, $items );

	$toc = fellow_render_toc( 'inline' );

	if ( '' === $toc ) {
		return $content;
	}

	// 最初の見出しの直前に差し込む(導入文は目次より上に残す)。
	$position = false;

	foreach ( array( '<h2', '<h3' ) as $tag ) {
		$found = strpos( $content, $tag );

		if ( false !== $found && ( false === $position || $found < $position ) ) {
			$position = $found;
		}
	}

	if ( false === $position ) {
		return $toc . $content;
	}

	return substr( $content, 0, $position ) . $toc . substr( $content, $position );
}
// do_shortcode(11) / wpautop(10) の後に処理する。
add_filter( 'the_content', 'fellow_process_content_headings', 12 );

/**
 * 目次のHTMLを組み立てる。
 *
 * @param string $variant 'inline'(本文内) または 'widget'(サイドバー)。
 * @return string 見出しが足りなければ空文字。
 */
function fellow_render_toc( $variant = 'inline' ) {
	$items = fellow_toc_items();

	if ( count( $items ) < FELLOW_TOC_MIN_HEADINGS ) {
		return '';
	}

	$variant = ( 'widget' === $variant ) ? 'widget' : 'inline';
	$base_id = 'fellow-toc-' . $variant;

	// 本文内はモバイルで畳めるようにする。サイドバーは常に開いた状態。
	$expanded = ( 'inline' === $variant ) ? 'false' : 'true';

	$html  = '<nav class="fellow-toc fellow-toc--' . esc_attr( $variant ) . '" id="' . esc_attr( $base_id ) . '"';
	$html .= ' aria-label="' . esc_attr__( '目次', 'fellow' ) . '">';

	if ( 'inline' === $variant ) {
		$html .= '<button type="button" class="fellow-toc__toggle" aria-expanded="' . esc_attr( $expanded ) . '"';
		$html .= ' aria-controls="' . esc_attr( $base_id . '-body' ) . '">';
		$html .= esc_html__( '目次', 'fellow' );
		$html .= '</button>';
	}

	$html .= '<div class="fellow-toc__body" id="' . esc_attr( $base_id . '-body' ) . '">';
	$html .= '<ol class="fellow-toc__list">';

	$sub_open = false;
	$li_open  = false;

	foreach ( $items as $item ) {
		$link = '<a href="#' . esc_attr( $item['id'] ) . '">' . esc_html( $item['text'] ) . '</a>';

		if ( 2 === $item['level'] ) {
			if ( $sub_open ) {
				$html    .= '</ol>';
				$sub_open = false;
			}
			if ( $li_open ) {
				$html .= '</li>';
			}
			$html   .= '<li>' . $link;
			$li_open = true;
		} else {
			// h2 より先に h3 が来る記事もあるので、親の li が無ければ作る。
			if ( ! $li_open ) {
				$html    .= '<li>';
				$li_open  = true;
			}
			if ( ! $sub_open ) {
				$html    .= '<ol class="fellow-toc__sub">';
				$sub_open = true;
			}
			$html .= '<li>' . $link . '</li>';
		}
	}

	if ( $sub_open ) {
		$html .= '</ol>';
	}
	if ( $li_open ) {
		$html .= '</li>';
	}

	$html .= '</ol></div></nav>';

	return $html;
}
