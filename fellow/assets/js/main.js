/**
 * fellow main.js
 *
 * ハンバーガーメニュー / 検索トグル / 目次(TOC)生成とスクロール追従 /
 * URLコピー。1ファイルに集約し defer で読み込む。
 * 各機能は対象要素の有無で発火を判定するため、ページ種別ごとの分岐は不要。
 */
( function () {
	'use strict';

	// .js クラスは head 内の同期スクリプト(fellow_print_js_detection)で
	// 既に付与済み。ここで付けると初回描画がチラつくため触らない。

	document.addEventListener( 'DOMContentLoaded', function () {
		setupNavToggle();
		setupSubmenuToggles();
		setupSearchToggle();
		setupToc();
		setupTabs();
		setupCopyButtons();
	} );

	/**
	 * ハンバーガーメニュー。
	 */
	function setupNavToggle() {
		var toggle = document.querySelector( '.nav-toggle' );
		var nav = document.getElementById( 'global-nav' );

		if ( ! toggle || ! nav ) {
			return;
		}

		toggle.addEventListener( 'click', function () {
			var isOpen = nav.classList.toggle( 'open' );
			toggle.setAttribute( 'aria-expanded', isOpen ? 'true' : 'false' );
		} );
	}

	/**
	 * モバイル用サブメニュー開閉(Fellow_Walker_Nav が出力するボタン)。
	 */
	function setupSubmenuToggles() {
		var toggles = document.querySelectorAll( '.global-nav__toggle' );

		toggles.forEach( function ( toggle ) {
			toggle.addEventListener( 'click', function () {
				var item = toggle.closest( '.global-nav__item' );
				var isOpen = item.classList.toggle( 'open' );
				toggle.setAttribute( 'aria-expanded', isOpen ? 'true' : 'false' );
			} );
		} );
	}

	/**
	 * ヘッダー検索トグル。Escapeキーと外側クリックで閉じる。
	 */
	function setupSearchToggle() {
		var wrap = document.getElementById( 'header-search' );

		if ( ! wrap ) {
			return;
		}

		var toggle = wrap.querySelector( '.header-search__toggle' );
		var field = wrap.querySelector( '.search-form__field' );

		function close() {
			wrap.classList.remove( 'open' );
			toggle.setAttribute( 'aria-expanded', 'false' );
		}

		toggle.addEventListener( 'click', function () {
			var isOpen = wrap.classList.toggle( 'open' );
			toggle.setAttribute( 'aria-expanded', isOpen ? 'true' : 'false' );

			if ( isOpen && field ) {
				field.focus();
			}
		} );

		document.addEventListener( 'keydown', function ( event ) {
			if ( 'Escape' === event.key && wrap.classList.contains( 'open' ) ) {
				close();
				toggle.focus();
			}
		} );

		document.addEventListener( 'click', function ( event ) {
			if ( wrap.classList.contains( 'open' ) && ! wrap.contains( event.target ) ) {
				close();
			}
		} );
	}

	/**
	 * タブ切り替え。
	 *
	 * ブロックパターンで作られた「見出し+中身のグループが縦に並んだもの」を、
	 * JSが動く環境でだけタブUIに組み替える(段階的強化)。
	 * JSが無ければ見出し付きの段落が順に並ぶだけなので、内容は全部読める。
	 */
	function setupTabs() {
		var groups = document.querySelectorAll( '.fellow-tabs' );

		groups.forEach( function ( group, groupIndex ) {
			/*
			 * WordPress はグループブロックの中身を .wp-block-group__inner-container で
			 * 包むため、パネルは直接の子ではなく孫になる。子孫から拾ったうえで、
			 * 入れ子のタブを取り違えないよう closest で自分のものだけに絞る。
			 */
			var panels = Array.prototype.filter.call(
				group.querySelectorAll( '.fellow-tabs__panel' ),
				function ( panel ) {
					return panel.closest( '.fellow-tabs' ) === group;
				}
			);

			if ( panels.length < 2 ) {
				return;
			}

			var list = document.createElement( 'div' );
			list.className = 'fellow-tabs__list';
			list.setAttribute( 'role', 'tablist' );

			var tabs = [];

			panels.forEach( function ( panel, index ) {
				var label = panel.querySelector( '.fellow-tabs__label' );
				var name = label ? label.textContent.trim() : String( index + 1 );
				var id = 'fellow-tab-' + groupIndex + '-' + index;

				var tab = document.createElement( 'button' );
				tab.type = 'button';
				tab.className = 'fellow-tabs__tab';
				tab.textContent = name;
				tab.id = id;
				tab.setAttribute( 'role', 'tab' );
				tab.setAttribute( 'aria-selected', index === 0 ? 'true' : 'false' );
				tab.setAttribute( 'aria-controls', id + '-panel' );
				tab.tabIndex = index === 0 ? 0 : -1;

				panel.id = id + '-panel';
				panel.setAttribute( 'role', 'tabpanel' );
				panel.setAttribute( 'aria-labelledby', id );
				panel.hidden = index !== 0;

				list.appendChild( tab );
				tabs.push( tab );
			} );

			function select( index ) {
				tabs.forEach( function ( tab, i ) {
					var on = i === index;
					tab.setAttribute( 'aria-selected', on ? 'true' : 'false' );
					tab.tabIndex = on ? 0 : -1;
					panels[ i ].hidden = ! on;
				} );
			}

			tabs.forEach( function ( tab, index ) {
				tab.addEventListener( 'click', function () {
					select( index );
				} );

				// 左右キーでの移動(WAI-ARIA のタブパターン)
				tab.addEventListener( 'keydown', function ( event ) {
					var next = null;

					if ( 'ArrowRight' === event.key ) {
						next = ( index + 1 ) % tabs.length;
					} else if ( 'ArrowLeft' === event.key ) {
						next = ( index - 1 + tabs.length ) % tabs.length;
					}

					if ( null !== next ) {
						event.preventDefault();
						select( next );
						tabs[ next ].focus();
					}
				} );
			} );

			// パネルと同じ階層(inner-container の中)へ差し込む
			panels[ 0 ].parentNode.insertBefore( list, panels[ 0 ] );
			group.classList.add( 'is-tabbed' );
		} );
	}

	/**
	 * 目次(TOC)。
	 *
	 * 目次そのものは inc/toc.php がサーバー側で出力済み(JS無効でも動く)。
	 * ここで足すのは「本文内の目次の折りたたみ」と
	 * 「読んでいる位置のハイライト」だけ。
	 */
	function setupToc() {
		var tocs = document.querySelectorAll( '.fellow-toc' );

		if ( ! tocs.length ) {
			return;
		}

		// 本文内の目次:モバイルで畳めるようにする
		var inline = document.querySelector( '.fellow-toc--inline' );

		if ( inline ) {
			var toggle = inline.querySelector( '.fellow-toc__toggle' );

			if ( toggle ) {
				// 広い画面では開いた状態から始める
				if ( window.matchMedia( '(min-width: 900px)' ).matches ) {
					toggle.setAttribute( 'aria-expanded', 'true' );
				}

				toggle.addEventListener( 'click', function () {
					var expanded = 'true' === toggle.getAttribute( 'aria-expanded' );
					toggle.setAttribute( 'aria-expanded', expanded ? 'false' : 'true' );
				} );
			}
		}

		// 現在地のハイライト(全ての目次に同時に反映する)
		if ( ! ( 'IntersectionObserver' in window ) ) {
			return;
		}

		var links = document.querySelectorAll( '.fellow-toc a[href^="#"]' );

		if ( ! links.length ) {
			return;
		}

		var linksById = {};
		var headings = [];

		links.forEach( function ( link ) {
			var id = decodeURIComponent( link.hash.slice( 1 ) );

			if ( ! id ) {
				return;
			}

			if ( ! linksById[ id ] ) {
				linksById[ id ] = [];
				var heading = document.getElementById( id );

				if ( heading ) {
					headings.push( heading );
				}
			}

			linksById[ id ].push( link );
		} );

		function setActive( id ) {
			links.forEach( function ( link ) {
				link.classList.remove( 'is-active' );
			} );

			( linksById[ id ] || [] ).forEach( function ( link ) {
				link.classList.add( 'is-active' );
			} );
		}

		var observer = new IntersectionObserver(
			function ( entries ) {
				entries.forEach( function ( entry ) {
					if ( entry.isIntersecting ) {
						setActive( entry.target.id );
					}
				} );
			},
			{ rootMargin: '0px 0px -70% 0px' }
		);

		headings.forEach( function ( heading ) {
			observer.observe( heading );
		} );
	}

	/**
	 * 「URLをコピー」ボタン。
	 */
	function setupCopyButtons() {
		var buttons = document.querySelectorAll( '[data-copy-url]' );

		if ( ! buttons.length || ! navigator.clipboard ) {
			return;
		}

		buttons.forEach( function ( button ) {
			button.addEventListener( 'click', function () {
				navigator.clipboard
					.writeText( button.getAttribute( 'data-copy-url' ) )
					.then( function () {
						button.classList.add( 'is-copied' );

						window.setTimeout( function () {
							button.classList.remove( 'is-copied' );
						}, 1500 );
					} );
			} );
		} );
	}
} )();
