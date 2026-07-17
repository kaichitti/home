<?php
/**
 * 記事詳細テンプレート。
 *
 * 構造: パンくず → 記事ヘッダー → 本文(+TOC) → スコアダイヤル →
 *       シェア → 著者 → 前後記事 → 関連記事 → コメント。
 * TOCはデスクトップでサイドバー、スマホでは本文上の折りたたみ(CSS/JSで制御)。
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

			<div class="entry-layout">
				<aside class="entry-toc" id="entry-toc" hidden>
					<button type="button" class="entry-toc__toggle" aria-expanded="false" aria-controls="entry-toc-list">
						<?php esc_html_e( '目次', 'fellow' ); ?>
					</button>
					<nav class="entry-toc__body" id="entry-toc-list" aria-label="<?php esc_attr_e( '目次', 'fellow' ); ?>"></nav>
				</aside>

				<div class="entry-content" data-toc-source>
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
			</div>

			<?php get_template_part( 'template-parts/score-dial' ); ?>

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
				<div class="card-grid">
					<?php
					while ( $fellow_related->have_posts() ) :
						$fellow_related->the_post();
						get_template_part( 'template-parts/content', 'card' );
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

<?php
get_footer();
