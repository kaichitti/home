<?php
/**
 * AdSense の読み込み。
 *
 * AdSense のスクリプト(adsbygoogle.js)は重く、読み込まれた直後に
 * 自動広告がページのあちこちへ枠を差し込む。これが
 * - 初回描画(FCP/LCP)の遅れ
 * - 表示中のレイアウトのずれ(CLS)
 * の大きな原因になる。
 *
 * そこで「読者が最初に操作した(スクロール・タップ・マウス移動・キー入力)
 * 時点で読み込む」遅延読み込みを用意する。ページを開いてすぐ読み始める
 * 読者にはほぼ同じタイミングで広告が出る一方、本文の表示は広告を待たない。
 *
 * パブリッシャーIDが未設定なら何も出力しない。
 * Site Kit などのプラグインでも AdSense のコードを入れている場合は、
 * 二重読み込みにならないようプラグイン側のコード挿入を止めること。
 *
 * @package fellow
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * パブリッシャーIDを正規化する。
 *
 * AdSense の管理画面では「pub-0000…」と「ca-pub-0000…」の両方の表記が
 * 出てくるので、どちらを貼っても通るようにする。
 *
 * @param mixed $value 入力値。
 * @return string 'ca-pub-数字' または空文字。
 */
function fellow_sanitize_adsense_client( $value ) {
	$value = trim( (string) $value );

	if ( preg_match( '/^(?:ca-)?pub-(\d{10,20})$/', $value, $matches ) ) {
		return 'ca-pub-' . $matches[1];
	}

	return '';
}

/**
 * 設定済みのパブリッシャーIDを返す。
 *
 * @return string 未設定なら空文字。
 */
function fellow_adsense_client() {
	return fellow_sanitize_adsense_client( get_theme_mod( 'fellow_adsense_client', '' ) );
}

/**
 * AdSense スクリプトの URL。
 *
 * @param string $client パブリッシャーID。
 * @return string
 */
function fellow_adsense_src( $client ) {
	return add_query_arg(
		'client',
		rawurlencode( $client ),
		'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
	);
}

/**
 * 遅延読み込みしない設定のとき、通常どおり head で読み込む。
 */
function fellow_print_adsense_script() {
	$client = fellow_adsense_client();

	if ( '' === $client || get_theme_mod( 'fellow_adsense_delay', true ) ) {
		return;
	}

	wp_print_script_tag(
		array(
			'async'       => true,
			'src'         => fellow_adsense_src( $client ),
			'crossorigin' => 'anonymous',
		)
	);
}
add_action( 'wp_head', 'fellow_print_adsense_script', 20 );

/**
 * 遅延読み込み用のスクリプトをフッターに出す。
 *
 * 最初の操作で1回だけ adsbygoogle.js を追加する。既に別の経路
 * (プラグイン等)で読み込まれていれば何もしない。
 * 手動配置の広告ユニットが先に (adsbygoogle = window.adsbygoogle || []).push({})
 * を実行していても、読み込み後にまとめて処理されるので問題ない。
 */
function fellow_print_adsense_delay_script() {
	$client = fellow_adsense_client();

	if ( '' === $client || ! get_theme_mod( 'fellow_adsense_delay', true ) ) {
		return;
	}

	$script = sprintf(
		'(function(){var src=%s,events=["scroll","wheel","pointerdown","touchstart","mousemove","keydown"],done=false;' .
		'function load(){if(done){return;}done=true;' .
		'events.forEach(function(e){window.removeEventListener(e,load,{passive:true});});' .
		'if(document.querySelector(\'script[src*="adsbygoogle.js"]\')){return;}' .
		'var s=document.createElement("script");s.async=true;s.crossOrigin="anonymous";s.src=src;document.head.appendChild(s);}' .
		'events.forEach(function(e){window.addEventListener(e,load,{passive:true});});})();',
		wp_json_encode( fellow_adsense_src( $client ) )
	);

	wp_print_inline_script_tag( $script, array( 'id' => 'fellow-adsense-delay' ) );
}
add_action( 'wp_footer', 'fellow_print_adsense_delay_script', 20 );
