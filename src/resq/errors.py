class ResqError(Exception):
    """resq の業務エラー（利用者に表示してよい内容のみを持つ）。"""


class SafetyError(ResqError):
    """安全装置による停止。原本保護・出力先・容量などの違反。"""


class CommandError(ResqError):
    """外部コマンドの失敗。"""
