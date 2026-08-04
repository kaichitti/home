<?php
/**
 * 検索結果テンプレート。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

get_header();
?>

<div class="container">
	<?php fellow_breadcrumb(); ?>

	<div class="site-layout">
		<div class="site-layout__main">

		<header class="archive-header">
			<h1 class="archive-title">
				<?php
				/* translators: %s: 検索キーワード。 */
				printf( esc_html__( '「%s」の検索結果', 'fellow' ), esc_html( get_search_query() ) );
				?>
			</h1>
			<?php if ( have_posts() ) : ?>
				<p class="archive-description">
					<?php
					/* translators: %s: ヒット件数。 */
					printf( esc_html__( '%s件見つかりました。', 'fellow' ), esc_html( number_format_i18n( (int) $wp_query->found_posts ) ) );
					?>
				</p>
			<?php endif; ?>
		</header>

		<?php if ( have_posts() ) : ?>
			<div class="card-grid">
				<?php
				while ( have_posts() ) :
					the_post();
					get_template_part( 'template-parts/content', 'card' );
				endwhile;
				?>
			</div>

			<?php
			the_posts_pagination(
				array(
					'prev_text' => __( '前へ', 'fellow' ),
					'next_text' => __( '次へ', 'fellow' ),
				)
			);
			?>
		<?php else : ?>
			<div class="no-results">
				<p><?php esc_html_e( '一致する記事が見つかりませんでした。別のキーワードでお試しください。', 'fellow' ); ?></p>
				<?php get_search_form(); ?>
			</div>
		<?php endif; ?>
		</div>

		<?php get_sidebar(); ?>
	</div>
</div>

<?php
get_footer();
