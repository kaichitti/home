<?php
/**
 * 記事一覧の1件分(リスト型)。
 *
 * home.php / archive.php / search.php / index.php / single.php(関連記事)から
 * 共通で呼ぶ。アイキャッチ未設定の記事が多いブログでも間延びしないよう、
 * 画像がある記事だけ小さなサムネイルを出し、無ければ文字だけで組む。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

$fellow_item_score      = fellow_get_review_score();
$fellow_item_categories = get_the_category();
$fellow_item_excerpt    = fellow_get_excerpt( 100 );
$fellow_item_has_thumb  = has_post_thumbnail();

/*
 * カード型かどうかは呼び出し側が渡す(get_template_part の第3引数)。
 * 関連記事は設定に関係なく常にリスト型なので、ここで設定を読むと
 * 画像の sizes が実際の表示とずれる。
 */
$fellow_is_card = isset( $args['layout'] ) && 'card' === $args['layout'];
?>
<article id="post-<?php the_ID(); ?>" <?php post_class( 'post-item' . ( $fellow_item_has_thumb ? ' post-item--has-thumb' : '' ) ); ?>>
	<a class="post-item__link" href="<?php the_permalink(); ?>">
		<div class="post-item__body">
			<?php if ( $fellow_item_categories || null !== $fellow_item_score ) : ?>
				<div class="post-item__labels">
					<?php if ( $fellow_item_categories ) : ?>
						<span class="post-item__category"><?php echo esc_html( $fellow_item_categories[0]->name ); ?></span>
					<?php endif; ?>

					<?php if ( null !== $fellow_item_score ) : ?>
						<span class="post-item__score">
							<?php echo esc_html( number_format_i18n( $fellow_item_score, 1 ) ); ?>
						</span>
					<?php endif; ?>
				</div>
			<?php endif; ?>

			<h3 class="post-item__title"><?php the_title(); ?></h3>

			<?php if ( '' !== $fellow_item_excerpt ) : ?>
				<p class="post-item__excerpt"><?php echo esc_html( $fellow_item_excerpt ); ?></p>
			<?php endif; ?>

			<div class="post-item__meta">
				<?php fellow_entry_date(); ?>
			</div>
		</div>

		<?php if ( $fellow_item_has_thumb ) : ?>
			<?php
			/*
			 * サムネイルは本文の「後ろ」に置く。
			 * 画像が無い記事の方が多い前提なので、左に置くと画像のある行だけ
			 * 本文が右へずれて左端が揃わない。右に寄せておけば列が乱れない。
			 * 読み上げ順もタイトルが先に来るので都合がよい。
			 *
			 * リスト型の表示は最大160px。コアの medium(既定300px)ならどのサイトでも
			 * 生成済みで、無駄な転送も抑えられる。
			 * カード型は横幅いっぱい(16:9)で出すので、16:9 の小さい方を使う。
			 */
			?>
			<div class="post-item__thumb">
				<?php
				/*
				 * loading は指定しない。
				 * WordPress 5.9 以降は wp_get_loading_optimization_attributes() が
				 * 「最初の画像には lazy を付けず fetchpriority=high を付ける」判断を
				 * 自動で行う。ここで loading=lazy を明示するとその判断を上書きして
				 * しまい、一覧の1件目(LCP要素になりやすい)の表示が遅れる。
				 */
				the_post_thumbnail(
					$fellow_is_card ? 'fellow-eyecatch-small' : 'medium',
					array(
						'class' => 'post-item__image',
						'sizes' => fellow_image_sizes( $fellow_is_card ? 'card' : 'list' ),
					)
				);
				?>
			</div>
		<?php endif; ?>
	</a>
</article>
