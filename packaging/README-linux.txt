resq — データ復旧作業ツール（Ubuntu 用 単体実行ファイル）
================================================================

対象: Ubuntu 24.04 LTS 以降（x86_64）。Python のインストールは不要です。
ブラウザもネットワークも使いません（作業機はオフラインのまま使えます）。

■ 中身
  resq-gui   デスクトップアプリ（受付・診断・イメージ化・復旧・一覧・納品・消去証明書）
  resq       同じ機能のコマンドライン版

■ 作業機に入れるもの（復旧エンジン本体は OS のパッケージを使います）
  sudo apt install gddrescue sleuthkit testdisk smartmontools cryptsetup-bin \
                   libvshadow-utils libimobiledevice-utils adb fonts-noto-cjk \
                   libpango-1.0-0 libpangoft2-1.0-0 libxcb-cursor0 libegl1
  ※ libxcb-cursor0 / libegl1 は画面表示（Qt）に必要です（デスクトップ版 Ubuntu には通常入っています）。

■ 置き場所
  sudo install -m 755 resq resq-gui /usr/local/bin/
  export RESQ_HOME=/srv/resq-data      # 作業領域（本番は暗号化コンテナ上）

■ 使い方
  resq-gui                              # デスクトップアプリを起動
  resq --help                           # コマンドライン版

■ 注意
  - 顧客の媒体はハードウェアのライトブロッカー経由で接続し、blockdev --setro で読み取り専用にしてから使う
  - この作業機に消去ツール（resq-erase）は入れない
  - 作業機はオフラインで使う
