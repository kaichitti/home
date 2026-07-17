<?php
/**
 * レビュースコア用メタボックス。
 *
 * プラグイン(ACF等)非依存。素の add_meta_box + post_meta で実装する。
 * メタキー: _fellow_review_score(0.0〜10.0、小数第1位)。
 * 未入力の投稿ではスコア関連UIを一切描画しない。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * レビュースコアのメタキー。
 */
const FELLOW_REVIEW_SCORE_KEY = '_fellow_review_score';

/**
 * 投稿編集画面にメタボックスを追加する。
 */
function fellow_add_review_meta_box() {
	if ( ! fellow_get_option( 'enable_review_score' ) ) {
		return;
	}

	add_meta_box(
		'fellow-review-score',
		__( 'レビュースコア', 'fellow' ),
		'fellow_render_review_meta_box',
		'post',
		'side',
		'default'
	);
}
add_action( 'add_meta_boxes', 'fellow_add_review_meta_box' );

/**
 * メタボックスの描画。
 *
 * @param WP_Post $post 編集中の投稿。
 */
function fellow_render_review_meta_box( $post ) {
	$score = get_post_meta( $post->ID, FELLOW_REVIEW_SCORE_KEY, true );

	wp_nonce_field( 'fellow_save_review_score', 'fellow_review_score_nonce' );
	?>
	<p>
		<label for="fellow-review-score-field">
			<?php esc_html_e( 'スコア(0.0〜10.0)', 'fellow' ); ?>
		</label>
	</p>
	<p>
		<input
			type="number"
			id="fellow-review-score-field"
			name="fellow_review_score"
			value="<?php echo esc_attr( $score ); ?>"
			min="0"
			max="10"
			step="0.1"
			style="width:100%"
		>
	</p>
	<p class="description">
		<?php esc_html_e( '未入力にするとこの記事にはスコアダイヤルが表示されません。', 'fellow' ); ?>
	</p>
	<?php
}

/**
 * メタボックスの保存処理。
 *
 * @param int $post_id 保存対象の投稿ID。
 */
function fellow_save_review_score( $post_id ) {
	if ( ! isset( $_POST['fellow_review_score_nonce'] ) ) {
		return;
	}

	$nonce = sanitize_text_field( wp_unslash( $_POST['fellow_review_score_nonce'] ) );

	if ( ! wp_verify_nonce( $nonce, 'fellow_save_review_score' ) ) {
		return;
	}

	if ( defined( 'DOING_AUTOSAVE' ) && DOING_AUTOSAVE ) {
		return;
	}

	if ( ! current_user_can( 'edit_post', $post_id ) ) {
		return;
	}

	if ( ! isset( $_POST['fellow_review_score'] ) ) {
		return;
	}

	$raw = sanitize_text_field( wp_unslash( $_POST['fellow_review_score'] ) );

	if ( '' === $raw || ! is_numeric( $raw ) ) {
		delete_post_meta( $post_id, FELLOW_REVIEW_SCORE_KEY );
		return;
	}

	$score = round( (float) $raw, 1 );
	$score = max( 0.0, min( 10.0, $score ) );

	update_post_meta( $post_id, FELLOW_REVIEW_SCORE_KEY, number_format( $score, 1, '.', '' ) );
}
add_action( 'save_post_post', 'fellow_save_review_score' );

/**
 * レビュースコアを取得する。未入力/機能オフなら null。
 *
 * @param int $post_id 投稿ID。省略時は現在の投稿。
 * @return float|null
 */
function fellow_get_review_score( $post_id = 0 ) {
	if ( ! fellow_get_option( 'enable_review_score' ) ) {
		return null;
	}

	$post_id = $post_id ? $post_id : get_the_ID();

	if ( ! $post_id ) {
		return null;
	}

	$raw = get_post_meta( $post_id, FELLOW_REVIEW_SCORE_KEY, true );

	if ( '' === $raw || ! is_numeric( $raw ) ) {
		return null;
	}

	return max( 0.0, min( 10.0, round( (float) $raw, 1 ) ) );
}
