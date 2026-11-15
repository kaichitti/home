"""E4 証明書・台帳・照合ページ（企画書 §8.7）。

- 証明書は「方式・検証内容・結果」を事実として記載する（「絶対に復元できない」とは書かない）
- 表記は「NIST SP 800-88 Rev.2 の区分に沿って実施」までにとどめる（NIST 認証とは書かない）
- PDF の SHA-256 を台帳に記録し、照合ページには証明書番号とハッシュ・発行日だけを載せる
  （社名・シリアル・顧客情報は載せない）
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from resq.reports import human_bytes

from .errors import EraseError
from .ledger import Ledger, now

TEMPLATES = Path(__file__).parent / "templates"
NIST_NOTE = "NIST SP 800-88 Rev.2 の区分（Clear / Purge / Destroy）に沿って実施"
COMPLETION_LABEL = {
    "completed": "ドライブが消去の完了を報告",
    "commands-ok": "消去コマンドが正常終了（全域を読み戻して確認）",
    None: "—",
}


def _env() -> Environment:
    e = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    e.filters["bytes"] = human_bytes
    return e


def _qr_data_uri(text: str) -> str | None:
    try:
        import qrcode  # type: ignore
    except ImportError:
        return None
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _photo_uris(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        f = Path(p)
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png"):
            mime = "png" if f.suffix.lower() == ".png" else "jpeg"
            out.append(f"data:image/{mime};base64," + base64.b64encode(f.read_bytes()).decode())
    return out


def next_number(ledger: Ledger) -> str:
    day = datetime.now().strftime("%Y%m%d")
    n = ledger.one("SELECT COUNT(*) AS n FROM certificates WHERE number LIKE ?", f"E-{day}-%")["n"] + 1
    return f"E-{day}-{n:04d}"


def issue(ledger: Ledger, media_id: int, *, operator: str = "", verify_base_url: str | None = None,
          pdf: bool = True) -> dict:
    media = dict(ledger.one("SELECT * FROM media WHERE id=?", media_id))
    photos = json.loads(media.get("photos") or "[]")
    run = ledger.one("SELECT * FROM runs WHERE media_id=? AND dry_run=0 ORDER BY id DESC LIMIT 1", media_id)
    ver = ledger.one("SELECT * FROM verifications WHERE media_id=? ORDER BY id DESC LIMIT 1", media_id)
    checklist = ledger.one("SELECT * FROM checklists WHERE media_id=?", media_id)

    if media["status"] == "物理破壊済":
        if not photos:
            raise EraseError("物理破壊の証明書には破壊後の写真が必要です")
        category, method = "Destroy", (run["method"] if run else "物理破壊")
    elif media["kind"] == "スマホ":
        from .mobile_checklist import is_complete

        if not is_complete(ledger, media_id):
            raise EraseError("スマホ初期化代行のチェックリストと写真が揃っていません")
        category, method = "Purge", "端末標準の初期化（暗号鍵の破棄）"
        photos = photos + json.loads(checklist["photos"])
    else:
        if ver is None or not ver["passed"]:
            raise EraseError("検証に合格していないため証明書を発行できません")
        if run is None:
            raise EraseError("消去の実行記録がありません")
        category, method = run["category"], run["method"]

    number = next_number(ledger)
    detail = json.loads(ver["detail"]) if ver else {}
    ctx = dict(
        number=number, issued=datetime.now().strftime("%Y-%m-%d %H:%M"), media=media, category=category,
        method=method, run=dict(run) if run else None, ver=dict(ver) if ver else None, detail=detail,
        operator=operator, nist_note=NIST_NOTE,
        completion_label=COMPLETION_LABEL.get(ver["completion"] if ver else None, ver["completion"] if ver else "—"), photos=_photo_uris(photos),
        checklist=json.loads(checklist["items"]) if checklist else None,
        qr=_qr_data_uri(f"{verify_base_url}?no={number}") if verify_base_url else None,
        verify_base_url=verify_base_url,
    )
    out_dir = ledger.home / "certificates"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{number}.html"
    html_path.write_text(_env().get_template("certificate.html").render(**ctx), encoding="utf-8")
    doc = html_path
    if pdf:
        try:
            from weasyprint import HTML  # type: ignore

            doc = html_path.with_suffix(".pdf")
            HTML(filename=str(html_path)).write_pdf(str(doc))
        except ImportError:
            doc = html_path
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()
    ledger.insert("certificates", number=number, media_id=media_id, issued_at=now(), path=str(doc), sha256=digest)
    ledger.event("certificate.issue", f"{number} sha256={digest}", media_id=media_id)
    return {"number": number, "path": doc, "sha256": digest}


def destroy(ledger: Ledger, media_id: int, *, photos: list[str], method: str = "穿孔による物理破壊",
            operator: str = "") -> None:
    if not photos:
        raise EraseError("破壊後の写真を記録してください")
    m = ledger.one("SELECT photos FROM media WHERE id=?", media_id)
    allp = json.loads(m["photos"] or "[]") + photos
    ledger.insert("runs", media_id=media_id, category="Destroy", method=method, commands="[]", dry_run=0,
                  started_at=now(), finished_at=now(), completion="destroyed", operator=operator)
    ledger.execute("UPDATE media SET status='物理破壊済', photos=? WHERE id=?", json.dumps(allp, ensure_ascii=False),
                   media_id)
    ledger.event("destroy", method, media_id=media_id)


def export_verification_list(ledger: Ledger, out_dir: Path) -> tuple[Path, Path]:
    """照合ページ用：証明書番号・発行日・SHA-256 だけを書き出す（個人情報・シリアルは含めない）。"""
    rows = [{"number": r["number"], "issued": r["issued_at"][:10], "sha256": r["sha256"]}
            for r in ledger.all("SELECT number, issued_at, sha256 FROM certificates ORDER BY id")]
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "certificates.json"
    j.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    h = out_dir / "index.html"
    h.write_text(_env().get_template("verify_page.html").render(rows=rows), encoding="utf-8")
    return j, h


def verify_document(ledger: Ledger, number: str, data: bytes) -> bool:
    r = ledger.one("SELECT sha256 FROM certificates WHERE number=?", number)
    return bool(r) and hashlib.sha256(data).hexdigest() == r["sha256"]
