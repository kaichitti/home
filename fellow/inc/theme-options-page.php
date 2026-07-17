<?php
/**
 * 配布版向けテーマ全体設定ページ(外観 > fellow 設定)。
 *
 * 見た目に関する設定はカスタマイザーに置き、
 * ここには「機能そのもののON/OFF」だけを置く。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * 設定ページの登録。
 */
function fellow_add_options_page() {
	add_theme_page(
		__( 'fellow 設定', 'fellow' ),
		__( 'fellow 設定', 'fellow' ),
		'manage_options',
		'fellow-options',
		'fellow_render_options_page'
	);
}
add_action( 'admin_menu', 'fellow_add_options_page' );

/**
 * 設定・セクション・フィールドの登録。
 */
function fellow_register_settings() {
	register_setting(
		'fellow_options_group',
		'fellow_options',
		array(
			'type'              => 'array',
			'sanitize_callback' => 'fellow_sanitize_options',
			'default'           => array(),
		)
	);

	add_settings_section(
		'fellow_features_section',
		__( '機能のON/OFF', 'fellow' ),
		'__return_null',
		'fellow-options'
	);

	add_settings_field(
		'enable_review_score',
		__( 'レビュースコア機能', 'fellow' ),
		'fellow_render_checkbox_field',
		'fellow-options',
		'fellow_features_section',
		array(
			'key'         => 'enable_review_score',
			'label'       => __( 'レビュースコアのメタボックスとスコアダイヤルを有効にする', 'fellow' ),
			'description' => __( 'レビュー機能を使わないブログではオフにできます。保存済みのスコアは削除されません。', 'fellow' ),
		)
	);

	add_settings_field(
		'show_footer_credit',
		__( 'フッタークレジット', 'fellow' ),
		'fellow_render_checkbox_field',
		'fellow-options',
		'fellow_features_section',
		array(
			'key'         => 'show_footer_credit',
			'label'       => __( 'フッターにテーマクレジットを表示する', 'fellow' ),
			'description' => __( 'クレジット表記はいつでも非表示にできます(GPLのため義務ではありません)。', 'fellow' ),
		)
	);
}
add_action( 'admin_init', 'fellow_register_settings' );

/**
 * オプションのサニタイズ。
 *
 * @param mixed $input 入力値。
 * @return array
 */
function fellow_sanitize_options( $input ) {
	$input = (array) $input;

	return array(
		'enable_review_score' => empty( $input['enable_review_score'] ) ? 0 : 1,
		'show_footer_credit'  => empty( $input['show_footer_credit'] ) ? 0 : 1,
	);
}

/**
 * チェックボックスフィールドの描画。
 *
 * @param array $args key / label / description。
 */
function fellow_render_checkbox_field( $args ) {
	$key   = $args['key'];
	$value = fellow_get_option( $key );
	?>
	<label>
		<input
			type="checkbox"
			name="fellow_options[<?php echo esc_attr( $key ); ?>]"
			value="1"
			<?php checked( $value, 1 ); ?>
		>
		<?php echo esc_html( $args['label'] ); ?>
	</label>
	<?php if ( ! empty( $args['description'] ) ) : ?>
		<p class="description"><?php echo esc_html( $args['description'] ); ?></p>
		<?php
	endif;
}

/**
 * 設定ページの描画。
 */
function fellow_render_options_page() {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'fellow 設定', 'fellow' ); ?></h1>
		<p><?php esc_html_e( '色やロゴなど見た目の設定は「外観 > カスタマイズ」から行えます。', 'fellow' ); ?></p>
		<form action="options.php" method="post">
			<?php
			settings_fields( 'fellow_options_group' );
			do_settings_sections( 'fellow-options' );
			submit_button();
			?>
		</form>
	</div>
	<?php
}
