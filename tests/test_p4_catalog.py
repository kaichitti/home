"""P4: 一覧化・検証。意図的に壊したファイルが「破損」と判定され、一覧で区別される。"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from resq import catalog
from resq import validate as V
from resq.recover import ingest as ING
from resq.recover import merge as M

DATA = Path(__file__).parent / "data"


@pytest.mark.parametrize("name,status", [
    ("good.jpg", V.OK), ("truncated.jpg", V.PARTIAL), ("garbage.jpg", V.BROKEN),
    ("good.pdf", V.OK), ("truncated.pdf", V.PARTIAL),
    ("good.docx", V.OK), ("zero.bin", V.ZERO),
])
def test_validate_corrupt_samples(fixtures, name, status):
    r = V.validate(fixtures / "corrupt" / name)
    assert r.status == status, r


def test_broken_docx_is_not_ok(fixtures):
    r = V.validate(fixtures / "corrupt" / "broken.docx")
    assert r.status in (V.PARTIAL, V.BROKEN)


def test_kind_detection(fixtures):
    assert V.validate(fixtures / "corrupt" / "good.docx").kind == "docx"
    assert V.validate(fixtures / "corrupt" / "good.jpg").kind == "jpg"
    assert V.detect_kind(b"\x00\x00\x00\x18ftypheic") == "heic"


def test_catalog_distinguishes_ranks(case, fixtures):
    ING.ingest(case, fixtures / "corrupt", engine="DMDE")
    M.merge(case)
    res = catalog.build(case, pdf=True)
    html = Path(res["html"]).read_text()
    ranks = res["ranks"]
    assert ranks["A"] == 3                       # good.jpg / good.pdf / good.docx
    assert ranks["C"] >= 2                       # truncated.jpg / truncated.pdf（＋broken.docx）
    assert res["excluded"] >= 2                  # garbage.jpg / zero.bin は復旧扱いしない
    assert "一部破損" in html and "開ける" in html
    assert "zero.bin" not in html and "garbage.jpg" not in html
    assert "復旧したものとして扱っていません" in html
    assert list((case.dir / "catalog" / "thumbs").glob("*.jpg")), "画像のサムネイル"
    if res["pdf"]:
        assert res["pdf"].read_bytes().startswith(b"%PDF")
    assert case.row["status"] == "受付"  # 診断前の案件は状態を飛ばさない


def test_cli_end_to_end(tmp_path, monkeypatch, fixtures):
    """受付 → 同意 → 診断 → イメージ化 → 復旧 → 一覧 を CLI で通す。"""
    from resq.cli import app

    monkeypatch.setenv("RESQ_HOME", str(tmp_path / "data"))
    src = tmp_path / "src.img"
    src.write_bytes((fixtures / "deleted.img").read_bytes())
    src.chmod(0o444)
    run = CliRunner().invoke

    r = run(app, ["case", "new", "--customer", "山田 花子", "--price-cap", "9800"])
    assert r.exit_code == 0, r.output
    cid = r.output.split(":")[1].split()[0]
    r = run(app, ["image", cid, str(src)])
    assert r.exit_code == 1 and "同意書" in r.output  # 同意前は作業できない
    assert run(app, ["consent", "add", cid, "--form-version", "2026.11", "--id-method", "マイナンバーカード"]).exit_code == 0
    r = run(app, ["diagnose", str(src), "--case", cid, "--smart-json", str(DATA / "smart_healthy.json")])
    assert r.exit_code == 0 and "自社" in r.output
    r = run(app, ["image", cid, str(src)])
    assert r.exit_code == 0, r.output
    r = run(app, ["recover", cid, "--no-testdisk"])
    assert r.exit_code == 0, r.output
    r = run(app, ["catalog", cid, "--no-pdf"])
    assert r.exit_code == 0 and "A=6" in r.output
    r = run(app, ["events", cid])
    assert r.exit_code == 0 and "image.pass1" in r.output
