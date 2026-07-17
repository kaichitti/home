<?php
/**
 * 記事カード。home.php / archive.php / single.php(関連記事)から共通で呼ぶ。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

$fellow_card_score      = fellow_get_review_score();
$fellow_card_categories = get_the_category();
?>
<article id="post-<?php the_ID(); ?>" <?php post_class( 'card' ); ?>>
	<a class="card__link" href="<?php the_permalink(); ?>">
		<div class="card__media">
			<?php if ( has_post_thumbnail() ) : ?>
				<?php the_post_thumbnail( 'fellow-card', array( 'loading' => 'lazy', 'class' => 'card__image' ) ); ?>
			<?php else : ?>
				<span class="card__image card__image--placeholder" aria-hidden="true"></span>
			<?php endif; ?>

			<?php if ( null !== $fellow_card_score ) : ?>
				<span class="card__score">
					<?php echo esc_html( number_format_i18n( $fellow_card_score, 1 ) ); ?>
				</span>
			<?php endif; ?>
		</div>

		<div class="card__body">
			<?php if ( $fellow_card_categories ) : ?>
				<span class="card__category"><?php echo esc_html( $fellow_card_categories[0]->name ); ?></span>
			<?php endif; ?>

			<h3 class="card__title"><?php the_title(); ?></h3>

			<div class="card__meta">
				<?php fellow_entry_date(); ?>
			</div>
		</div>
	</a>
</article>
