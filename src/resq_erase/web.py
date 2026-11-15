"""消去ステーションの管理画面（127.0.0.1 のみ）。媒体の受付・スマホ初期化代行のチェックリスト・証明書。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from resq.errors import SafetyError
from resq.reports import human_bytes
from resq.web import LISTEN_HOST, LocalOnly

from . import certificate, mobile_checklist
from .errors import EraseError
from .ledger import KINDS, ORIGINS, Ledger

TEMPLATES = Path(__file__).parent / "templates"
PHOTO_EXT = {".jpg", ".jpeg", ".png"}


def create_app(home: Path | None = None) -> FastAPI:
    app = FastAPI(title="resq-erase", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalOnly)
    tpl = Jinja2Templates(directory=str(TEMPLATES))
    tpl.env.filters["bytes"] = human_bytes

    def L() -> Ledger:
        return Ledger(home)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        lg = L()
        return tpl.TemplateResponse(request, "web_index.html",
                                    {"media": lg.all("SELECT * FROM media ORDER BY id DESC")})

    @app.get("/media/new", response_class=HTMLResponse)
    def new_form(request: Request):
        return tpl.TemplateResponse(request, "web_media_new.html", {"kinds": KINDS, "origins": ORIGINS, "error": None})

    @app.post("/media/new")
    def new_media(request: Request, serial: str = Form(...), kind: str = Form(...), requester: str = Form(...),
                  origin: str = Form(...), consent_doc: str = Form(""), maker: str = Form(""), model: str = Form(""),
                  device_maker: str = Form(""), device_model: str = Form(""), device_serial: str = Form(""),
                  location: str = Form("")):
        lg = L()
        try:
            mid = lg.register(serial=serial, kind=kind, requester=requester, origin=origin,
                              consent_doc=consent_doc or None, maker=maker or None, model=model or None,
                              device_maker=device_maker or None, device_model=device_model or None,
                              device_serial=device_serial or None, location=location or None)
        except (EraseError, Exception) as e:  # noqa: BLE001 - UNIQUE 制約違反なども表示する
            return tpl.TemplateResponse(request, "web_media_new.html",
                                        {"kinds": KINDS, "origins": ORIGINS, "error": str(e)}, status_code=400)
        return RedirectResponse(f"/media/{mid}", status_code=303)

    def _media(lg: Ledger, mid: int):
        m = lg.one("SELECT * FROM media WHERE id=?", mid)
        if m is None:
            raise HTTPException(404)
        return m

    @app.get("/media/{mid}", response_class=HTMLResponse)
    def detail(request: Request, mid: int):
        lg = L()
        m = _media(lg, mid)
        return tpl.TemplateResponse(request, "web_media.html", {
            "m": m, "checklist": mobile_checklist.get(lg, mid) if m["kind"] == "スマホ" else None,
            "complete": mobile_checklist.is_complete(lg, mid) if m["kind"] == "スマホ" else None,
            "items": mobile_checklist.ITEMS,
            "runs": lg.all("SELECT * FROM runs WHERE media_id=? ORDER BY id", mid),
            "vers": lg.all("SELECT * FROM verifications WHERE media_id=? ORDER BY id", mid),
            "certs": lg.all("SELECT * FROM certificates WHERE media_id=? ORDER BY id", mid),
            "blocked": lg.blocked_reason(m["serial"]), "error": request.query_params.get("error")})

    @app.post("/media/{mid}/checklist")
    async def checklist(request: Request, mid: int, photo: UploadFile | None = File(None)):
        lg = L()
        _media(lg, mid)
        form = await request.form()
        checked = {item: f"item_{i}" in form for i, item in enumerate(mobile_checklist.ITEMS)}
        photos = []
        if photo is not None and photo.filename:
            ext = Path(photo.filename).suffix.lower()
            if ext not in PHOTO_EXT:
                raise HTTPException(400, "写真は JPEG / PNG のみ")
            d = lg.home / "photos" / str(mid)
            d.mkdir(parents=True, exist_ok=True)
            dest = d / f"checklist_{len(list(d.iterdir())) + 1:03d}{ext}"
            dest.write_bytes(await photo.read())
            photos.append(str(dest))
        try:
            mobile_checklist.save(lg, mid, checked, photos)
        except EraseError as e:
            raise HTTPException(400, str(e)) from None
        return RedirectResponse(f"/media/{mid}", status_code=303)

    @app.post("/media/{mid}/certificate")
    def issue(mid: int, operator: str = Form("")):
        lg = L()
        _media(lg, mid)
        try:
            certificate.issue(lg, mid, operator=operator)
        except EraseError as e:
            raise HTTPException(400, str(e)) from None
        return RedirectResponse(f"/media/{mid}", status_code=303)

    @app.get("/certificates/{number}")
    def cert_file(number: str):
        lg = L()
        r = lg.one("SELECT path FROM certificates WHERE number=?", number)
        if r is None or not Path(r["path"]).exists():
            raise HTTPException(404)
        return FileResponse(r["path"], filename=Path(r["path"]).name)

    @app.get("/api/media/{mid}")
    def api_media(mid: int):
        lg = L()
        m = dict(_media(lg, mid))
        m["photos"] = json.loads(m["photos"] or "[]")
        return m

    return app


def serve(host: str = LISTEN_HOST, port: int = 8766) -> None:
    if host != LISTEN_HOST:
        raise SafetyError("管理画面は 127.0.0.1 でのみ待ち受けます")
    import uvicorn

    uvicorn.run(create_app(), host=LISTEN_HOST, port=port, log_level="warning")
