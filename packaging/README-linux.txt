resq — データ復旧作業ツール（Ubuntu 用 単体実行ファイル）
================================================================

対象: Ubuntu 24.04 LTS 以降（x86_64）。Python のインストールは不要です。

■ 中身
  resq       復旧作業の CLI（受付・診断・イメージ化・復旧・一覧・納品・消去証明書）
  resq-web   管理画面を起動してブラウザで開く（http://127.0.0.1:8765/ のみ）

■ 作業機に入れるもの（復旧エンジン本体は OS のパッケージを使います）
  sudo apt install gddrescue sleuthkit testdisk smartmontools cryptsetup-bin \
                   libvshadow-utils libimobiledevice-utils adb fonts-noto-cjk \
                   libpango-1.0-0 libpangoft2-1.0-0
  ※ libpango が無い場合、帳票は PDF ではなく HTML で出力されます。

■ 置き場所
  sudo install -m 755 resq resq-web /usr/local/bin/
  export RESQ_HOME=/srv/resq-data      # 作業領域（本番は暗号化コンテナ上）

■ 使い方
  resq --help
  resq case new --customer "山田 花子" --price-cap 19800
  resq consent add <案件番号> --form-version 2026.11 --id-method 運転免許証
  resq diagnose <デバイス> --case <案件番号>
  resq image <案件番号> <デバイス>
  resq recover <案件番号>
  resq catalog <案件番号>
  resq-web                              # 管理画面

■ 注意
  - 顧客の媒体はハードウェアのライトブロッカー経由で接続し、blockdev --setro で読み取り専用にしてから使う
  - この作業機に消去ツール（resq-erase）は入れない
  - 作業機はオフラインで使う
