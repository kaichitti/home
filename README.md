# resq — データ復旧作業ツール ／ resq-erase — 完全消去ツール

来店型修理店舗の「データ救出」と「データ消去」メニュー向けの作業ツール（企画書 v0.3）。

- **resq（復旧ビルド）**：原本には書き込まず、イメージに対して OSS（＋商用）エンジンと自作の救出処理を
  多段で当て、結果を統合して顧客向けの「復旧ファイル一覧」→ 納品 → 作業領域の消去まで行う
- **resq-erase（消去ステーション専用ビルド）**：シリアル指定・2 段確認で消去し、自社の復旧手法で
  「何も戻らない」ことを検証してから証明書を出す。**復旧作業機には入れない**

## 実装状況

| フェーズ | 内容 | 状態 |
|---|---|---|
| P0 | 基盤（audit / safety / DB / 受付）・フィクスチャ・Claude Code ガードレール | ✅ |
| P1 | 診断（SMART・構造・暗号化検出 → 自社／条件付き／取次／不可） | ✅ |
| P2 | イメージ化（ddrescue・mapfile・中断再開・sha256） | ✅ |
| P3 | 多段復旧 S1（mmls＋TestDisk＋ブートセクタ走査）→ S2（TSK）→ S5（PhotoRec）→ S8（統合） | ✅ |
| P3b | 商用エンジン（DMDE / R-Studio）書き出し結果の取り込み・統合 | ✅ |
| P4 | 一覧化・検証（開けるかの判定、サムネイル、顧客向け HTML/PDF） | ✅ |
| P5 | 納品（全件ハッシュ照合・納品書）、案件ごとの LUKS2 作業領域、作業領域の消去と証明書 | ✅（LUKS は生成スクリプトを作業機で実行） |
| P6 | デスクトップアプリ（受付・案件・診断・イメージ化・復旧・納品対象の選択・帳票・消去）。ブラウザ・ネットワーク不使用 | ✅ |
| P7 | BitLocker / LUKS の解錠（回復キーは標準入力のみ、保存・記録しない） | ✅（実機は作業機で確認） |
| P8 | スマホ吸い出し（iPhone: idevicebackup2、Android: adb）持ち主の操作確認つき | ✅（実機は作業機で確認） |
| P9 | S3 残骸スキャン（FAT12/16/32・exFAT・NTFS）、商用エンジンとの比較レポート | ✅ |
| P10 | S6 名前の付け直し（カービング結果×残骸の位置照合、FAT32 上位ワード消失対応） | ✅ |
| P11 | S4 シャドウコピー（libvshadow）、S7 サムネイルキャッシュ（thumbcache / Thumbs.db） | ✅（VSS 実物は作業機で確認） |
| E1〜E5 | 媒体識別・方式選択、実行ラッパ、検証、証明書・照合ページ、スマホ初期化代行 | ✅（消去の実行は消去ステーションのみ） |

## セットアップ

### 復旧作業機（Ubuntu LTS・オフライン）

```bash
sudo apt install gddrescue sleuthkit testdisk smartmontools cryptsetup-bin libvshadow-utils \
                 libimobiledevice-utils adb fonts-noto-cjk
pip install -e '.[pdf,thumbs]'
```

### 消去ステーション（別の PC）

```bash
sudo apt install smartmontools hdparm nvme-cli nwipe sg3-utils sleuthkit testdisk fonts-noto-cjk
./scripts/build_erase_station.sh            # dist/resq_erase-*.whl（resq_erase＋検証用の復旧エンジン）
pip install dist/resq_erase-*.whl
echo ST-01 | sudo tee /etc/resq-erase-station && export RESQ_ERASE_STATION_ID=ST-01
```

マーカーファイルと環境変数が一致しないマシンでは、消去コマンドは**決して実行されない**（開発機・復旧機を含む）。

## 実行ファイル（配布用）

Python を入れずに使える単体の実行ファイルを用意している（PyInstaller）。

| 配布物 | 中身 | 使う場所 |
|---|---|---|
| `resq-<版>-linux-x86_64.tar.gz` | `resq-gui`（デスクトップアプリ）・`resq`（CLI） | 復旧作業機（Ubuntu 24.04 以降）。全機能 |
| `resq-erase-<版>-linux-x86_64.tar.gz` | `resq-erase-gui`・`resq-erase` | 消去ステーション専用。**復旧作業機には入れない** |
| `resq-<版>-windows-x64.zip` | `resq-gui.exe`・`resq.exe` | Windows。案件管理・残骸スキャン・一覧（PDF）・納品・商用エンジン取り込み等（イメージ化・解錠・消去は不可） |

- ビルド：Linux は `./scripts/build_exe.sh`、Windows は `.\scripts\build_exe.ps1`（どちらもビルド後にフィクスチャで動作確認）
- GitHub Actions（`.github/workflows/build.yml`）でテスト→Linux / Windows のビルドと動作確認を行い、成果物を保存する。
  `v*` タグを付けるとリリースに添付する
- 外部ツール（ddrescue・TSK・PhotoRec 等）は実行ファイルに含めない。OS のパッケージを入れる（各配布物の README を参照）
- Windows 版は TSK / TestDisk の Windows 版を PATH に置くと S1・S2・S5・S6 も動く。無い段は「未インストールのため省略」と記録される

## 復旧の流れ（resq）

```bash
export RESQ_HOME=/srv/resq-data
resq case new --customer "山田 花子" --price-cap 19800 --retention-until 2026-12-31
resq consent add R2611-0001 --form-version 2026.11 --id-method 運転免許証
resq device add  R2611-0001 --kind HDD --model XXX --serial ABC123 --symptom "誤削除"
resq workspace create R2611-0001 --size 500G   # 暗号化作業領域の作成スクリプト（root で実行）

resq diagnose <デバイス or イメージ> --case R2611-0001
resq image    R2611-0001 <デバイス>             # 中断しても同じコマンドで再開
resq unlock   R2611-0001 --image 1               # BitLocker の場合（回復キーは画面入力のみ）
resq recover  R2611-0001                          # S1→S2→S3→S4→S5→S6→S7→S8
resq ingest   R2611-0001 ./dmde_export --engine DMDE
resq compare  R2611-0001 S3 COM1                  # 自作スキャナと商用エンジンの件数・差分
resq catalog  R2611-0001                          # 顧客向け一覧（PDF）
resq select   R2611-0001 --ranks A,B
resq deliver  R2611-0001 /media/usb               # 全件 SHA-256 照合・納品書
resq wipe     R2611-0001 --plan / --confirm       # 作業領域の消去と消去証明書
resq-gui                                          # デスクトップアプリ（同じ操作を画面で）
resq export-serials serials.json                  # 消去ステーションへ渡す「消去禁止シリアル」
```

スマホ: `resq mobile ios <案件> <UDID>` ／ `resq mobile android <案件> <シリアル>`（持ち主の操作確認を対話で記録）

### サルベージ・パイプライン

| 段 | 手法 | 実装 |
|---|---|---|
| S1 | パーティション探索 | mmls ＋ TestDisk（analyze/search のみ）＋ 自前のブートセクタ走査 |
| S2 | 削除エントリ | TSK（fls / icat）。孤立エントリは「…/」付きで部分パスを保持 |
| S3 | 管理情報の残骸から再構築 | 自作。FAT（LFN・削除で消えた先頭文字の復元）／exFAT（削除エントリセット）／NTFS（MFT・ランリスト） |
| S4 | シャドウコピー | libvshadow で展開し TSK |
| S5 | カービング | PhotoRec（report.xml の位置情報を記録） |
| S6 | 名前の付け直し | 自作。S5 の位置 × S3 のデータ位置（FAT32 上位ワード消失も照合） |
| S7 | サムネイル | 自作。thumbcache_*.db（Vista〜11）・Thumbs.db → ランク D |
| S8 | 統合・検証 | SHA-256 で束ね、開ける・フォルダ付き・パス情報が多い版を採用 |

### 顧客向け一覧のランク

| ランク | 状態 | 見積対象 |
|---|---|---|
| A | 名前（・フォルダ）付きで開ける | ○ |
| B | 名前なし（カービング）だが開ける | ○ |
| C | 開けるが一部破損 | 希望者に無料同梱 |
| D | サムネイル・低解像度版のみ | 希望者に無料同梱 |
| U | 種別を自動確認できない（要確認） | 個別判断 |
| X | 中身がゼロ・破損・拡張子と中身が不一致 → **復旧扱いにしない** | × |

## 消去の流れ（resq-erase、消去ステーション）

```bash
resq-erase sync-blocked serials.json      # 復旧案件の媒体を消去禁止に
resq-erase register --serial WD-WCC4E1234567 --kind HDD --requester 山田商事 --origin 法人 \
                    --consent-doc 承諾書No.7 --location 棚A-1 --photo label.jpg
resq-erase inventory WD-WCC4E1234567 ...  # 施錠保管の台数照合
resq-erase probe WD-WCC4E1234567           # 方式選択（Clear / Purge / Destroy）
resq-erase erase WD-WCC4E1234567           # ドライラン（既定）
resq-erase erase WD-WCC4E1234567 --execute # シリアル下 4 桁の入力で本実行
resq-erase verify WD-WCC4E1234567 --target /dev/sdX   # 読み戻し＋復旧試行（0 件で合格）
resq-erase certificate WD-WCC4E1234567 --verify-url https://example.jp/verify
resq-erase export-verify ./public          # 照合ページ（番号・発行日・SHA-256 のみ）
resq-erase validation record / report      # 月次の妥当性確認と型番別の実績表
resq-erase-gui                             # デスクトップアプリ（スマホ初期化代行のチェックリスト等）
```

方式選択（企画書 §8.3）：HDD は ATA Sanitize（なければ nwipe ゼロ 1 回＋全域検証）、SATA SSD は
Sanitize（Crypto Scramble / Block Erase）または Enhanced Secure Erase、NVMe は Sanitize / Format（SES=2）。
**SSD に上書きは使わない**。USB 変換経由の SSD は「本体スロットに直結」と返して実行しない。
frozen・HPA は解消するまで実行しない。証明書は「NIST SP 800-88 Rev.2 の区分に沿って実施」までの表記にとどめる。

## 安全装置

- 外部コマンドはすべて `audit.run()`（消去側は `resq_erase.exec.run()`）経由で記録。操作ログは追記専用
- 復旧ビルドでは `dd`・`mkfs*`・`wipefs`・`hdparm`・`nvme`・`mount` 等をコードレベルで実行拒否
- `/dev/` を含む引数は、診断・イメージ化・解錠の読み取りでのみ明示的に許可
- 書き込み先は案件ディレクトリ内のみ。原本と同じ物理ディスク・容量不足は拒否
- 回復キー・パスコードの列はない。キーは標準入力でのみ渡し、ログ・例外から伏字
- 画面はデスクトップアプリ（Qt）。ブラウザもネットワークも使わない（通信部品を読み込まないことをテストで確認）
- 復旧ビルドのホイールに `resq_erase` は含まれない（テストで確認）

## 開発（Claude Code）

- `CLAUDE.md`：開発ルール ／ `.claude/settings.json`：権限ルール ／ `.claude/hooks/block_devices.py`：実デバイス参照のブロック
- **開発機には実ドライブを一切つながない**。テストは `fixtures/` のイメージだけで行う

```bash
./scripts/make_fixtures.sh   # FAT32 / NTFS / exFAT のフィクスチャ（root 不要）
python3 -m pytest -q         # 初回はフィクスチャを自動生成
```

フィクスチャ：削除のみ／一部上書き／クイックフォーマット／パーティション表削除／入れ子フォルダ＋LFN の
クイックフォーマット／FAT32 上位ワード消失／NTFS 再フォーマット／exFAT 削除／破損ファイル。
`scripts/make_fixtures_root.sh`（mount を使う NTFS / exFAT）は作業機の検証環境で人間が実行する。

### 作業機でしか確認できないこと

開発機には実デバイスがないため、次は作業機・消去ステーションで実機確認が必要：
ライトブロッカー越しの `blockdev --getro`・同一物理ディスク判定、ddrescue の不良セクタ処理、
cryptsetup による BitLocker 解錠、LUKS 作業領域の作成・破棄、iPhone / Android の実機吸い出し、
Windows 実機ディスクのシャドウコピー、各消去命令の実行と完了ステータス（自社のジャンクドライブで）。

## ライセンス

GPL-3.0（`LICENSE`）。TestDisk / PhotoRec 等の OSS は subprocess で呼び出すのみで、コードには取り込んでいない。
