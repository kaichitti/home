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
 * 初期設定の状況を返す。
 *
 * テーマ選択画面の見本(screenshot.png)は各所を設定し終えた状態を写している。
 * 未設定の項目があるとその部分は描画されず、「見本と違う」という印象になるため、
 * 何が残っているのかを設定ページで一覧できるようにする。
 *
 * @return array{label:string,done:bool,note:string,link:string,link_label:string}[]
 */
function fellow_setup_status() {
	$has_sidebar = is_active_sidebar( 'sidebar-main' ) || is_active_sidebar( 'sidebar-sticky' );
	$front_posts = ( 'posts' === get_option( 'show_on_front' ) );

	return array(
		array(
			'label'      => __( 'ヘッダーメニュー', 'fellow' ),
			'done'       => has_nav_menu( 'primary' ),
			'note'       => __( '未割り当ての間は、ヘッダーのメニューとスマホのハンバーガーを表示しません。', 'fellow' ),
			'link'       => admin_url( 'nav-menus.php' ),
			'link_label' => __( 'メニューを設定', 'fellow' ),
		),
		array(
			'label'      => __( 'サイドバー', 'fellow' ),
			'done'       => $has_sidebar,
			'note'       => __( 'ウィジェットが1つも無いとサイドバーは描画されず、本文が全幅になります。', 'fellow' ),
			'link'       => admin_url( 'widgets.php' ),
			'link_label' => __( 'ウィジェットを配置', 'fellow' ),
		),
		array(
			'label'      => __( 'ホームページの表示', 'fellow' ),
			'done'       => $front_posts,
			/*
			 * ここが「固定ページ」だと home.php が使われないため、
			 * 紹介の帯・カテゴリー導線・ピックアップ・リスト型一覧が
			 * まとめて出なくなる。見本との差が一番大きく出るのがこの設定。
			 */
			'note'       => __( '「固定ページ」になっています。この場合トップは固定ページの中身がそのまま出るため、紹介の帯・カテゴリー導線・ピックアップ・リスト型一覧は使われません。見本と同じ構成にするには「最新の投稿」を選んでください。', 'fellow' ),
			'link'       => admin_url( 'options-reading.php' ),
			'link_label' => __( '表示設定を開く', 'fellow' ),
		),
		array(
			'label'      => __( 'ピックアップ記事', 'fellow' ),
			'done'       => ( 'sticky' !== get_theme_mod( 'fellow_pickup_source', 'sticky' ) ) || ( array() !== get_option( 'sticky_posts', array() ) ),
			'note'       => __( 'ピックアップの取得元が「先頭に固定した記事」ですが、固定された記事がまだありません。投稿を固定するか、カスタマイザーで「最新の記事」に変えてください。', 'fellow' ),
			'link'       => admin_url( 'edit.php' ),
			'link_label' => __( '投稿一覧を開く', 'fellow' ),
		),
	);
}

/**
 * 初期設定の状況パネルを描画する。
 */
function fellow_render_setup_status() {
	$items = fellow_setup_status();
	$todo  = 0;

	foreach ( $items as $item ) {
		if ( ! $item['done'] ) {
			++$todo;
		}
	}
	?>
	<h2><?php esc_html_e( '初期設定の状況', 'fellow' ); ?></h2>
	<?php if ( 0 === $todo ) : ?>
		<p><?php esc_html_e( '設定は一通り終わっています。', 'fellow' ); ?></p>
	<?php else : ?>
		<p>
			<?php
			printf(
				/* translators: %d: number of unfinished setup items. */
				esc_html( _n( '未設定の項目が %d 件あります。テーマ見本と見た目が違う場合は、まずここを確認してください。', '未設定の項目が %d 件あります。テーマ見本と見た目が違う場合は、まずここを確認してください。', $todo, 'fellow' ) ),
				(int) $todo
			);
			?>
		</p>
	<?php endif; ?>

	<table class="widefat striped" style="max-width:48rem;margin-bottom:2rem;">
		<tbody>
		<?php foreach ( $items as $item ) : ?>
			<tr>
				<td style="width:12rem;"><strong><?php echo esc_html( $item['label'] ); ?></strong></td>
				<td style="width:6rem;">
					<?php if ( $item['done'] ) : ?>
						<span style="color:#1a7f37;">&#10003; <?php esc_html_e( '設定済み', 'fellow' ); ?></span>
					<?php else : ?>
						<span style="color:#b32d2e;">&#9679; <?php esc_html_e( '未設定', 'fellow' ); ?></span>
					<?php endif; ?>
				</td>
				<td>
					<?php if ( ! $item['done'] ) : ?>
						<?php echo esc_html( $item['note'] ); ?>
						<a href="<?php echo esc_url( $item['link'] ); ?>"><?php echo esc_html( $item['link_label'] ); ?></a>
					<?php endif; ?>
				</td>
			</tr>
		<?php endforeach; ?>
		</tbody>
	</table>
	<?php
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

		<?php fellow_render_setup_status(); ?>
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
