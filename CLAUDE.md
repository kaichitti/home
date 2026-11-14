# resq — データ復旧作業ツール

## これは何か
来店型修理店でのデータ復旧作業を、安全な手順で行うための CLI＋ローカル管理画面。
復旧エンジンは OSS（GNU ddrescue, The Sleuth Kit, TestDisk/PhotoRec, cryptsetup,
libimobiledevice, adb）を subprocess で呼び出す。エンジンは自作しない。
自作するのは「多段で当てて統合する仕組み」（src/resq/recover/）と独自の救出処理。

## 絶対ルール
- 実デバイス（/dev/sd*, /dev/nvme*, /dev/mmcblk*, /dev/disk*）に対するコマンドを実行しない。
  開発・テストは fixtures/ のイメージファイルのみを使う。
- sudo を使わない。root が必要な処理はコードとして書くだけで、実行は人間が作業機で行う。
- 原本に書き込む可能性のある処理（dd の of=, mkfs, fdisk, wipefs, blkdiscard 等）を
  作業フローに入れない。audit.FORBIDDEN_PROGRAMS がコードレベルでも拒否する。
- 外部コマンドは必ず audit.run() 経由で呼ぶ。直接 subprocess を呼ばない。
- 書き込み先は必ず safety.assert_writable_target() を通す。
  外部由来のファイル名を連結するときは safety.safe_join() を使う。
- 回復キー・パスコードを DB・ログ・ファイル・例外メッセージに出さない
  （audit.run(secrets=[...]) で伏字にする。DB に列を作らない）。
- 顧客データを外部送信するコード（HTTP 通信、クラウド SDK）を入れない。
- 管理画面は 127.0.0.1 以外で待ち受けない。
- 消去機能（src/resq_erase/）は消去ステーション向けビルドにのみ含める。
  resq（復旧）側から resq_erase を import できない構成にする（pyproject で除外済み）。
  逆方向（消去の検証で resq.recover を読み取り専用で呼ぶ）は可。
- 消去系のテストはドライラン（実行予定コマンドの生成）までに限る。
- 上書きされたデータを「戻ったように見せない」。中身がゼロ・破損のファイルはランク X（ランク外）。

## 技術スタック
Python 3.12+ / Typer / Rich / SQLite / Jinja2 / WeasyPrint / Pillow / pytest
（FastAPI は P6 で追加）

## 構成
- src/resq/audit.py      外部コマンドの唯一の窓口・監査ログ
- src/resq/safety.py     読み取り専用確認・出力先・容量・同一ディスク判定
- src/resq/db.py         SQLite（events は追記専用）
- src/resq/cases.py      案件・状態遷移
- src/resq/intake.py     同意・本人確認・所有確認（P0）
- src/resq/diagnose.py   診断と判定（P1）
- src/resq/image.py      ddrescue イメージ化（P2）
- src/resq/recover/      S1 partitions / S2 tsk / S5 photorec / ingest(P3b) / S8 merge / pipeline
- src/resq/validate.py   種別判定・開けるかの検証
- src/resq/catalog.py    顧客向け一覧（P4）

## コマンド
- テスト: `pytest -q`（初回はフィクスチャを自動生成）
- フィクスチャ生成: `./scripts/make_fixtures.sh`（root 不要の範囲のみ）
- NTFS/exFAT フィクスチャ: `scripts/make_fixtures_root.sh`（作業機で人間が実行。開発機では実行しない）

## 進め方
- 1 フェーズずつ進める。テストを先に書き、実装は後。
- 完了条件は「フィクスチャから削除したファイルが sha256 一致で戻ること」を基本にする。
- 外部コマンドのオプションは推測しない。man / --help の出力を確認してから使う。
- 不明点は推測で埋めず、TODO として残して質問する。
