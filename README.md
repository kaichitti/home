# DetCut — AviUtl向け 決定論的自動編集ツール

動画の音声を解析して、無音カット・テロップ・SE・BGMを配置した **AviUtl ExEdit2 の `.aup2`**（と従来版 AviUtl 1.10＋拡張編集 0.92 の **`.exo`**）を書き出す、個人利用向けのツールです。
設計書「（仮称）DetCut 原案 v1.3」に沿って Python で実装しています。

- **ルールベース**：判定はしきい値・区間演算・テーブル参照だけ。乱数やネットワークは使いません。
- **決定論的**：同じ入力＋同じ設定＋同じバージョンなら、出力がバイト単位で一致します（`detcut verify` で確認可能）。
- **AIは隔離**：文字起こし（faster-whisper）だけが任意のAI段。結果はキャッシュ・ファイル化され、2回目以降は再計算しません。
- **上限なし**：処理はすべてローカル。利用量の制限はありません。
- **非破壊**：元素材は変更せず、AviUtlのプロジェクトだけを作ります（仕上げはAviUtl上で行う下ごしらえ用ツール）。

## 機能

| ID | 機能 | 状態 | 主なファイル |
|---|---|---|---|
| F1 | ジェットカット（無音カット）＋前後の余白 | ✅ | `edit/cutlist.py` |
| F2 | 短い発話（咳・クリック）の除去・近接区間の結合 | ✅ | `analysis/segments.py` |
| F3 | 間の圧縮モード（無音を指定長まで詰める） | ✅ | `edit/cutlist.py` |
| F4 | `.aup2` 出力（テンプレート方式・リップル済み） | ✅ | `writers/aup2.py` |
| F5 | `.exo` 出力（Shift-JIS、テキストは UTF-16LE hex） | ✅ | `writers/exo.py` |
| F6 | レポート（カット理由・測定値・ハッシュ） | ✅ | `report.py`, `*.run.json` |
| F7 | 自動テロップ（単語タイムスタンプ → カット後の時間軸） | ✅ | `edit/telop.py` |
| F8 | 辞書置換（表記ゆれ） | ✅ | `edit/dictionary.py` |
| F9 | 編集点吸着（テロップ・SEの端をカット位置へ） | ✅ | `edit/snap.py` |
| F10 | SE自動挿入（キーワード・カット直後・章頭） | ✅ | `edit/rules_se.py` |
| F11 | BGM自動配置・ダッキング（区間分割＋フェード） | ✅ | `edit/bgm.py` |
| F12 | ズーム・カット割り（拡大率の交互切替・長尺分割） | ✅ | `edit/zoom.py` |
| F13 | GUI（波形とカットのプレビュー、D&D） | ✅ | `gui/app.py` |
| F14 | AviUtl2 汎用プラグイン（.aux2）化 | ❌ 未実装（Phase 4・任意） | — |
| F15 | ショートカットボタン（`.object` / `.exo` を生成） | ✅ | `shortcuts.py` |

## セットアップ（Windows）

1. **Python 3.11 以上**（python.org 版。tkinter が含まれます）と **FFmpeg**（`ffmpeg` / `ffprobe` にPATHを通す）を入れる。
2. このフォルダの `setup_windows.bat` をダブルクリック（`.venv` を作って必要なライブラリを入れ、SE/BGMのサンプルを作ります）。
3. 自動テロップを使うなら：`.venv\Scripts\python.exe -m pip install faster-whisper`
   GUIへのドラッグ&ドロップを使うなら：`.venv\Scripts\python.exe -m pip install tkinterdnd2`

手動の場合：

```
python -m venv .venv
.venv\Scripts\activate
pip install -e .            # detcut コマンドが使えるようになる
```

## 使い方

### いちばん簡単な使い方

- **GUI**：`run_gui.bat` をダブルクリック（動画を `run_gui.bat` にドロップしても開けます）。
  「解析・プレビュー」で波形と残す区間（緑）を確認 → しきい値を調整 → 「書き出し」。
- **ドロップで書き出し**：動画を `run_cut.bat` にドロップすると、`presets/gadget_review.yaml` で `out/` に書き出します。

### コマンド

```
detcut run 動画.mp4 -p presets/gadget_review.yaml            # .aup2 を書き出す
detcut run 動画.mp4 -p presets/gadget_review.yaml -t both    # .aup2 と .exo
detcut run a.mp4 b.mp4 -p presets/gadget_review.yaml         # まとめて処理
detcut run 動画.mp4 -p presets/gadget_review.yaml --set cut.speech_on_db=-40 --set telop.enabled=true

detcut analyze 動画.mp4      # 音量分布を表示し、しきい値を提案（提案値も決定論的）
detcut verify 動画.mp4 -p …  # 2回実行して出力がバイト単位で一致するか確認
detcut transcribe 動画.mp4 -p …   # 文字起こしだけ行い .transcript.json / .srt を出力
detcut shortcut --list -p …       # ショートカットボタンの一覧
detcut shortcut wow -p …          # out/shortcuts/ に .object / .exo を作る
detcut harvest 保存した.aup2      # 実機ファイルのキー名を採取して組み込み表と比較
detcut gui [動画.mp4]
```

`--set` はプリセットの任意の項目を上書きします（リストは番号で指定：`--set se.rules.1.min_cut_ms=800`）。
未知のキーや型の誤りはエラーになります（タイプミスが黙って無視されることはありません）。

### 出力ファイル（`out/`）

| ファイル | 内容 |
|---|---|
| `名前.aup2` | AviUtl2 のプロジェクト（UTF-8・BOMなし・CRLF） |
| `名前.exo` | 従来版のオブジェクトファイル（Shift-JIS・CRLF）。AviUtl2 でも読み込み可 |
| `名前.report.csv` | 残した区間・カットした区間と理由（例：`F1:silence max -52.3dB 640ms`）、テロップ・SE・BGM・ズーム |
| `名前.cutlist.json` | カットリスト（サンプル位置・フレーム位置） |
| `名前.timeline.json` | 中間表現（形式に依存しないタイムライン） |
| `名前.run.json` | 入力・設定・FFmpeg・出力のハッシュ、警告 |
| `名前.transcript.json` / `.srt` | 文字起こしした場合のみ |

### おすすめのテロップ運用（AIを1回だけ使う）

1. `detcut transcribe 動画.mp4 -p …` で文字起こし（faster-whisper：CPU・int8・temperature=0 固定）。
2. 出力された `.transcript.json`（または `.srt`）の誤字を直す。
3. プリセットの `telop.transcript_file` にそのファイルを指定して `detcut run`。

以降はAIを使わないので、テロップも完全に決定論的になります（辞書置換は `dict/gadget_terms.tsv`）。

## AviUtl2 での確認（最初に一度やっておくこと）

`.aup2` の公式仕様書はないため、キー名は実機の保存ファイルの公開情報（AviUtl2 2.00 beta53a 前後）から作った組み込み表を使っています。
お使いの AviUtl2（例：2.1.15）で確実に開けるよう、次の手順を一度行ってください。

1. AviUtl2 で解像度・fpsを設定した**空のプロジェクト**を保存し、`templates/base_1080p.aup2` と差し替える（`project.template_aup2`）。
2. 動画ファイル・音声ファイル・テキストを1つずつ手で置いたプロジェクトを保存し、
   `detcut harvest そのファイル.aup2` で組み込み表との差分を確認 → `project.object_samples_aup2` に指定。
   以降はそのファイルのキー構成で書き出します（キー名が変わっても追従できます）。
3. テロップのスタイルは、AviUtl2 で好みに整えたテキストを `.object`（エイリアス）として保存し、`telop.style_template` に指定。
4. 従来版を使う場合は、テキストを1つ置いてエクスポートした `.exo` を `telop.style_template_exo` に、
   各オブジェクトを置いた `.exo` を `project.object_samples_exo` に指定。
5. 書き出した `.aup2` を AviUtl2 で開き → 保存 → 差分を確認（ラウンドトリップ確認）。

**実機で未確認の点**（このリポジトリの開発環境では AviUtl を動かせないため）：

- AviUtl2 の `文字装飾`（例：縁取り文字）・`文字揃え`（例：中央揃え[中]）の値の表記。`標準文字`・`左寄せ[上]` は確認済みの記録あり。
- BGMフェードの音量トラック表記 `開始,終了,直線移動,0`。不安なら `bgm.duck_fade_ms: 0`（フェードなし）にできます。
- `.object` の `[Object]` に書く `frame=0,長さ-1`。
- `.exo` の構造は拡張編集 0.92 の一般的な形式どおりですが、従来版での読み込みは未確認です。

いずれも上記の採取（harvest／スタイルテンプレート）で実機の値に置き換えられます。

## 設定ファイル（プリセット）

`presets/gadget_review.yaml`（ガジェットレビュー向け・コメント付き）と `presets/podcast_compress.yaml`（間の圧縮）があります。
主な項目：

| セクション | 内容 |
|---|---|
| `project` | 出力形式・解像度・fps（`"30000/1001"` または `"auto"`）・テンプレート・実機サンプル |
| `cut` | `speech_on_db` / `speech_off_db`（ヒステリシス）、`min_silence_ms`、`min_speech_ms`、余白、`merge_gap_ms`、`mode`（jetcut / compress）、手動の `keep_ranges` / `force_cut_ranges` |
| `telop` | 文字起こし設定（`asr`）、1行の文字数・行数、最小表示時間、吸着フレーム数、禁則・区切り文字、スタイル、辞書 |
| `se.rules` | `keyword`（正規表現）/ `after_cut`（長いカットの直後）/ `chapter`。`priority`、`min_interval_ms`、`pick: first / hash` |
| `bgm` | ループ配置、`duck_volume`、`duck_min_gap_ms`、`duck_fade_ms` |
| `zoom` | `min_shot_ms` ごとに `levels` の拡大率を切替、`split_long_ms` で長尺を分割 |
| `chapters` | 章マーカー（CSV `時刻,タイトル`）。SE の `chapter` ルールと章タイトルのテロップに使用 |
| `layers` | 各要素のレイヤー番号（AviUtl画面上の番号＝1始まり） |
| `shortcuts` | ショートカットボタン（テキスト・SE・画像・テンプレート .exo/.object の組み合わせ） |
| `output` | 出力先、`path_map`（WSLで作るときの `/mnt/c/` → `C:\` など）、書き出し後に AviUtl2 で開く設定 |

相対パスは `paths.base_dir`（プリセットからの相対位置）を基準に解決されます。

## 決定論性の仕組み

| 要因 | 対策 |
|---|---|
| 音声解析 | FFmpeg で 48kHz・モノラル・16bit に固定して抽出。10ms窓の**二乗和を整数で計算**し、しきい値との比較だけで判定（対数はレポート表示のみ） |
| 時刻・フレーム | 時刻は整数サンプルで保持し、fps は `Fraction`（30000/1001 など）。フレーム変換は整数の床・天井関数。秒の表記も整数演算で丸める |
| 並び順 | 出力前に `(レイヤー, 開始フレーム, ID)` でソート。JSON は `sort_keys`。Python の `hash()` は使わない（SEの擬似ランダム選択は SHA-256） |
| 設定 | 既定値を補完した正規化済み設定の SHA-256 を記録（出力先・キャッシュ場所は除外） |
| 文字コード | `.aup2` は UTF-8・CRLF、`.exo` は Shift-JIS・CRLF に固定 |
| FFmpeg | `ffmpeg -version` のハッシュを記録。`ffmpeg.expected_version_sha256` と違えば警告 |
| Whisper | モデルファイルのハッシュ照合、temperature 単一値、beam・言語・VAD・スレッド数を固定、CPU int8 推奨、結果をキャッシュ |
| 検証 | `detcut verify`、テスト（別プロセス・別 `PYTHONHASHSEED` で一致、整数合成のWAVによるゴールデンファイル比較） |

## 開発・テスト

```
pip install -e .[dev]
python -m pytest
python tools/make_sample_media.py       # 試用素材（14秒の動画と SE/BGM）を作る
```

- ゴールデンファイル（`tests/golden/`）を更新するとき：`DETCUT_UPDATE_GOLDEN=1 python -m pytest tests/test_pipeline.py -k golden`
- GUIのテストは tkinter と画面がある環境でだけ実行されます（Linux では `xvfb-run python -m pytest`）。

## 参考・ライセンス

- `.aup2` / `.object` の書式は、MIT ライセンスの [aviutl2-alias](https://crates.io/crates/aviutl2-alias)（実機保存ファイルのテスト資産）と
  [aviutl2-mcp](https://github.com/sima05020/aviutl2-mcp)（実機から採取したキー一覧）の公開情報を参考にしました。コードは流用していません。
- ライセンス表記のない ACUTE のコードは流用していません（設計書 12 章のクリーンルーム方針）。
- VOX LAB のプログラム・UI・アセット・文章は参照・流用していません。
- このリポジトリのライセンスは `LICENSE`（GPL-3.0）に従います。
