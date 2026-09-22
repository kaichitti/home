<?php
/**
 * トップページ(固定フロントページ設定時)。
 *
 * 「最新の投稿」設定のままの場合は home.php に委譲する。
 * 固定ページを割り当てている場合は page.php と同じ2カラム構成にする
 * (ここだけサイドバーを呼ばないと、body に has-sidebar が付いたまま
 *  2列目が空になってしまうため)。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( 'posts' === get_option( 'show_on_front' ) ) {
	include get_home_template();
	return;
}

get_header();
?>

<div class="<?php echo esc_attr( fellow_container_class() ); ?>">
	<div class="site-layout">
		<div class="site-layout__main">
			<?php
			while ( have_posts() ) :
				the_post();
				?>
				<article id="post-<?php the_ID(); ?>" <?php post_class( 'entry' ); ?>>
					<div class="entry-content">
						<?php the_content(); ?>
					</div>
				</article>
			<?php endwhile; ?>
		</div>

		<?php get_sidebar(); ?>
	</div>
</div>

<?php
get_footer();
