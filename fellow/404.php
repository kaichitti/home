<?php
/**
 * 404テンプレート。検索ボックスと人気カテゴリーへの導線を置く。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

get_header();
?>

<div class="container container--narrow">
	<?php fellow_breadcrumb(); ?>

	<section class="error-404">
		<p class="error-404__code" aria-hidden="true">404</p>
		<h1 class="error-404__title"><?php esc_html_e( 'ページが見つかりませんでした', 'fellow' ); ?></h1>
		<p class="error-404__text">
			<?php esc_html_e( 'お探しのページは移動または削除された可能性があります。キーワード検索か、カテゴリーからお探しください。', 'fellow' ); ?>
		</p>

		<div class="error-404__search">
			<?php get_search_form(); ?>
		</div>

		<h2 class="section-title"><?php esc_html_e( '人気カテゴリー', 'fellow' ); ?></h2>
		<?php fellow_footer_categories( 6 ); ?>

		<p class="error-404__home">
			<a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php esc_html_e( 'トップページへ戻る', 'fellow' ); ?></a>
		</p>
	</section>
</div>

<?php
get_footer();
