"""P2: イメージ化（ddrescue, mapfile, 中断・再開）。"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from resq import diagnose as D
from resq import image as I
from resq.errors import SafetyError

DATA = Path(__file__).parent / "data"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _diag(case, src, smart="smart_healthy.json"):
    D.save(D.diagnose(str(src), smart_json=DATA / smart, ctx=case.ctx), case)


def test_full_image_matches_source(case, fixtures, ro):
    src = ro(fixtures / "deleted.img")
    _diag(case, src)
    iid = I.acquire(case, str(src))
    row = case.db.one("SELECT * FROM images WHERE id=?", iid)
    assert row["sha256"] == sha(src)
    assert row["unreadable_bytes"] == 0
    assert Path(row["mapfile"]).exists()
    assert not (Path(row["path"]).stat().st_mode & 0o222), "取得後のイメージは読み取り専用"
    assert case.row["status"] == "イメージ取得済"
    ops = [r["op"] for r in case.db.all("SELECT op FROM events WHERE case_id=?", case.id)]
    assert "image.pass1" in ops and "safety.getro" not in ops  # ファイル原本なので blockdev は使わない


def test_interrupt_and_resume_gives_same_hash(case, fixtures, ro):
    src = ro(fixtures / "quickformat.img")
    _diag(case, src)
    iid1 = I.acquire(case, str(src), max_bytes=7 * 1024 * 1024)  # 7MiB で中断したのと同じ状態
    row = case.db.one("SELECT * FROM images WHERE id=?", iid1)
    assert row["sha256"] is None
    st = I.parse_mapfile(Path(row["mapfile"]).read_text())
    assert st.untried > 0 and st.finished == 7 * 1024 * 1024
    with pytest.raises(SafetyError, match="未完了"):
        I.get_image(case, iid1)
    iid2 = I.acquire(case, str(src))  # 再開
    assert iid2 == iid1
    assert case.db.one("SELECT sha256 FROM images WHERE id=?", iid1)["sha256"] == sha(src)
    assert any(r["op"] == "image.resume" for r in case.db.all("SELECT op FROM events WHERE case_id=?", case.id))


def test_writable_source_is_refused(case, fixtures, tmp_path):
    src = tmp_path / "rw.img"
    src.write_bytes((fixtures / "deleted.img").read_bytes())
    _diag(case, src)
    with pytest.raises(SafetyError, match="書き込み権限"):
        I.acquire(case, str(src))


def test_requires_diagnosis(case, fixtures, ro):
    with pytest.raises(SafetyError, match="診断"):
        I.acquire(case, str(ro(fixtures / "deleted.img")))


def test_degraded_requires_accept_risk(case, fixtures, ro):
    src = ro(fixtures / "deleted.img")
    _diag(case, src, "smart_degraded.json")
    with pytest.raises(SafetyError, match="accept-risk"):
        I.acquire(case, str(src))
    I.acquire(case, str(src), accept_risk=True)


def test_refer_verdict_is_never_imaged(case, fixtures, ro):
    src = ro(fixtures / "deleted.img")
    _diag(case, src, "smart_danger.json")
    with pytest.raises(SafetyError, match="取次"):
        I.acquire(case, str(src), accept_risk=True)


def test_parse_mapfile():
    text = """# Mapfile. Created by GNU ddrescue version 1.27
# current_pos  current_status  current_pass
0x00100000     +               1
#      pos        size  status
0x00000000  0x00100000  +
0x00100000  0x00000200  -
0x00100200  0x00000400  *
0x00100600  0x00010000  ?
"""
    st = I.parse_mapfile(text)
    assert st.finished == 0x100000 and st.bad == 0x200 and st.pending == 0x400
    assert st.untried == 0x10000 and not st.complete and st.size == 0x110600
