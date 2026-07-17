<?php
/**
 * トップの注目記事ブロック(ブログトップ1ページ目の先頭1件)。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

$fellow_featured_score      = fellow_get_review_score();
$fellow_featured_categories = get_the_category();
?>
<article id="post-<?php the_ID(); ?>" <?php post_class( 'featured' ); ?>>
	<a class="featured__link" href="<?php the_permalink(); ?>">
		<div class="featured__media">
			<?php if ( has_post_thumbnail() ) : ?>
				<?php
				// トップのLCP要素になるため lazy にしない。
				the_post_thumbnail(
					'fellow-eyecatch',
					array(
						'loading'       => 'eager',
						'fetchpriority' => 'high',
						'class'         => 'featured__image',
					)
				);
				?>
			<?php else : ?>
				<span class="featured__image card__image--placeholder" aria-hidden="true"></span>
			<?php endif; ?>
		</div>

		<div class="featured__body">
			<span class="featured__badge"><?php esc_html_e( '注目記事', 'fellow' ); ?></span>

			<?php if ( $fellow_featured_categories ) : ?>
				<span class="card__category"><?php echo esc_html( $fellow_featured_categories[0]->name ); ?></span>
			<?php endif; ?>

			<h2 class="featured__title"><?php the_title(); ?></h2>

			<p class="featured__excerpt"><?php echo esc_html( wp_trim_words( get_the_excerpt(), 60 ) ); ?></p>

			<div class="card__meta">
				<?php fellow_entry_date(); ?>
				<?php if ( null !== $fellow_featured_score ) : ?>
					<span class="card__score card__score--inline">
						<?php echo esc_html( number_format_i18n( $fellow_featured_score, 1 ) ); ?>
					</span>
				<?php endif; ?>
			</div>
		</div>
	</a>
</article>
