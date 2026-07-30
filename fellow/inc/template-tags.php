<?php
/**
 * テンプレートタグ:パンくず、アーカイブタイトル、関連記事、フッターの各リスト。
 *
 * すべてプラグイン非依存の自前実装。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * テーマオプション(外観 > fellow 設定)の値を取得する。
 *
 * 設定ページ自体は管理画面でのみ読み込まれるため、
 * 取得ヘルパーはフロントでも使えるようここに置く。
 *
 * @param string $key オプションキー。
 * @return mixed
 */
function fellow_get_option( $key ) {
	$defaults = array(
		'enable_review_score' => 1,
		'show_footer_credit'  => 1,
	);

	$options = (array) get_option( 'fellow_options', array() );
	$options = wp_parse_args( $options, $defaults );

	return isset( $options[ $key ] ) ? $options[ $key ] : null;
}

/**
 * パンくずリストを出力する(JSON-LD の BreadcrumbList 付き)。
 */
function fellow_breadcrumb() {
	if ( is_front_page() ) {
		return;
	}

	$items   = array();
	$items[] = array(
		'label' => __( 'ホーム', 'fellow' ),
		'url'   => home_url( '/' ),
	);

	if ( is_home() ) {
		$page_for_posts = (int) get_option( 'page_for_posts' );
		$items[]        = array(
			'label' => $page_for_posts ? get_the_title( $page_for_posts ) : __( 'ブログ', 'fellow' ),
			'url'   => '',
		);
	} elseif ( is_singular( 'post' ) ) {
		$categories = get_the_category();

		if ( $categories ) {
			$category  = $categories[0];
			$ancestors = array_reverse( get_ancestors( $category->term_id, 'category' ) );

			foreach ( $ancestors as $ancestor_id ) {
				$ancestor = get_term( $ancestor_id, 'category' );

				if ( $ancestor && ! is_wp_error( $ancestor ) ) {
					$items[] = array(
						'label' => $ancestor->name,
						'url'   => get_category_link( $ancestor ),
					);
				}
			}

			$items[] = array(
				'label' => $category->name,
				'url'   => get_category_link( $category ),
			);
		}

		$items[] = array(
			'label' => get_the_title(),
			'url'   => '',
		);
	} elseif ( is_page() ) {
		$ancestors = array_reverse( get_post_ancestors( get_the_ID() ) );

		foreach ( $ancestors as $ancestor_id ) {
			$items[] = array(
				'label' => get_the_title( $ancestor_id ),
				'url'   => get_permalink( $ancestor_id ),
			);
		}

		$items[] = array(
			'label' => get_the_title(),
			'url'   => '',
		);
	} elseif ( is_category() || is_tag() ) {
		$term = get_queried_object();

		if ( $term instanceof WP_Term ) {
			$ancestors = array_reverse( get_ancestors( $term->term_id, $term->taxonomy ) );

			foreach ( $ancestors as $ancestor_id ) {
				$ancestor = get_term( $ancestor_id, $term->taxonomy );

				if ( $ancestor && ! is_wp_error( $ancestor ) ) {
					$items[] = array(
						'label' => $ancestor->name,
						'url'   => get_term_link( $ancestor ),
					);
				}
			}

			$items[] = array(
				'label' => $term->name,
				'url'   => '',
			);
		}
	} elseif ( is_year() ) {
		$items[] = array(
			/* translators: %s: 年(4桁)。 */
			'label' => sprintf( __( '%s年', 'fellow' ), get_the_date( 'Y' ) ),
			'url'   => '',
		);
	} elseif ( is_search() ) {
		$items[] = array(
			/* translators: %s: 検索キーワード。 */
			'label' => sprintf( __( '「%s」の検索結果', 'fellow' ), get_search_query() ),
			'url'   => '',
		);
	} elseif ( is_404() ) {
		$items[] = array(
			'label' => __( 'ページが見つかりません', 'fellow' ),
			'url'   => '',
		);
	} elseif ( is_archive() ) {
		$items[] = array(
			'label' => get_the_archive_title(),
			'url'   => '',
		);
	} else {
		return;
	}

	// --- HTML 出力 -------------------------------------------------------.
	echo '<nav class="breadcrumb" aria-label="' . esc_attr__( '現在位置', 'fellow' ) . '"><ol class="breadcrumb__list">';

	$last_index = count( $items ) - 1;

	foreach ( $items as $index => $item ) {
		echo '<li class="breadcrumb__item">';

		if ( $item['url'] && $index !== $last_index ) {
			echo '<a href="' . esc_url( $item['url'] ) . '">' . esc_html( $item['label'] ) . '</a>';
		} else {
			echo '<span aria-current="page">' . esc_html( $item['label'] ) . '</span>';
		}

		echo '</li>';
	}

	echo '</ol></nav>';

	// --- JSON-LD(BreadcrumbList) ---------------------------------------.
	$list_elements = array();

	foreach ( $items as $index => $item ) {
		$element = array(
			'@type'    => 'ListItem',
			'position' => $index + 1,
			'name'     => wp_strip_all_tags( $item['label'] ),
		);

		if ( $item['url'] ) {
			$element['item'] = $item['url'];
		}

		$list_elements[] = $element;
	}

	$json_ld = array(
		'@context'        => 'https://schema.org',
		'@type'           => 'BreadcrumbList',
		'itemListElement' => $list_elements,
	);

	echo '<script type="application/ld+json">' . wp_json_encode( $json_ld, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ) . '</script>';
}

/**
 * アーカイブタイトルを日本語向けに整形する(「カテゴリー:」等の接頭辞を除去)。
 *
 * @param string $title 元のタイトル。
 * @return string
 */
function fellow_archive_title( $title ) {
	if ( is_category() ) {
		return single_cat_title( '', false );
	}

	if ( is_tag() ) {
		/* translators: %s: タグ名。 */
		return sprintf( __( '#%s', 'fellow' ), single_tag_title( '', false ) );
	}

	if ( is_year() ) {
		/* translators: %s: 年(4桁)。 */
		return sprintf( __( '%s年の記事', 'fellow' ), get_the_date( 'Y' ) );
	}

	if ( is_month() ) {
		/* translators: %s: 年月。 */
		return sprintf( __( '%sの記事', 'fellow' ), get_the_date( 'Y年n月' ) );
	}

	if ( is_author() ) {
		/* translators: %s: 著者名。 */
		return sprintf( __( '%s の記事', 'fellow' ), get_the_author() );
	}

	return $title;
}
add_filter( 'get_the_archive_title', 'fellow_archive_title' );

/**
 * 投稿日(+更新日)を time 要素で出力する。
 */
function fellow_entry_date() {
	printf(
		'<time class="entry-date" datetime="%1$s">%2$s</time>',
		esc_attr( get_the_date( DATE_W3C ) ),
		esc_html( get_the_date() )
	);

	if ( get_the_modified_time( 'U' ) > get_the_time( 'U' ) + DAY_IN_SECONDS ) {
		printf(
			'<time class="entry-date entry-date--updated" datetime="%1$s">%2$s</time>',
			esc_attr( get_the_modified_date( DATE_W3C ) ),
			/* translators: %s: 更新日。 */
			esc_html( sprintf( __( '%s 更新', 'fellow' ), get_the_modified_date() ) )
		);
	}
}

/**
 * 関連記事のクエリを返す。
 *
 * DB負荷を抑えるため「同一カテゴリー内の直近日付順」で取得する
 * (orderby=rand は共用サーバーで負荷が上がりやすいため使わない)。
 *
 * @param int $count 取得件数。
 * @return WP_Query
 */
function fellow_related_posts_query( $count = 3 ) {
	$args = array(
		'post_type'           => 'post',
		'posts_per_page'      => $count,
		'post__not_in'        => array( get_the_ID() ),
		'no_found_rows'       => true,
		'ignore_sticky_posts' => true,
	);

	$categories = get_the_category();

	if ( $categories ) {
		$args['cat'] = $categories[0]->term_id;
	}

	return new WP_Query( $args );
}

/**
 * フッター用カテゴリーリストを出力する。
 *
 * @param int  $number       表示件数。
 * @param bool $hierarchical 子カテゴリーを入れ子で表示するか。
 *                           404ページのように横並びで見せる場所では false にする。
 */
function fellow_footer_categories( $number = 6, $hierarchical = true ) {
	$list = wp_list_categories(
		array(
			'title_li'     => '',
			'echo'         => false,
			'number'       => $number,
			'orderby'      => 'count',
			'order'        => 'DESC',
			'hierarchical' => (bool) $hierarchical,
		)
	);

	if ( ! $list ) {
		return;
	}

	echo '<ul class="footer-list">' . $list . '</ul>'; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- wp_list_categories() はエスケープ済みHTMLを返す。
}

/**
 * フッター用の年別アーカイブリストを出力する。
 *
 * @param int $limit 表示件数。
 */
function fellow_footer_archives( $limit = 5 ) {
	$list = wp_get_archives(
		array(
			'type'  => 'yearly',
			'limit' => $limit,
			'echo'  => false,
		)
	);

	if ( ! $list ) {
		return;
	}

	echo '<ul class="footer-list">' . $list . '</ul>'; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- wp_get_archives() はエスケープ済みHTMLを返す。
}

/**
 * 抜粋を「文字数」で切り詰めて返す。
 *
 * wp_trim_words() は空白で単語を区切るため、空白をほとんど使わない日本語では
 * ほぼ切り詰められず本文全体が出てしまう。文字数ベースで判定する。
 * 手動抜粋が未設定のときは本文の最初の段落だけを使う(見出しの文字列が
 * 抜粋に混ざって読みづらくなるのを避けるため)。
 *
 * @param int $length 最大文字数。
 * @return string
 */
function fellow_get_excerpt( $length = 120 ) {
	$post = get_post();

	if ( ! $post ) {
		return '';
	}

	if ( '' !== trim( (string) $post->post_excerpt ) ) {
		$text = $post->post_excerpt;
	} else {
		$content = strip_shortcodes( $post->post_content );

		// 最初の段落だけを採用する。段落が取れなければ全体を使う。
		if ( preg_match( '#<p[^>]*>(.*?)</p>#is', $content, $matches ) ) {
			$text = $matches[1];
		} else {
			$text = $content;
		}
	}

	$text = wp_strip_all_tags( $text, true );
	$text = trim( preg_replace( '/\s+/u', ' ', $text ) );

	if ( '' === $text ) {
		return '';
	}

	if ( function_exists( 'mb_strlen' ) ) {
		if ( mb_strlen( $text ) > $length ) {
			$text = rtrim( mb_substr( $text, 0, $length ) ) . '…';
		}
	} elseif ( strlen( $text ) > $length * 3 ) {
		$text = rtrim( substr( $text, 0, $length * 3 ) ) . '…';
	}

	return $text;
}

/**
 * 記事のタグを出力する。タグ未設定なら何も出さない。
 */
function fellow_entry_tags() {
	$tags = get_the_tags();

	if ( ! $tags || is_wp_error( $tags ) ) {
		return;
	}
	?>
	<div class="entry-tags">
		<span class="entry-tags__label"><?php esc_html_e( 'タグ', 'fellow' ); ?></span>
		<ul class="entry-tags__list">
			<?php foreach ( $tags as $tag ) : ?>
				<li>
					<a class="entry-tags__link" href="<?php echo esc_url( get_tag_link( $tag ) ); ?>" rel="tag">
						<?php echo esc_html( $tag->name ); ?>
					</a>
				</li>
			<?php endforeach; ?>
		</ul>
	</div>
	<?php
}

/**
 * シェアリンク(X / はてなブックマーク)を出力する。
 */
function fellow_share_links() {
	$url   = get_permalink();
	$title = get_the_title();

	$x_url = add_query_arg(
		array(
			'url'  => rawurlencode( $url ),
			'text' => rawurlencode( $title ),
		),
		'https://x.com/intent/post'
	);

	$hatena_url = 'https://b.hatena.ne.jp/entry/' . preg_replace( '#^https?://#', '', $url );
	?>
	<div class="share">
		<span class="share__label"><?php esc_html_e( 'シェア', 'fellow' ); ?></span>
		<ul class="share__list">
			<li>
				<a class="share__link share__link--x" href="<?php echo esc_url( $x_url ); ?>" target="_blank" rel="noopener noreferrer">
					<?php esc_html_e( 'Xでポスト', 'fellow' ); ?>
				</a>
			</li>
			<li>
				<a class="share__link share__link--hatena" href="<?php echo esc_url( $hatena_url ); ?>" target="_blank" rel="noopener noreferrer">
					<?php esc_html_e( 'はてなブックマーク', 'fellow' ); ?>
				</a>
			</li>
			<li>
				<button type="button" class="share__link share__link--copy" data-copy-url="<?php echo esc_url( $url ); ?>">
					<?php esc_html_e( 'URLをコピー', 'fellow' ); ?>
				</button>
			</li>
		</ul>
	</div>
	<?php
}
