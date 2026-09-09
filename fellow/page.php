<?php
/**
 * 固定ページテンプレート。
 *
 * 記事詳細と同じく本文+サイドバーの2カラム。
 * サイドバーのウィジェットが空のときは自動的に1カラムになり、
 * その場合は読みやすい幅に絞る(fellow_container_class)。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

get_header();
?>

<div class="<?php echo esc_attr( fellow_container_class() ); ?>">
	<?php fellow_breadcrumb(); ?>

	<div class="site-layout">
		<div class="site-layout__main">
			<?php
			while ( have_posts() ) :
				the_post();
				?>
				<article id="post-<?php the_ID(); ?>" <?php post_class( 'entry' ); ?>>
					<header class="entry-header">
						<h1 class="entry-title"><?php the_title(); ?></h1>
					</header>

					<?php if ( has_post_thumbnail() ) : ?>
						<figure class="entry-eyecatch">
							<?php
							the_post_thumbnail(
								'fellow-eyecatch',
								array(
									'loading'       => 'eager',
									'fetchpriority' => 'high',
								)
							);
							?>
						</figure>
					<?php endif; ?>

					<div class="entry-content">
						<?php
						the_content();

						wp_link_pages(
							array(
								'before' => '<nav class="page-links">' . esc_html__( 'ページ:', 'fellow' ),
								'after'  => '</nav>',
							)
						);
						?>
					</div>

					<?php fellow_after_entry_widgets(); ?>
				</article>

				<?php
				if ( comments_open() || get_comments_number() ) :
					comments_template();
				endif;
				?>
			<?php endwhile; ?>
		</div>

		<?php get_sidebar(); ?>
	</div>
</div>

<?php
get_footer();
