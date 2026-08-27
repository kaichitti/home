<?php
/**
 * カテゴリー導線(トップ1ページ目のみ)。
 *
 * 画像バナーではなくテキストのチップで並べる。アイキャッチを設定しない
 * 運用でも成立し、カテゴリーが増減しても崩れないため。
 * スマホでは横スクロールにして、ファーストビューの縦を消費しない。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( ! fellow_show_category_nav() ) {
	return;
}

$fellow_nav_terms = fellow_category_nav_terms();

if ( ! $fellow_nav_terms ) {
	return;
}
?>
<nav class="category-nav" aria-label="<?php esc_attr_e( 'カテゴリーから探す', 'fellow' ); ?>">
	<ul class="category-nav__list">
		<?php foreach ( $fellow_nav_terms as $fellow_nav_term ) : ?>
			<li class="category-nav__item">
				<a class="category-nav__link" href="<?php echo esc_url( get_category_link( $fellow_nav_term ) ); ?>">
					<span class="category-nav__name"><?php echo esc_html( $fellow_nav_term->name ); ?></span>
					<span class="category-nav__count"><?php echo esc_html( number_format_i18n( $fellow_nav_term->count ) ); ?></span>
				</a>
			</li>
		<?php endforeach; ?>
	</ul>
</nav>
