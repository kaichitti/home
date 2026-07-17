<?php
/**
 * スコアダイヤル。
 *
 * _fellow_review_score が未入力の投稿ではダイヤルごと描画しない
 * (レビュー記事以外にも使うテーマのため)。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

$fellow_dial_score = fellow_get_review_score();

if ( null === $fellow_dial_score ) {
	return;
}

$fellow_dial_percent = (int) round( $fellow_dial_score * 10 );
$fellow_dial_label   = sprintf(
	/* translators: %s: スコア(0.0〜10.0)。 */
	__( 'レビュースコア %s / 10', 'fellow' ),
	number_format_i18n( $fellow_dial_score, 1 )
);
?>
<section class="score-dial">
	<h2 class="score-dial__heading"><?php esc_html_e( '総合評価', 'fellow' ); ?></h2>
	<div
		class="score-dial__ring"
		style="--score-pct:<?php echo esc_attr( $fellow_dial_percent ); ?>"
		role="img"
		aria-label="<?php echo esc_attr( $fellow_dial_label ); ?>"
	>
		<span class="score-dial__value" aria-hidden="true">
			<?php echo esc_html( number_format_i18n( $fellow_dial_score, 1 ) ); ?>
		</span>
		<span class="score-dial__max" aria-hidden="true">/ 10</span>
	</div>
</section>
