"""resq-erase — 完全消去ツール（消去ステーション専用ビルド。企画書 §8）。

復旧作業機には入れない。復旧ツール（resq）はこのパッケージを import しない。
逆方向（消去後の検証で resq.recover を読み取り専用で呼ぶ）は可。

  E1 probe.py       媒体の識別と方式選択（NIST SP 800-88 Rev.2 の区分）
  E2 run.py         実行ラッパ（既定はドライラン。シリアル指定・2 段確認・拒否リスト）
  E3 verify.py      検証（完了ステータス・読み戻し・復旧試行）と月次の妥当性確認
  E4 certificate.py 証明書・台帳・照合ページ
  E5 mobile_checklist.py / web.py  スマホ初期化代行のチェックリストと管理画面
"""

__version__ = "0.1.0"
