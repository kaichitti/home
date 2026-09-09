<?php
/**
 * 記事詳細テンプレート。
 *
 * 構造: パンくず → 記事ヘッダー → 本文 → スコアダイヤル → タグ →
 *       シェア → 著者 → 前後記事 → 関連記事 → コメント。
 * 目次は inc/toc.php が本文の最初の見出し直前に挿入する。
 * サイドバー(ウィジェット)は sidebar.php が担当する。
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

		<?php
		while ( have_posts() ) :
			the_post();
			?>
			<article id="post-<?php the_ID(); ?>" <?php post_class( 'entry entry--single' ); ?>>
				<header class="entry-header">
					<?php $fellow_categories = get_the_category(); ?>
					<?php if ( $fellow_categories ) : ?>
						<a class="entry-category" href="<?php echo esc_url( get_category_link( $fellow_categories[0] ) ); ?>">
							<?php echo esc_html( $fellow_categories[0]->name ); ?>
						</a>
					<?php endif; ?>

					<h1 class="entry-title"><?php the_title(); ?></h1>

					<div class="entry-meta">
						<?php fellow_entry_date(); ?>
					</div>

					<?php if ( has_post_thumbnail() ) : ?>
						<figure class="entry-eyecatch">
							<?php
							// アイキャッチはLCP要素のため lazy にせず優先読み込みする。
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
				</header>

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

				<?php get_template_part( 'template-parts/score-dial' ); ?>

				<?php fellow_entry_tags(); ?>

				<?php fellow_share_links(); ?>

				<?php if ( get_the_author_meta( 'description' ) ) : ?>
					<section class="author-box">
						<div class="author-box__avatar">
							<?php echo get_avatar( get_the_author_meta( 'ID' ), 72 ); ?>
						</div>
						<div class="author-box__body">
							<h2 class="author-box__name">
								<?php
								/* translators: %s: 著者名。 */
								printf( esc_html__( 'この記事を書いた人:%s', 'fellow' ), esc_html( get_the_author() ) );
								?>
							</h2>
							<p class="author-box__description"><?php echo esc_html( get_the_author_meta( 'description' ) ); ?></p>
						</div>
					</section>
				<?php endif; ?>

				<?php
				the_post_navigation(
					array(
						'prev_text' => '<span class="post-navigation__label">' . esc_html__( '前の記事', 'fellow' ) . '</span><span class="post-navigation__title">%title</span>',
						'next_text' => '<span class="post-navigation__label">' . esc_html__( '次の記事', 'fellow' ) . '</span><span class="post-navigation__title">%title</span>',
					)
				);
				?>
			</article>

			<?php
			$fellow_related = fellow_related_posts_query( 3 );
			if ( $fellow_related->have_posts() ) :
				?>
				<section class="related-posts">
					<h2 class="section-title"><?php esc_html_e( '関連記事', 'fellow' ); ?></h2>
					<div class="post-list">
						<?php
						while ( $fellow_related->have_posts() ) :
							$fellow_related->the_post();
							get_template_part( 'template-parts/content', 'list' );
						endwhile;
						wp_reset_postdata();
						?>
					</div>
				</section>
			<?php endif; ?>

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
