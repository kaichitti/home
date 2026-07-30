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
	 * 目次(TOC):本文の h2/h3 から生成し、IntersectionObserver で追従ハイライト。
	 */
	function setupToc() {
		var toc = document.getElementById( 'entry-toc' );
		var source = document.querySelector( '[data-toc-source]' );

		if ( ! toc || ! source ) {
			return;
		}

		var headings = source.querySelectorAll( 'h2, h3' );

		if ( headings.length < 2 ) {
			return; // 見出しが少ない記事では目次を出さない
		}

		var body = toc.querySelector( '.entry-toc__body' );
		var tocToggle = toc.querySelector( '.entry-toc__toggle' );
		var rootList = document.createElement( 'ol' );
		var currentParent = rootList;
		var lastTopItem = null;

		headings.forEach( function ( heading, index ) {
			if ( ! heading.id ) {
				heading.id = 'section-' + ( index + 1 );
			}

			var item = document.createElement( 'li' );
			var link = document.createElement( 'a' );
			link.href = '#' + heading.id;
			link.textContent = heading.textContent;
			item.appendChild( link );

			if ( 'H2' === heading.tagName || ! lastTopItem ) {
				rootList.appendChild( item );
				lastTopItem = item;
				currentParent = null;
			} else {
				if ( ! currentParent ) {
					currentParent = document.createElement( 'ol' );
					lastTopItem.appendChild( currentParent );
				}
				currentParent.appendChild( item );
			}
		} );

		body.appendChild( rootList );
		toc.hidden = false;

		// モバイル:折りたたみトグル
		if ( tocToggle ) {
			tocToggle.addEventListener( 'click', function () {
				var isOpen = toc.classList.toggle( 'is-open' );
				tocToggle.setAttribute( 'aria-expanded', isOpen ? 'true' : 'false' );
			} );
		}

		// スクロール追従(現在地ハイライト)
		if ( 'IntersectionObserver' in window ) {
			var links = body.querySelectorAll( 'a' );
			var linkById = {};

			links.forEach( function ( link ) {
				linkById[ link.hash.slice( 1 ) ] = link;
			} );

			var observer = new IntersectionObserver(
				function ( entries ) {
					entries.forEach( function ( entry ) {
						if ( ! entry.isIntersecting ) {
							return;
						}

						links.forEach( function ( link ) {
							link.classList.remove( 'is-active' );
						} );

						var active = linkById[ entry.target.id ];

						if ( active ) {
							active.classList.add( 'is-active' );
						}
					} );
				},
				{ rootMargin: '0px 0px -70% 0px' }
			);

			headings.forEach( function ( heading ) {
				observer.observe( heading );
			} );
		}
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
