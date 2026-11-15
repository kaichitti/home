resq-erase — 完全消去ツール（消去ステーション専用・Ubuntu 用 単体実行ファイル）
================================================================================

★ 復旧作業機には入れないでください。消去ステーション（別の PC）専用です。

対象: Ubuntu 24.04 LTS 以降（x86_64）

■ 消去ステーションに入れるもの
  sudo apt install smartmontools hdparm nvme-cli nwipe sg3-utils sleuthkit testdisk \
                   fonts-noto-cjk libpango-1.0-0 libpangoft2-1.0-0
  sudo install -m 755 resq-erase /usr/local/bin/

■ 消去ステーションとしての登録（これが無いマシンでは消去コマンドは決して実行されません）
  echo ST-01 | sudo tee /etc/resq-erase-station
  export RESQ_ERASE_STATION_ID=ST-01
  export RESQ_ERASE_HOME=/srv/resq-erase

■ 使い方
  resq-erase sync-blocked serials.json        # 復旧側（resq export-serials）の消去禁止シリアル
  resq-erase register --serial <シリアル> --kind HDD --requester <依頼者> --origin 法人 --consent-doc <承諾書>
  resq-erase probe <シリアル>                  # 方式選択
  resq-erase erase <シリアル>                  # ドライラン（既定）
  resq-erase erase <シリアル> --execute        # 本実行（シリアル下 4 桁の入力が必要）
  resq-erase verify <シリアル> --target <デバイス>
  resq-erase certificate <シリアル>
  resq-erase web                              # スマホ初期化代行のチェックリスト（127.0.0.1:8766）

■ 注意
  - SSD は本体の SATA / M.2 スロットに直結する（USB 変換経由では実行しません）
  - 初めて使う型番は、自社のジャンクドライブで妥当性確認（resq-erase validation record）をしてから
