<?php
/**
 * 検索フォームテンプレート(get_search_form() から呼ばれる)。
 *
 * JS無効環境でもネイティブの form として機能する。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}
?>
<form role="search" method="get" class="search-form" action="<?php echo esc_url( home_url( '/' ) ); ?>">
	<label class="search-form__label">
		<span class="screen-reader-text"><?php esc_html_e( '検索キーワード', 'fellow' ); ?></span>
		<input
			type="search"
			class="search-form__field"
			placeholder="<?php esc_attr_e( 'サイト内を検索', 'fellow' ); ?>"
			value="<?php echo esc_attr( get_search_query() ); ?>"
			name="s"
		>
	</label>
	<button type="submit" class="search-form__submit"><?php esc_html_e( '検索', 'fellow' ); ?></button>
</form>
