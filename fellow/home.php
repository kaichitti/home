<?php
/**
 * ブログトップ(最新記事一覧)。
 *
 * 全記事を同じリスト形式で並べる。先頭1件を大きく見せる枠は持たない
 * (アイキャッチ未設定の記事が多いと、大きな画像枠が空のまま残るため)。
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
				<h1 class="section-title"><?php esc_html_e( '最新記事', 'fellow' ); ?></h1>

				<div class="post-list">
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
				<p class="no-results"><?php esc_html_e( 'まだ記事がありません。', 'fellow' ); ?></p>
			<?php endif; ?>
		</div>

		<?php get_sidebar(); ?>
	</div>
</div>

<?php
get_footer();
