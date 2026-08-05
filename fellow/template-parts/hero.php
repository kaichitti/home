<?php
/**
 * ヘッダー直下の紹介の帯。
 *
 * header.php から毎ページ呼ばれるが、描画するのはブログトップの1ページ目だけ。
 * サイドバーの外に出したいので、コンテナの内側ではなくここで全幅として出す。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( ! fellow_show_hero() ) {
	return;
}

$fellow_hero = fellow_hero_text();
?>
<section class="site-hero">
	<div class="site-hero__inner">
		<?php if ( '' !== $fellow_hero['title'] ) : ?>
			<p class="site-hero__title"><?php echo esc_html( $fellow_hero['title'] ); ?></p>
		<?php endif; ?>

		<?php if ( '' !== $fellow_hero['lead'] ) : ?>
			<p class="site-hero__lead"><?php echo esc_html( $fellow_hero['lead'] ); ?></p>
		<?php endif; ?>
	</div>
</section>
