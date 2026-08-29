<?php
/**
 * ヘッダーテンプレート。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
?>
<!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo( 'charset' ); ?>">
<meta name="viewport" content="width=device-width, initial-scale=1">
<?php wp_head(); ?>
</head>
<body <?php body_class( fellow_is_sticky_header() ? 'has-sticky-header' : '' ); ?>>
<?php wp_body_open(); ?>

<a class="skip-link screen-reader-text" href="#content"><?php esc_html_e( '本文へスキップ', 'fellow' ); ?></a>

<header class="site-header" id="site-header">
	<div class="site-header__inner">
		<div class="site-branding">
			<?php if ( has_custom_logo() ) : ?>
				<?php the_custom_logo(); ?>
			<?php else : ?>
				<?php if ( is_front_page() && ! is_paged() ) : ?>
					<h1 class="site-title"><a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php bloginfo( 'name' ); ?></a></h1>
				<?php else : ?>
					<p class="site-title"><a href="<?php echo esc_url( home_url( '/' ) ); ?>"><?php bloginfo( 'name' ); ?></a></p>
				<?php endif; ?>
			<?php endif; ?>
		</div>

		<?php if ( has_nav_menu( 'primary' ) ) : ?>
		<nav class="global-nav" id="global-nav" aria-label="<?php esc_attr_e( 'メインメニュー', 'fellow' ); ?>">
			<?php
			wp_nav_menu(
				array(
					'theme_location' => 'primary',
					'container'      => false,
					'menu_class'     => 'global-nav__list',
					'fallback_cb'    => false,
					'walker'         => new Fellow_Walker_Nav(),
				)
			);
			?>
		</nav>
		<?php endif; ?>

		<div class="header-actions">
			<?php if ( fellow_show_search() ) : ?>
				<div class="header-search" id="header-search">
					<button type="button" class="header-search__toggle" aria-expanded="false" aria-controls="header-search-form">
						<span class="screen-reader-text"><?php esc_html_e( '検索ボックスを開閉', 'fellow' ); ?></span>
						<span class="icon-search" aria-hidden="true"></span>
					</button>
					<div class="header-search__form" id="header-search-form">
						<?php get_search_form(); ?>
					</div>
				</div>
			<?php endif; ?>

			<?php if ( has_nav_menu( 'primary' ) ) : ?>
				<?php /* メニュー未割り当てのときは、空のドロワーが開くだけなので出さない。 */ ?>
				<button type="button" class="nav-toggle" aria-expanded="false" aria-controls="global-nav">
					<span class="screen-reader-text"><?php esc_html_e( 'メニューを開閉', 'fellow' ); ?></span>
					<span class="nav-toggle__bar" aria-hidden="true"></span>
				</button>
			<?php endif; ?>
		</div>
	</div>
</header>

<?php get_template_part( 'template-parts/hero' ); ?>

<main id="content" class="site-main">
