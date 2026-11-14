# resq — データ復旧作業ツール

来店型修理店舗の「データ救出」メニュー向けの作業ツール（企画書 v0.3 の `resq`）。
原本には書き込まず、イメージに対して OSS（＋商用）エンジンを多段で当て、結果を統合して
顧客向けの「復旧ファイル一覧」を作るところまでを扱う。

**この版の範囲：最小営業ライン（P0〜P4＋P3b）**

| フェーズ | 内容 | 状態 |
|---|---|---|
| P0 | 基盤（audit / safety / DB / 受付）・フィクスチャ・Claude Code ガードレール | ✅ |
| P1 | 診断（SMART・構造・暗号化検出 → 自社／条件付き／取次／不可） | ✅ |
| P2 | イメージ化（ddrescue・mapfile・中断再開・sha256） | ✅ |
| P3 | 多段復旧 S1（mmls＋TestDisk＋ブートセクタ走査）→ S2（TSK）→ S5（PhotoRec）→ S8（統合・ランク付け） | ✅ |
| P3b | 商用エンジン（DMDE / R-Studio）書き出し結果の取り込み・統合 | ✅ |
| P4 | 一覧化・検証（開けるかの判定、サムネイル、顧客向け HTML/PDF） | ✅ |
| P5〜P11, E1〜E5 | 納品・LUKS 作業領域・管理画面・BitLocker・スマホ・独自サルベージ・消去ツール | 未着手 |

## セットアップ（作業機：Ubuntu LTS）

```bash
sudo apt install gddrescue sleuthkit testdisk smartmontools dosfstools mtools fonts-noto-cjk
pip install -e '.[pdf,dev]'
```

## 作業の流れ

```bash
export RESQ_HOME=/srv/resq-data          # 作業領域（本番は暗号化コンテナ上）

resq case new --customer "山田 花子" --price-cap 19800
resq consent add R2611-0001 --form-version 2026.11 --id-method 運転免許証
resq device add  R2611-0001 --kind HDD --model XXX --serial ABC123 --symptom "誤削除"

resq diagnose <デバイス or イメージ> --case R2611-0001        # 判定と理由
resq image    R2611-0001 <デバイス>                           # 中断しても同じコマンドで再開
resq recover  R2611-0001                                       # S1 → S2 → S5 → S8
resq ingest   R2611-0001 ./dmde_export --engine DMDE           # 任意：商用エンジン結果を統合
resq catalog  R2611-0001                                       # catalog/list.html と list.pdf
resq events   R2611-0001                                       # 実行した全コマンドの記録
```

原本デバイスは、ハードウェアのライトブロッカー経由で接続し、`blockdev --setro` で読み取り専用に
してから使う（`resq` は読み取り専用を確認できないと止まる）。

## 顧客向け一覧のランク

| ランク | 状態 | 見積対象 |
|---|---|---|
| A | 名前・フォルダ付きで開ける | ○ |
| B | 名前なし（カービング）だが開ける | ○ |
| C | 開けるが一部破損 | 希望者に無料同梱 |
| D | サムネイル・低解像度版のみ（P11） | 希望者に無料同梱 |
| U | 種別を自動確認できない（要確認） | 個別判断 |
| X | 中身がゼロ・破損 → **復旧扱いにしない**（一覧に載せず件数のみ表示） | × |

## 安全装置

- 外部コマンドはすべて `audit.run()` 経由。全実行を JSONL と追記専用の `events` テーブルに記録
- `dd`・`mkfs*`・`wipefs`・`fdisk`・`hdparm`・`nvme`・`mount` 等はコードレベルで実行拒否
- `/dev/` を含む引数は、診断・イメージ化の読み取りでのみ明示的に許可
- 書き込み先は案件ディレクトリ内のみ。原本と同じ物理ディスク・容量不足（原本×1.1）は拒否
- SMART 危険は取次、劣化は `--accept-risk` なしではイメージ化しない
- 回復キー・パスコードを保存する列はない。`secrets=` に渡した値はログ・例外から伏字
- 復旧ビルドに消去機能（`resq_erase`）は含めない

## 開発（Claude Code）

- `CLAUDE.md`：開発ルール
- `.claude/settings.json`：deny／ask／allow の権限ルール
- `.claude/hooks/block_devices.py`：実デバイスを参照する Bash コマンドを終了コード 2 でブロック
- **開発機には実ドライブを一切つながない**。テストは `fixtures/` のイメージだけで行う

```bash
./scripts/make_fixtures.sh   # FAT32 フィクスチャ（削除／上書き／クイックフォーマット／パーティション表削除／破損ファイル）
python3 -m pytest -q         # 初回はフィクスチャを自動生成
```

NTFS / exFAT のフィクスチャは `scripts/make_fixtures_root.sh`（root・loop デバイスが必要）。
**開発機では実行せず**、作業機の検証環境で人間が実行する。

## ライセンス

GPL-3.0（`LICENSE`）。TestDisk / PhotoRec 等の OSS は subprocess で呼び出すのみで、コードには取り込んでいない。
