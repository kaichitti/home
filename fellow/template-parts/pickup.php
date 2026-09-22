<?php
/**
 * ピックアップ記事。
 *
 * 通常のリストと差をつけるため、番号を振ったアクセントカラーの枠で見せる。
 * アイキャッチには依存しない(画像を設定しない運用でも成立させるため)。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

$fellow_pickup_ids = fellow_pickup_ids();

if ( ! $fellow_pickup_ids ) {
	return;
}

$fellow_pickup = new WP_Query(
	array(
		'post_type'           => 'post',
		'post__in'            => $fellow_pickup_ids,
		'orderby'             => 'post__in',
		'posts_per_page'      => count( $fellow_pickup_ids ),
		'ignore_sticky_posts' => true,
		'no_found_rows'       => true,
	)
);

if ( ! $fellow_pickup->have_posts() ) {
	return;
}
?>
<section class="pickup">
	<h2 class="pickup__heading"><?php esc_html_e( 'ピックアップ', 'fellow' ); ?></h2>

	<ol class="pickup__list">
		<?php
		$fellow_pickup_index = 0;
		while ( $fellow_pickup->have_posts() ) :
			$fellow_pickup->the_post();
			++$fellow_pickup_index;
			$fellow_pickup_score = fellow_get_review_score();
			$fellow_pickup_cats  = get_the_category();
			?>
			<li class="pickup__item">
				<a class="pickup__link" href="<?php the_permalink(); ?>">
					<span class="pickup__num" aria-hidden="true">
						<?php echo esc_html( str_pad( (string) $fellow_pickup_index, 2, '0', STR_PAD_LEFT ) ); ?>
					</span>

					<span class="pickup__body">
						<?php if ( $fellow_pickup_cats ) : ?>
							<span class="pickup__category"><?php echo esc_html( $fellow_pickup_cats[0]->name ); ?></span>
						<?php endif; ?>

						<span class="pickup__title"><?php the_title(); ?></span>
					</span>

					<?php if ( null !== $fellow_pickup_score ) : ?>
						<span class="pickup__score">
							<?php echo esc_html( number_format_i18n( $fellow_pickup_score, 1 ) ); ?>
						</span>
					<?php endif; ?>
				</a>
			</li>
			<?php
		endwhile;
		wp_reset_postdata();
		?>
	</ol>
</section>
