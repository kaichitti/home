# assets

SE・BGM などの素材を置くフォルダです（音声ファイルは Git の管理対象外）。

- `se/` … 効果音（プリセットの `se.rules[].file` / `files` / `dir` から参照）
- `bgm/` … BGM（`bgm.file` から参照）

動作確認用のサンプル（wow / whoosh / pop / lofi01）は次のコマンドで作れます（既にあるファイルは上書きしません）。

```
python tools/make_sample_media.py --assets-only
```

収益化する動画では、利用許諾を確認した素材を使ってください。
