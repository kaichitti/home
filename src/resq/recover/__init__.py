"""多段復旧（サルベージ・パイプライン、企画書 §3.8）。

どの段もイメージを読むだけで、書き込まない。結果は案件ディレクトリの
stages/img<イメージID>/<段>/ に出し、manifest.json に候補を列挙する。
S8（merge）が全段の manifest を統合する。
"""

STAGES = {
    "S1": "パーティション探索",
    "S2": "削除エントリ（TSK）",
    "S3": "管理情報の残骸から再構築",
    "S4": "シャドウコピー（VSS）",
    "S5": "カービング（PhotoRec）",
    "S6": "名前の付け直し",
    "S7": "サムネイルキャッシュ",
    "COM": "商用エンジン取り込み",
    "MOB": "スマホ吸い出し",
    "S8": "統合・検証",
}


def stage_label(stage: str) -> str:
    key = "COM" if stage.startswith("COM") else "MOB" if stage.startswith("MOB") else stage
    return STAGES.get(key, stage)
