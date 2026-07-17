# assets/fonts/ — 自己ホストWebフォント置き場

fellow は初期状態ではWebフォントを同梱せず、システムフォントスタックで動作します
(CDN依存を避け、共用サーバーでの表示速度を優先するため)。

## フォントを自己ホストする場合

1. **ライセンス確認**:再配布・Webフォントとしての利用が許可されているフォントのみ使用してください
   (例:SIL OFL のフォント)。確認結果は `LICENSE` に追記します。
2. woff2 ファイルをこのディレクトリに配置します。
3. `assets/css/main.css` の先頭に `@font-face` を追加し、`--font-body` を差し替えます。

```css
@font-face {
	font-family: "MyFont";
	src: url("../fonts/myfont.woff2") format("woff2");
	font-weight: 400;
	font-display: swap;
}

:root {
	--font-body: "MyFont", -apple-system, BlinkMacSystemFont, "Hiragino Sans", Meiryo, sans-serif;
}
```
