<?php
/**
 * カテゴリー/タグ/年別アーカイブ共通テンプレート。
 *
 * タイトルは get_the_archive_title フィルター(fellow_archive_title)で
 * 日本語向けに整形される。
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
			<h1 class="archive-title"><?php the_archive_title(); ?></h1>
			<?php the_archive_description( '<div class="archive-description">', '</div>' ); ?>
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
			<p class="no-results"><?php esc_html_e( 'このアーカイブには記事がありません。', 'fellow' ); ?></p>
		<?php endif; ?>
		</div>

		<?php get_sidebar(); ?>
	</div>
</div>

<?php
get_footer();
