"""P5: 納品・作業領域（LUKS）・消去。

完了条件: ドライランの生成コマンドが期待通り。証明書 PDF が生成される。
（LUKS の作成・破棄は root が必要なため、スクリプト生成までをテストし、実行しない）
"""
from __future__ import annotations

import csv
import hashlib
from datetime import date
from pathlib import Path

import pytest

from resq import catalog, deliver, wipe, workspace_crypt
from resq import diagnose as D
from resq import image as I
from resq.errors import ResqError, SafetyError
from resq.recover import pipeline

DATA = Path(__file__).parent / "data"


@pytest.fixture
def recovered(case, fixtures, ro):
    src = ro(fixtures / "deleted.img")
    D.save(D.diagnose(str(src), smart_json=DATA / "smart_healthy.json", ctx=case.ctx), case)
    I.acquire(case, str(src))
    pipeline.run(case, stages=("S1", "S2", "S5"), use_testdisk=False)
    catalog.build(case, pdf=False)
    return case


def test_select_and_deliver_with_hash_check(recovered, tmp_path, expected):
    case = recovered
    assert deliver.select(case, ranks=("A", "B")) == 6
    media = tmp_path / "usb"
    media.mkdir()
    res = deliver.deliver(case, media, operator="店長")
    root = res["root"]
    assert root.name == f"{case.id}_復旧データ"
    want = {f["sha256"] for f in expected["images"]["deleted"]["files"]}
    got = {hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "復旧データ").rglob("*") if p.is_file()}
    assert want == got
    rows = list(csv.reader((root / "納品ファイル一覧.csv").read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0][:3] == ["相対パス", "サイズ", "SHA-256"] and len(rows) == 7
    assert any(p.name.startswith("納品書") for p in root.iterdir())
    assert res["note"].suffix == ".pdf" and res["note"].read_bytes().startswith(b"%PDF")
    assert case.row["status"] == "納品済"
    d = case.db.one("SELECT * FROM deliveries WHERE case_id=?", case.id)
    assert d["files"] == 6 and d["manifest_sha256"] == res["manifest_sha256"]


def test_deliver_refuses_bad_targets(recovered, tmp_path):
    case = recovered
    deliver.select(case)
    with pytest.raises(SafetyError):
        deliver.deliver(case, Path("/dev/sdz"))
    with pytest.raises(SafetyError, match="作業領域"):
        deliver.deliver(case, case.dir / "deliver")
    with pytest.raises(SafetyError):
        deliver.deliver(case, tmp_path / "not-mounted")


def test_deliver_requires_selection(recovered, tmp_path):
    deliver.select(recovered, ranks=())
    with pytest.raises(ResqError, match="選ばれていません"):
        deliver.deliver(recovered, tmp_path)


def test_rank_x_cannot_be_selected(case, fixtures, ro):
    src = ro(fixtures / "overwrite.img")
    D.save(D.diagnose(str(src), smart_json=DATA / "smart_healthy.json", ctx=case.ctx), case)
    I.acquire(case, str(src))
    pipeline.run(case, stages=("S1", "S2"), use_testdisk=False)
    x_ids = [r["id"] for r in case.db.all("SELECT id FROM recovered_files WHERE case_id=? AND rank='X'", case.id)]
    assert x_ids
    assert deliver.select(case, ranks=None, ids=x_ids) == 0


def test_luks_scripts_are_generated_not_executed(ws, monkeypatch, tmp_path):
    w, _db = ws
    monkeypatch.setenv("RESQ_KEYS", str(tmp_path / "keys"))
    create = workspace_crypt.create_commands(w, "R2611-0042", "200G")
    joined = "\n".join(create)
    assert "cryptsetup luksFormat --type luks2 --batch-mode --key-file" in joined
    assert f"cryptsetup open --key-file {tmp_path}/keys/R2611-0042.key" in joined
    assert joined.index("luksFormat") < joined.index("cryptsetup open") < joined.index("mkfs.ext4") < joined.index("mount ")
    destroy = workspace_crypt.destroy_commands(w, "R2611-0042")
    assert destroy[0].startswith("umount ") and destroy[1].startswith("cryptsetup close ")
    assert destroy[2].startswith("cryptsetup erase --batch-mode ")
    assert any(c.startswith("rm -f") and c.endswith(".key") for c in destroy)
    p = workspace_crypt.write_script(w, "R2611-0042", "create", create)
    assert p.read_text().startswith("#!/usr/bin/env bash") and p.stat().st_mode & 0o777 == 0o700
    assert not (tmp_path / "keys").exists(), "生成するだけで実行しない"


def test_wipe_requires_finished_case(recovered):
    assert recovered.row["status"] == "一覧提示"  # 納品もキャンセルもしていない
    with pytest.raises(ResqError, match="消去できません"):
        wipe.wipe_plain(recovered, execute=True)


def test_wipe_plain_dry_run_then_execute(recovered, tmp_path):
    case = recovered
    deliver.select(case)
    (tmp_path / "usb").mkdir()
    deliver.deliver(case, tmp_path / "usb")
    dry = wipe.wipe_plain(case)
    assert dry["dry_run"] and dry["summary"]["images"] == 1 and case.dir.exists()
    res = wipe.wipe_plain(case, execute=True, operator="店長")
    assert not case.dir.exists()
    assert res["path"].suffix == ".pdf" and res["path"].read_bytes().startswith(b"%PDF")
    assert hashlib.sha256(res["path"].read_bytes()).hexdigest() == res["sha256"]
    assert case.row["status"] == "消去済"
    assert case.db.one("SELECT COUNT(*) AS n FROM recovered_files WHERE case_id=?", case.id)["n"] == 0
    cert = case.db.one("SELECT * FROM certificates WHERE case_id=?", case.id)
    assert cert["number"] == res["number"] and cert["kind"] == "作業領域消去"


def test_wipe_luks_plan_and_confirm(recovered, tmp_path, monkeypatch):
    case = recovered
    monkeypatch.setenv("RESQ_KEYS", str(tmp_path / "keys"))
    case.set_status("キャンセル")
    p = workspace_crypt.paths(case.ws, case.id)
    p.container.parent.mkdir(parents=True, exist_ok=True)
    p.container.write_bytes(b"LUKS\xba\xbe")  # コンテナがある＝暗号化作業領域
    with pytest.raises(ResqError, match="暗号化コンテナ"):
        wipe.wipe_plain(case, execute=True)
    script = wipe.plan(case)
    assert "cryptsetup erase" in script.read_text()
    with pytest.raises(ResqError, match="まだ残っています"):
        wipe.confirm(case)
    p.container.unlink()  # ＝人間が作業機で破棄スクリプトを実行した
    res = wipe.confirm(case, pdf=True)
    assert "LUKS2" in Path(str(res["path"]).replace(".pdf", ".html")).read_text()
    assert case.row["status"] == "消去済"


def test_retention_due(ws):
    from resq.cases import create_case

    w, db = ws
    a = create_case(w, db, customer="A", retention_until="2026-11-01")
    b = create_case(w, db, customer="B", retention_until="2026-12-31")
    for c in (a, b):
        db.execute("UPDATE cases SET status='納品済' WHERE id=?", c.id)
    due = wipe.due(db, today=date(2026, 11, 14))
    assert [d["id"] for d in due] == [a.id]
