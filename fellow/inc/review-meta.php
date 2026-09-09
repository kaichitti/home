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
		__( 'fellow 記事設定', 'fellow' ),
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
	$score   = get_post_meta( $post->ID, FELLOW_REVIEW_SCORE_KEY, true );
	$item    = get_post_meta( $post->ID, '_fellow_review_item', true );
	$noindex = get_post_meta( $post->ID, '_fellow_noindex', true );

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

	<hr>

	<p>
		<label for="fellow-review-item-field">
			<?php esc_html_e( 'レビュー対象の名前', 'fellow' ); ?>
		</label>
	</p>
	<p>
		<input
			type="text"
			id="fellow-review-item-field"
			name="fellow_review_item"
			value="<?php echo esc_attr( $item ); ?>"
			style="width:100%"
		>
	</p>
	<p class="description">
		<?php esc_html_e( '構造化データ(Review)で「何をレビューしたか」として使われます。空欄なら記事タイトルが使われます。', 'fellow' ); ?>
	</p>

	<hr>

	<p>
		<label for="fellow-noindex-field">
			<input
				type="checkbox"
				id="fellow-noindex-field"
				name="fellow_noindex"
				value="1"
				<?php checked( $noindex, '1' ); ?>
			>
			<?php esc_html_e( 'この記事を検索エンジンに登録させない(noindex)', 'fellow' ); ?>
		</label>
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

	// レビュー対象名。空なら削除する。
	if ( isset( $_POST['fellow_review_item'] ) ) {
		$item = sanitize_text_field( wp_unslash( $_POST['fellow_review_item'] ) );

		if ( '' === trim( $item ) ) {
			delete_post_meta( $post_id, '_fellow_review_item' );
		} else {
			update_post_meta( $post_id, '_fellow_review_item', $item );
		}
	}

	// noindex はチェックボックスなので、未送信＝オフとして扱う。
	if ( isset( $_POST['fellow_noindex'] ) ) {
		update_post_meta( $post_id, '_fellow_noindex', '1' );
	} else {
		delete_post_meta( $post_id, '_fellow_noindex' );
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
