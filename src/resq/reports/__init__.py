"""帳票（HTML → PDF）。

PDF は WeasyPrint（Ubuntu 版）で作る。WeasyPrint が使えない環境（Windows 版）では、
Qt（QTextDocument → QPdfWriter）で PDF を作る。ブラウザは使わない。
どちらも無い場合だけ HTML のみを出力する。
"""
from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).parent / "templates"
_QT_APP = None  # Qt で PDF を作るために作ったアプリケーション（作り直さないよう保持）


def env() -> Environment:
    e = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    e.filters["bytes"] = human_bytes
    return e


def human_bytes(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024
    return str(n)


def _weasyprint(out_html: Path, out_pdf: Path) -> bool:
    try:
        from weasyprint import HTML  # type: ignore
    except Exception:  # noqa: BLE001 - 依存（Pango 等）が無い環境
        return False
    HTML(filename=str(out_html), base_url=str(out_html.parent)).write_pdf(str(out_pdf))
    return True


def _qt(out_html: Path, out_pdf: Path) -> bool:
    global _QT_APP
    try:
        from PySide6.QtCore import QMarginsF, QUrl
        from PySide6.QtGui import QGuiApplication, QPageLayout, QPageSize, QPdfWriter, QTextDocument
    except Exception:  # noqa: BLE001
        return False
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 画面を出さずに文字の配置だけ行う
        _QT_APP = QGuiApplication(["resq"])
    doc = QTextDocument()
    doc.setBaseUrl(QUrl.fromLocalFile(str(out_html.parent) + os.sep))
    doc.setHtml(out_html.read_text(encoding="utf-8"))
    writer = QPdfWriter(str(out_pdf))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter)
    writer.setResolution(110)
    doc.setPageSize(writer.pageLayout().paintRectPixels(writer.resolution()).size().toSizeF())
    doc.print_(writer)
    del writer  # ここでファイルが確定する
    return out_pdf.exists()


def render(template: str, out_html: Path, *, pdf: bool = True, **ctx) -> tuple[Path, Path | None]:
    html = env().get_template(template).render(**ctx)
    out_html.write_text(html, encoding="utf-8")
    if not pdf:
        return out_html, None
    out_pdf = out_html.with_suffix(".pdf")
    if _weasyprint(out_html, out_pdf) or _qt(out_html, out_pdf):
        return out_html, out_pdf
    return out_html, None
