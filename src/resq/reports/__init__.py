"""帳票（HTML → PDF）。WeasyPrint が無い環境では HTML のみ出力する。"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).parent / "templates"


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


def render(template: str, out_html: Path, *, pdf: bool = True, **ctx) -> tuple[Path, Path | None]:
    html = env().get_template(template).render(**ctx)
    out_html.write_text(html, encoding="utf-8")
    out_pdf = None
    if pdf:
        try:
            from weasyprint import HTML  # type: ignore
        except Exception:  # noqa: BLE001 - 依存が無い作業機では HTML のみ
            return out_html, None
        out_pdf = out_html.with_suffix(".pdf")
        HTML(filename=str(out_html), base_url=str(out_html.parent)).write_pdf(str(out_pdf))
    return out_html, out_pdf
