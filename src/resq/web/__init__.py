"""受付・案件管理画面（P6）。FastAPI + Jinja2。

- 127.0.0.1 以外では待ち受けない（serve() が拒否する）
- Host ヘッダが 127.0.0.1 / localhost 以外の要求は拒否（DNS リバインディング対策）
- POST は Origin が自分自身のときだけ受け付ける
- 顧客データを外部に送信する処理は持たない
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from .. import catalog as catalog_mod
from .. import deliver as deliver_mod
from .. import diagnose as diagnose_mod
from .. import intake, reports
from ..cases import STATES, TRANSITIONS, create_case, get_case, open_workspace
from ..config import Workspace
from ..errors import ResqError, SafetyError
from ..recover import stage_label

LISTEN_HOST = "127.0.0.1"
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
TEMPLATES = Path(__file__).parent / "templates"


class LocalOnly(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ALLOWED_HOSTS:
            return PlainTextResponse("forbidden host", status_code=403)
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin:
                o = origin.split("://", 1)[-1].rsplit(":", 1)[0]
                if o not in ALLOWED_HOSTS:
                    return PlainTextResponse("forbidden origin", status_code=403)
        return await call_next(request)


def create_app(ws: Workspace | None = None) -> FastAPI:
    app = FastAPI(title="resq 管理画面", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalOnly)
    tpl = Jinja2Templates(directory=str(TEMPLATES))
    tpl.env.filters["bytes"] = reports.human_bytes

    def db_ws():
        return open_workspace(ws)

    def page(request: Request, name: str, **ctx):
        return tpl.TemplateResponse(request, name, ctx)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        w, db = db_ws()
        rows = db.all("SELECT * FROM cases ORDER BY id DESC")
        return page(request, "index.html", cases=rows, states=STATES)

    @app.get("/cases/new", response_class=HTMLResponse)
    def new_form(request: Request):
        return page(request, "case_new.html", id_methods=intake.ID_METHODS, ownerships=intake.OWNERSHIP_CHOICES,
                    error=None, form={})

    @app.post("/cases/new")
    def new_case(request: Request, customer: str = Form(...), contact: str = Form(""),
                 price_cap: str = Form(""), retention_until: str = Form(""), form_version: str = Form(...),
                 id_method: str = Form(...), ownership: str = Form(...), authorization_doc: str = Form(""),
                 kind: str = Form(""), maker: str = Form(""), model: str = Form(""), serial: str = Form(""),
                 symptom: str = Form(""), request_text: str = Form("")):
        w, db = db_ws()
        form = dict(customer=customer, contact=contact, price_cap=price_cap, retention_until=retention_until,
                    form_version=form_version, id_method=id_method, ownership=ownership,
                    authorization_doc=authorization_doc, kind=kind, maker=maker, model=model, serial=serial,
                    symptom=symptom, request_text=request_text)
        try:
            # 先に検証してから登録（途中で失敗して半端な案件が残らないように）
            if ownership != intake.OWNERSHIP_SELF and not authorization_doc:
                raise ResqError("本人所有でない端末は、権限者の同意書面（書類番号等）の記録が必要です")
            for key, reason in intake.REFUSED_REQUESTS.items():
                if key in request_text:
                    raise ResqError(f"受付できません: {reason}")
            cap = int(price_cap.replace(",", "")) if price_cap.strip() else None
            c = create_case(w, db, customer=customer, contact=contact or None, price_cap=cap,
                            retention_until=retention_until or None)
            intake.add_consent(c, form_version=form_version, id_method=id_method, ownership=ownership,
                               authorization_doc=authorization_doc or None)
            if kind:
                intake.add_device(c, kind=kind, maker=maker or None, model=model or None, serial=serial or None,
                                  symptom=symptom or None, request=request_text or None)
        except (ResqError, ValueError) as e:
            return tpl.TemplateResponse(request, "case_new.html",
                                        dict(id_methods=intake.ID_METHODS, ownerships=intake.OWNERSHIP_CHOICES,
                                             error=str(e), form=form), status_code=400)
        return RedirectResponse(f"/cases/{c.id}", status_code=303)

    def _case(case_id: str):
        w, db = db_ws()
        try:
            return get_case(w, db, case_id)
        except ResqError:
            raise HTTPException(404, "案件が見つかりません") from None

    @app.get("/cases/{case_id}", response_class=HTMLResponse)
    def detail(request: Request, case_id: str):
        c = _case(case_id)
        db = c.db
        ranks = {r["rank"]: (r["n"], r["sel"]) for r in db.all(
            "SELECT rank, COUNT(*) AS n, SUM(selected) AS sel FROM recovered_files WHERE case_id=? GROUP BY rank",
            c.id)}
        diag = diagnose_mod.latest(c)
        stages = [dict(r, label=stage_label(r["stage"])) for r in db.all(
            "SELECT * FROM stage_runs WHERE case_id=? ORDER BY id", c.id)]
        return page(request, "case_detail.html", case=c.row, devices=db.all("SELECT * FROM devices WHERE case_id=?", c.id),
                    consents=db.all("SELECT * FROM consents WHERE case_id=?", c.id), diag=diag,
                    images=db.all("SELECT * FROM images WHERE case_id=?", c.id), stages=stages, ranks=ranks,
                    transitions=TRANSITIONS[c.row["status"]], downloads=_downloads(c),
                    deliveries=db.all("SELECT * FROM deliveries WHERE case_id=?", c.id),
                    certs=db.all("SELECT * FROM certificates WHERE case_id=?", c.id),
                    events=db.all("SELECT * FROM events WHERE case_id=? ORDER BY id DESC LIMIT 30", c.id),
                    error=request.query_params.get("error"))

    @app.post("/cases/{case_id}/status")
    def change_status(case_id: str, new_status: str = Form(...)):
        c = _case(case_id)
        try:
            c.set_status(new_status)
        except ResqError as e:
            raise HTTPException(400, str(e)) from None
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.post("/cases/{case_id}/devices")
    def add_device(case_id: str, kind: str = Form(...), maker: str = Form(""), model: str = Form(""),
                   serial: str = Form(""), symptom: str = Form("")):
        c = _case(case_id)
        intake.add_device(c, kind=kind, maker=maker or None, model=model or None, serial=serial or None,
                          symptom=symptom or None)
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.post("/cases/{case_id}/catalog")
    def build_catalog(case_id: str):
        c = _case(case_id)
        catalog_mod.build(c, pdf=True)
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.get("/cases/{case_id}/files", response_class=HTMLResponse)
    def files(request: Request, case_id: str):
        c = _case(case_id)
        rows = c.db.all("SELECT * FROM recovered_files WHERE case_id=? AND rank!='X' ORDER BY rank, id", c.id)
        return page(request, "files.html", case=c.row, files=rows)

    @app.post("/cases/{case_id}/select")
    async def select(request: Request, case_id: str):
        c = _case(case_id)
        form = await request.form()
        ids = [int(v) for v in form.getlist("id")]
        deliver_mod.select(c, ranks=None, ids=ids)
        return RedirectResponse(f"/cases/{case_id}/files", status_code=303)

    @app.get("/cases/{case_id}/download/{kind}")
    def download(case_id: str, kind: str):
        c = _case(case_id)
        path = _downloads(c).get(kind)
        if not path:
            raise HTTPException(404, "まだありません")
        p = Path(path).resolve()
        if not str(p).startswith(str(c.ws.root.resolve())):
            raise HTTPException(403)
        return FileResponse(p, filename=p.name)

    @app.get("/api/cases/{case_id}")
    def api_case(case_id: str):
        c = _case(case_id)
        return json.loads(json.dumps(dict(c.row), default=str))

    return app


def _downloads(c) -> dict[str, str]:
    out = {}
    cat = c.dir / "catalog"
    if (cat / "list.pdf").exists():
        out["catalog_pdf"] = str(cat / "list.pdf")
    if (cat / "list.html").exists():
        out["catalog_html"] = str(cat / "list.html")
    d = c.db.one("SELECT note_path FROM deliveries WHERE case_id=? ORDER BY id DESC LIMIT 1", c.id)
    if d and d["note_path"] and Path(d["note_path"]).exists():
        out["delivery_note"] = d["note_path"]
    cert = c.db.one("SELECT path FROM certificates WHERE case_id=? ORDER BY id DESC LIMIT 1", c.id)
    if cert and Path(cert["path"]).exists():
        out["certificate"] = cert["path"]
    return out


def serve(host: str = LISTEN_HOST, port: int = 8765) -> None:
    if host != LISTEN_HOST:
        raise SafetyError("管理画面は 127.0.0.1 でのみ待ち受けます")
    import uvicorn

    uvicorn.run(create_app(), host=LISTEN_HOST, port=port, log_level="warning")


def launch_main() -> None:
    """resq-web：管理画面を起動してブラウザで開く（Windows ではこれをダブルクリック）。"""
    import argparse
    import threading
    import webbrowser

    ap = argparse.ArgumentParser(prog="resq-web", description="resq 管理画面（127.0.0.1 のみ）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを開かない")
    args = ap.parse_args()
    url = f"http://{LISTEN_HOST}:{args.port}/"
    print(f"resq 管理画面: {url}  （終了するにはこの画面で Ctrl+C）")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    serve(port=args.port)
