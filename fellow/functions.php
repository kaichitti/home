<?php
/**
 * fellow エントリポイント。
 *
 * ロジックはすべて inc/ 配下に置き、このファイルは require のみ行う。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

require get_template_directory() . '/inc/setup.php';
require get_template_directory() . '/inc/enqueue.php';
require get_template_directory() . '/inc/customizer.php';
require get_template_directory() . '/inc/review-meta.php';
require get_template_directory() . '/inc/template-tags.php';
require get_template_directory() . '/inc/front-page-parts.php';
require get_template_directory() . '/inc/seo.php';
require get_template_directory() . '/inc/structured-data.php';
require get_template_directory() . '/inc/toc.php';
require get_template_directory() . '/inc/widget-toc.php';
require get_template_directory() . '/inc/walker-nav.php';

if ( is_admin() ) {
	require get_template_directory() . '/inc/theme-options-page.php';
}
