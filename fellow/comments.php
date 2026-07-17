<?php
/**
 * コメントテンプレート。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( post_password_required() ) {
	return;
}
?>

<section id="comments" class="comments-area">
	<?php if ( have_comments() ) : ?>
		<h2 class="comments-title">
			<?php
			$fellow_comment_count = get_comments_number();
			/* translators: %s: コメント数。 */
			printf( esc_html( _n( '%s件のコメント', '%s件のコメント', $fellow_comment_count, 'fellow' ) ), esc_html( number_format_i18n( $fellow_comment_count ) ) );
			?>
		</h2>

		<ol class="comment-list">
			<?php
			wp_list_comments(
				array(
					'style'       => 'ol',
					'avatar_size' => 48,
				)
			);
			?>
		</ol>

		<?php the_comments_navigation(); ?>

		<?php if ( ! comments_open() ) : ?>
			<p class="no-comments"><?php esc_html_e( 'コメントは締め切られています。', 'fellow' ); ?></p>
		<?php endif; ?>
	<?php endif; ?>

	<?php comment_form(); ?>
</section>
