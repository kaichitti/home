<?php
/**
 * フッターテンプレート。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
?>
</main><!-- #content -->

<footer class="site-footer">
	<div class="site-footer__inner">
		<div class="site-footer__columns">
			<?php if ( has_nav_menu( 'footer-site' ) ) : ?>
				<section class="site-footer__column">
					<h2 class="site-footer__heading"><?php esc_html_e( 'サイト', 'fellow' ); ?></h2>
					<?php
					wp_nav_menu(
						array(
							'theme_location' => 'footer-site',
							'container'      => false,
							'menu_class'     => 'footer-list',
							'fallback_cb'    => false,
							'depth'          => 1,
						)
					);
					?>
				</section>
			<?php endif; ?>

			<section class="site-footer__column">
				<h2 class="site-footer__heading"><?php esc_html_e( 'カテゴリー', 'fellow' ); ?></h2>
				<?php fellow_footer_categories( 6 ); ?>
			</section>

			<section class="site-footer__column">
				<h2 class="site-footer__heading"><?php esc_html_e( 'アーカイブ', 'fellow' ); ?></h2>
				<?php fellow_footer_archives( 5 ); ?>
			</section>

			<?php
			$fellow_sns = fellow_sns_links();
			if ( $fellow_sns ) :
				?>
				<section class="site-footer__column">
					<h2 class="site-footer__heading"><?php esc_html_e( 'フォロー', 'fellow' ); ?></h2>
					<ul class="footer-list footer-list--sns">
						<?php foreach ( $fellow_sns as $fellow_sns_link ) : ?>
							<li>
								<a class="sns-link sns-link--<?php echo esc_attr( $fellow_sns_link['slug'] ); ?>" href="<?php echo esc_url( $fellow_sns_link['url'] ); ?>" target="_blank" rel="noopener noreferrer">
									<?php echo esc_html( $fellow_sns_link['label'] ); ?>
								</a>
							</li>
						<?php endforeach; ?>
					</ul>
				</section>
			<?php endif; ?>
		</div>

		<div class="site-footer__bottom">
			<p class="site-footer__copyright">
				&copy; <?php echo esc_html( gmdate( 'Y' ) ); ?> <a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php bloginfo( 'name' ); ?></a>
			</p>
			<?php if ( fellow_get_option( 'show_footer_credit' ) ) : ?>
				<p class="site-footer__credit">
					<?php
					/* translators: %s: テーマ名。 */
					printf( esc_html__( 'Theme: %s', 'fellow' ), '<span class="site-footer__theme-name">fellow</span>' );
					?>
				</p>
			<?php endif; ?>
		</div>
	</div>
</footer>

<?php wp_footer(); ?>
</body>
</html>
