<?php
/**
 * ブログトップ(最新記事一覧)。
 *
 * 1ページ目の先頭にピックアップ記事を置き、その下に通常のリストを並べる。
 * ピックアップに出した記事は下の一覧から除いて重複させない。
 * ヘッダー直下の紹介の帯は header.php 側で全幅として出している。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

get_header();

$fellow_pickup_ids = fellow_pickup_ids();
?>

<div class="container">

	<div class="site-layout">
		<div class="site-layout__main">
			<?php get_template_part( 'template-parts/category-nav' ); ?>

			<?php get_template_part( 'template-parts/pickup' ); ?>

			<?php if ( have_posts() ) : ?>
				<?php
				/*
				 * header.php はフロントページでのみサイト名を h1 で出す。
				 * そこと重複しないよう、見出しレベルを切り替える。
				 * (静的フロントページを設定した場合、このテンプレートは
				 *  ブログ用ページになるので h1 を持つ側になる)
				 */
				$fellow_home_heading = ( is_front_page() && ! is_paged() ) ? 'h2' : 'h1';
				?>
				<<?php echo esc_attr( $fellow_home_heading ); ?> class="section-title">
					<?php esc_html_e( '最新記事', 'fellow' ); ?>
				</<?php echo esc_attr( $fellow_home_heading ); ?>>

				<div class="post-list">
					<?php
					$fellow_shown = 0;

					while ( have_posts() ) :
						the_post();

						// ピックアップに出した記事はここでは飛ばす。
						if ( in_array( get_the_ID(), $fellow_pickup_ids, true ) ) {
							continue;
						}

						++$fellow_shown;
						get_template_part( 'template-parts/content', 'list' );
					endwhile;

					if ( 0 === $fellow_shown ) :
						?>
						<p class="no-results"><?php esc_html_e( 'ほかに記事がありません。', 'fellow' ); ?></p>
						<?php
					endif;
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
