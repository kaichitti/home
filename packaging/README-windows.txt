resq — データ復旧作業ツール（Windows 版）
==========================================

■ 中身
  resq-web.exe   管理画面を起動してブラウザで開きます（ダブルクリックで起動）
  resq.exe       コマンドライン版（PowerShell / コマンドプロンプトから使います）

  初回起動時に「Windows によって PC が保護されました」と表示された場合は、
  「詳細情報」→「実行」を選んでください（署名なしの社内ツールのため）。

■ Windows 版でできること
  - 受付・案件管理・状態の管理（管理画面）
  - 取得済みディスクイメージの登録（resq image-register）
  - 管理情報の残骸からの再構築（S3：FAT / exFAT / NTFS）、サムネイル救出（S7）、統合・ランク付け
  - DMDE / R-Studio の書き出し結果の取り込み（resq ingest）と比較（resq compare）
  - 顧客向け一覧（HTML。ブラウザの「印刷」→「PDF に保存」で PDF にできます）
  - 納品（ハッシュ照合・納品書）、作業データの消去と証明書

■ Windows 版でできないこと（Ubuntu の作業機で行ってください）
  - 媒体からのイメージ化（ddrescue）・SMART 診断・BitLocker 解錠・シャドウコピー（S4）
  - 暗号化作業領域（LUKS）
  - 消去ツール（resq-erase）は消去ステーション（Ubuntu）専用です

■ もっと多くの段を使うには（任意）
  The Sleuth Kit（fls / icat / mmls / fsstat）と TestDisk/PhotoRec の Windows 版を入れ、
  PATH を通すと、S1・S2・S5・S6 も動きます（photorec_win.exe / testdisk_win.exe を自動で使います）。
  入っていない段は「未インストールのため省略」と記録されます。

■ 使い方（PowerShell）
  $env:RESQ_HOME = "D:\resq-data"           # 作業データの置き場所
  .\resq.exe case new --customer "山田 花子" --price-cap 19800
  .\resq.exe consent add R2611-0001 --form-version 2026.11 --id-method 運転免許証
  attrib +R D:\images\disk.img              # イメージは読み取り専用にしてから登録
  .\resq.exe image-register R2611-0001 D:\images\disk.img
  .\resq.exe recover R2611-0001
  .\resq.exe catalog R2611-0001
