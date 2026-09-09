<?php
/**
 * サイドバー用の目次ウィジェット(スクロール追従エリアに置く想定)。
 *
 * 目次データは inc/toc.php が the_content フィルタで組み立てたものを共有する。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * 目次ウィジェット。
 */
class Fellow_Widget_TOC extends WP_Widget {

	/**
	 * ウィジェットの登録情報。
	 */
	public function __construct() {
		parent::__construct(
			'fellow_toc',
			__( 'fellow 目次', 'fellow' ),
			array(
				'description' => __( '記事詳細ページで、本文の見出しから目次を表示します。見出しが2つ未満の記事や、記事以外のページでは何も表示しません。', 'fellow' ),
				'classname'   => 'widget_fellow_toc',
			)
		);
	}

	/**
	 * フロント側の描画。
	 *
	 * @param array $args     ウィジェットエリアの引数。
	 * @param array $instance ウィジェットの設定値。
	 */
	public function widget( $args, $instance ) {
		if ( ! is_singular( 'post' ) ) {
			return;
		}

		$toc = fellow_render_toc( 'widget' );

		if ( '' === $toc ) {
			return;
		}

		$title = isset( $instance['title'] ) ? $instance['title'] : __( '目次', 'fellow' );
		$title = apply_filters( 'widget_title', $title, $instance, $this->id_base );

		echo $args['before_widget']; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- register_sidebar() で定義した固定のHTML。

		if ( '' !== $title ) {
			echo $args['before_title'] . esc_html( $title ) . $args['after_title']; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- 同上。
		}

		echo $toc; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- fellow_render_toc() 内でエスケープ済み。

		echo $args['after_widget']; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- 同上。
	}

	/**
	 * 管理画面の設定フォーム。
	 *
	 * @param array $instance 現在の設定値。
	 */
	public function form( $instance ) {
		$title = isset( $instance['title'] ) ? $instance['title'] : __( '目次', 'fellow' );
		?>
		<p>
			<label for="<?php echo esc_attr( $this->get_field_id( 'title' ) ); ?>">
				<?php esc_html_e( 'タイトル:', 'fellow' ); ?>
			</label>
			<input
				class="widefat"
				id="<?php echo esc_attr( $this->get_field_id( 'title' ) ); ?>"
				name="<?php echo esc_attr( $this->get_field_name( 'title' ) ); ?>"
				type="text"
				value="<?php echo esc_attr( $title ); ?>"
			>
		</p>
		<p class="description">
			<?php esc_html_e( '「サイドバー(スクロール追従)」に置くと、読みながら目次を参照できます。', 'fellow' ); ?>
		</p>
		<?php
	}

	/**
	 * 設定値の保存。
	 *
	 * @param array $new_instance 新しい値。
	 * @param array $old_instance 以前の値。
	 * @return array
	 */
	public function update( $new_instance, $old_instance ) {
		$instance          = $old_instance;
		$instance['title'] = isset( $new_instance['title'] ) ? sanitize_text_field( $new_instance['title'] ) : '';

		return $instance;
	}
}

/**
 * ウィジェットを登録する。
 */
function fellow_register_widgets() {
	register_widget( 'Fellow_Widget_TOC' );
}
add_action( 'widgets_init', 'fellow_register_widgets' );
