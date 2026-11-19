class EraseError(Exception):
    """消去ステーションの業務エラー。"""


class EraseRefused(EraseError):
    """安全装置による拒否（誤消去の防止）。"""
