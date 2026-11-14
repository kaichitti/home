"""P6: 受付・案件管理画面。

完了条件: 定義外の状態遷移がエラーになる。待ち受けアドレスが 127.0.0.1 固定。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resq import diagnose as D
from resq import image as I
from resq.errors import SafetyError
from resq.recover import pipeline
from resq.web import LISTEN_HOST, create_app, serve

DATA = Path(__file__).parent / "data"
FORM = {"customer": "鈴木 一郎", "contact": "090-0000-0000", "price_cap": "19,800", "retention_until": "2026-12-15",
        "form_version": "2026.11", "id_method": "運転免許証", "ownership": "本人所有",
        "kind": "HDD", "maker": "WD", "model": "WD10EZEX", "serial": "WCC0000001", "symptom": "誤削除"}


@pytest.fixture
def client(ws):
    w, _db = ws
    return TestClient(create_app(w), base_url="http://127.0.0.1")


def _new(client, **over):
    return client.post("/cases/new", data={**FORM, **over}, follow_redirects=False)


def test_listen_address_is_fixed():
    assert LISTEN_HOST == "127.0.0.1"
    for bad in ("0.0.0.0", "192.168.1.10", "::"):
        with pytest.raises(SafetyError):
            serve(host=bad)


def test_foreign_host_and_origin_are_rejected(ws):
    w, _db = ws
    evil = TestClient(create_app(w), base_url="http://attacker.example")
    assert evil.get("/").status_code == 403
    c = TestClient(create_app(w), base_url="http://127.0.0.1")
    r = c.post("/cases/new", data=FORM, headers={"Origin": "http://attacker.example"})
    assert r.status_code == 403


def test_intake_flow_and_transitions(client):
    r = _new(client)
    assert r.status_code == 303
    url = r.headers["location"]
    cid = url.rsplit("/", 1)[1]
    page = client.get(url)
    assert page.status_code == 200 and "鈴木 一郎" in page.text and "WCC0000001" in page.text
    assert "19,800 円" in page.text and "運転免許証" in page.text
    # 定義外の遷移はエラー
    bad = client.post(f"/cases/{cid}/status", data={"new_status": "納品済"})
    assert bad.status_code == 400
    ok = client.post(f"/cases/{cid}/status", data={"new_status": "診断済"}, follow_redirects=False)
    assert ok.status_code == 303
    assert client.get(f"/api/cases/{cid}").json()["status"] == "診断済"
    assert cid in client.get("/").text


def test_intake_validation(client, ws):
    _w, db = ws
    r = _new(client, ownership="法人所有（権限者の同意書面あり）")
    assert r.status_code == 400 and "権限者の同意書面" in r.text
    r = _new(client, request_text="パスコード解除をお願いしたい")
    assert r.status_code == 400 and "ロック解除" in r.text
    assert db.one("SELECT COUNT(*) AS n FROM cases")["n"] == 0, "失敗した受付で半端な案件を残さない"


def test_files_selection_and_downloads(client, ws, fixtures, ro):
    from resq.cases import get_case

    w, db = ws
    cid = _new(client).headers["location"].rsplit("/", 1)[1]
    case = get_case(w, db, cid)
    src = ro(fixtures / "deleted.img")
    D.save(D.diagnose(str(src), smart_json=DATA / "smart_healthy.json", ctx=case.ctx), case)
    I.acquire(case, str(src))
    pipeline.run(case, stages=("S1", "S2"), use_testdisk=False)
    page = client.get(f"/cases/{cid}/files")
    assert page.status_code == 200 and "IMG_0001.JPG" in page.text
    ids = [r["id"] for r in db.all("SELECT id FROM recovered_files WHERE case_id=? AND rank='A'", cid)][:2]
    client.post(f"/cases/{cid}/select", data={"id": [str(i) for i in ids]})
    assert db.one("SELECT SUM(selected) AS s FROM recovered_files WHERE case_id=?", cid)["s"] == 2
    assert client.get(f"/cases/{cid}/download/catalog_pdf").status_code == 404
    client.post(f"/cases/{cid}/catalog")
    r = client.get(f"/cases/{cid}/download/catalog_pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get("/cases/R0000-9999").status_code == 404
