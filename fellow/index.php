<?php
/**
 * フォールバックテンプレート(投稿一覧)。
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

		<?php if ( have_posts() ) : ?>
			<div class="<?php echo esc_attr( fellow_post_list_class() ); ?>">
				<?php
				while ( have_posts() ) :
					the_post();
					get_template_part( 'template-parts/content', 'list' );
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
			<p class="no-results"><?php esc_html_e( '記事が見つかりませんでした。', 'fellow' ); ?></p>
		<?php endif; ?>
		</div>

		<?php get_sidebar(); ?>
	</div>
</div>

<?php
get_footer();
