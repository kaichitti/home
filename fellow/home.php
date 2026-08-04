<?php
/**
 * ブログトップ(最新記事一覧)。
 *
 * 1ページ目のみ先頭の1件を注目記事として大きく表示し、
 * 残りをカードグリッドで並べる。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

get_header();
?>

<div class="container">

	<div class="site-layout">
		<div class="site-layout__main">
		<?php if ( have_posts() ) : ?>

			<?php
			// 1ページ目だけ先頭の投稿を注目記事枠で消費する。
			if ( ! is_paged() ) :
				the_post();
				get_template_part( 'template-parts/content', 'featured' );
			endif;
			?>

			<?php if ( have_posts() ) : ?>
				<h2 class="section-title"><?php esc_html_e( '最新記事', 'fellow' ); ?></h2>
				<div class="card-grid">
					<?php
					while ( have_posts() ) :
						the_post();
						get_template_part( 'template-parts/content', 'card' );
					endwhile;
					?>
				</div>
			<?php endif; ?>

			<?php
			the_posts_pagination(
				array(
					'prev_text' => __( '前へ', 'fellow' ),
					'next_text' => __( '次へ', 'fellow' ),
				)
			);
			?>

		<?php else : ?>
			<p class="no-results"><?php esc_html_e( 'まだ記事がありません。', 'fellow' ); ?></p>
		<?php endif; ?>
		</div>

		<?php get_sidebar(); ?>
	</div>
</div>

<?php
get_footer();
