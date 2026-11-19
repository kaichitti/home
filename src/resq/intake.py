"""受付：案件登録・同意・本人確認・所有確認（企画書 §6.1）。"""
from __future__ import annotations

from .cases import Case
from .db import now
from .errors import ResqError

OWNERSHIP_SELF = "本人所有"
OWNERSHIP_CHOICES = (
    OWNERSHIP_SELF,
    "家族所有（所有者の同意書あり）",
    "法人所有（権限者の同意書面あり）",
)
ID_METHODS = ("運転免許証", "マイナンバーカード", "健康保険証", "在留カード", "パスポート", "その他公的書類")

# 受けない依頼（企画書 §1.1 / §6.1）
REFUSED_REQUESTS = {
    "パスコード解除": "ロック解除・回避は請け負いません",
    "ロック回避": "ロック解除・回避は請け負いません",
    "他人のデータ調査": "所有者本人以外のデータ調査は請け負いません",
}


def add_consent(case: Case, *, form_version: str, id_method: str, ownership: str,
                authorization_doc: str | None = None) -> int:
    if id_method not in ID_METHODS:
        raise ResqError(f"本人確認方法が不正です: {id_method}（選択肢: {', '.join(ID_METHODS)}）")
    if ownership not in OWNERSHIP_CHOICES:
        raise ResqError(f"所有確認が不正です: {ownership}（選択肢: {', '.join(OWNERSHIP_CHOICES)}）")
    if ownership != OWNERSHIP_SELF and not authorization_doc:
        raise ResqError("本人所有でない端末は、権限者の同意書面（書類番号等）の記録が必要です")
    cid = case.db.insert("consents", case_id=case.id, form_version=form_version, signed_at=now(),
                         id_method=id_method, ownership=ownership, authorization_doc=authorization_doc)
    case.db.add_event(case.id, "intake.consent", f"form={form_version} id={id_method} own={ownership}", 0)
    return cid


def has_consent(case: Case) -> bool:
    return case.db.one("SELECT 1 FROM consents WHERE case_id=?", case.id) is not None


def require_consent(case: Case) -> None:
    if not has_consent(case):
        raise ResqError(f"案件 {case.id} に同意書の記録がありません。先に `resq consent add` を実行してください。")


def add_device(case: Case, *, kind: str, maker: str | None = None, model: str | None = None,
               serial: str | None = None, capacity: int | None = None, symptom: str | None = None,
               owner: str | None = None, request: str | None = None) -> int:
    if request:
        for key, reason in REFUSED_REQUESTS.items():
            if key in request:
                raise ResqError(f"受付できません: {reason}")
    did = case.db.insert("devices", case_id=case.id, kind=kind, maker=maker, model=model,
                         serial=serial, capacity=capacity, symptom=symptom, owner=owner)
    case.db.add_event(case.id, "intake.device", f"{kind} {maker or ''} {model or ''} sn={serial or ''}", 0)
    return did
