<?php
/**
 * サイドバー。
 *
 * ウィジェットが1つも無い場合は何も出力しない(空の列を作らないため)。
 * 位置(右/左/非表示)はカスタマイザーで切り替える。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( ! fellow_has_sidebar() ) {
	return;
}
?>
<aside class="site-sidebar" id="site-sidebar" aria-label="<?php esc_attr_e( 'サイドバー', 'fellow' ); ?>">
	<?php if ( is_active_sidebar( 'sidebar-main' ) ) : ?>
		<div class="site-sidebar__section">
			<?php dynamic_sidebar( 'sidebar-main' ); ?>
		</div>
	<?php endif; ?>

	<?php if ( is_active_sidebar( 'sidebar-sticky' ) ) : ?>
		<div class="site-sidebar__section site-sidebar__section--sticky">
			<?php dynamic_sidebar( 'sidebar-sticky' ); ?>
		</div>
	<?php endif; ?>
</aside>
