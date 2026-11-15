"""E1〜E5: 完全消去ツール resq-erase（消去ステーション専用ビルド）。

消去系のテストはドライラン（実行予定コマンドの生成）までに限る。消去コマンドは一切実行しない。
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from resq_erase import certificate as C
from resq_erase import exec as ex
from resq_erase import mobile_checklist as MC
from resq_erase import probe as P
from resq_erase import run as R
from resq_erase import verify as V
from resq_erase.errors import EraseError, EraseRefused
from resq_erase.ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- モック（識別コマンドの出力）
LSBLK = {"blockdevices": [
    {"name": "sda", "serial": "STATION-BOOT-01", "model": "Station SSD", "size": 256060514304, "tran": "sata",
     "rota": False, "rm": False, "type": "disk",
     "children": [{"name": "sda1", "mountpoints": ["/boot/efi"]}, {"name": "sda2", "mountpoints": ["/"]}]},
    {"name": "sdb", "serial": "WD-WCC4E1234567", "model": "WDC WD10EZEX", "size": 1000204886016, "tran": "sata",
     "rota": True, "rm": False, "type": "disk", "children": [{"name": "sdb1", "mountpoints": [None]}]},
    {"name": "sdc", "serial": "S3Z1NB0K123456A", "model": "Samsung SSD 860", "size": 500107862016, "tran": "sata",
     "rota": False, "rm": False, "type": "disk"},
    {"name": "sdd", "serial": "USBSSD0000001", "model": "USB3.0 Bridge", "size": 512110190592, "tran": "usb",
     "rota": False, "rm": False, "type": "disk"},
    {"name": "sde", "serial": "4C530001230101", "model": "Cruzer Blade", "size": 16008609792, "tran": "usb",
     "rota": False, "rm": True, "type": "disk"},
    {"name": "nvme0n1", "serial": "S4EWNX0R123456", "model": "Samsung SSD 970", "size": 500107862016,
     "tran": "nvme", "rota": False, "rm": False, "type": "disk"},
    {"name": "sdf", "serial": "RECOVERY-CASE-9", "model": "ST1000DM010", "size": 1000204886016, "tran": "sata",
     "rota": True, "rm": False, "type": "disk"},
]}

HDPARM_SSD = """
/dev/sdc:

ATA device, with non-removable media
	Model Number:       Samsung SSD 860 EVO 500GB
	Serial Number:      S3Z1NB0K123456A
	Nominal Media Rotation Rate: Solid State Device
Commands/features:
	Enabled	Supported:
	   *	SANITIZE feature set
	   *	BLOCK_ERASE_EXT command
	   *	CRYPTO_SCRAMBLE_EXT command
Security:
	Master password revision code = 65534
		supported
	not	enabled
	not	locked
	not	frozen
	not	expired: security count
		supported: enhanced erase
	2min for SECURITY ERASE UNIT. 8min for ENHANCED SECURITY ERASE UNIT.
Logical Unit WWN Device Identifier: 5002538e40000000
"""
HDPARM_SSD_FROZEN_ESE = HDPARM_SSD.replace("	   *	SANITIZE feature set\n	   *	BLOCK_ERASE_EXT command\n"
                                           "	   *	CRYPTO_SCRAMBLE_EXT command\n", "") \
    .replace("	not	frozen", "		frozen")
HDPARM_SSD_NONE = re.sub(r"Security:.*?(?=Logical)", "", HDPARM_SSD_FROZEN_ESE, flags=re.S)
HDPARM_HDD = """
/dev/sdb:

ATA device, with non-removable media
	Model Number:       WDC WD10EZEX-08WN4A0
	Nominal Media Rotation Rate: 7200
Commands/features:
	Enabled	Supported:
	   *	SMART feature set
Security:
		supported
	not	enabled
	not	locked
	not	frozen
"""
HDPARM_HDD_SANITIZE = HDPARM_HDD.replace("	   *	SMART feature set\n",
                                         "	   *	SMART feature set\n	   *	SANITIZE feature set\n"
                                         "	   *	OVERWRITE_EXT command\n")
HPA_ON = "\n/dev/sdb:\n max sectors   = 1953523055/1953525168, HPA is enabled\n"
HPA_OFF = "\n/dev/sdb:\n max sectors   = 1953525168/1953525168, HPA is disabled\n"


def _probe(serial, kind=None, **kw):
    return P.probe_from_outputs(serial, lsblk=LSBLK, declared_kind=kind, **kw)


# ---------------------------------------------------------------- E1
def test_hdd_without_sanitize_is_clear_overwrite():
    p = _probe("WD-WCC4E1234567", "HDD", hdparm_i=HDPARM_HDD, hdparm_n=HPA_OFF)
    m = P.select_method(p, "/dev/sdb")
    assert p.media == "hdd" and m.category == P.CLEAR and m.executable
    assert m.commands == [["nwipe", "--autonuke", "--nogui", "--method=zero", "--verify=last", "--rounds=1", "/dev/sdb"]]
    assert m.expected_pattern == b"\0"


def test_hdd_with_sanitize_is_purge_and_hpa_blocks():
    m = P.select_method(_probe("WD-WCC4E1234567", "HDD", hdparm_i=HDPARM_HDD_SANITIZE, hdparm_n=HPA_OFF), "/dev/sdb")
    assert m.category == P.PURGE and "Overwrite" in m.name
    assert "--sanitize-overwrite" in m.commands[0]
    m2 = P.select_method(_probe("WD-WCC4E1234567", "HDD", hdparm_i=HDPARM_HDD, hdparm_n=HPA_ON), "/dev/sdb")
    assert m2.blockers and "HPA" in m2.blockers[0] and not m2.executable


def test_sata_ssd_methods_never_overwrite():
    crypto = P.select_method(_probe("S3Z1NB0K123456A", "SATA SSD", hdparm_i=HDPARM_SSD), "/dev/sdc")
    assert crypto.category == P.PURGE and "Crypto Scramble" in crypto.name and crypto.executable
    ese = P.select_method(_probe("S3Z1NB0K123456A", "SATA SSD", hdparm_i=HDPARM_SSD_FROZEN_ESE), "/dev/sdc")
    assert ese.name == "ATA Enhanced Secure Erase" and not ese.executable and "frozen" in ese.blockers[0]
    none = P.select_method(_probe("S3Z1NB0K123456A", "SATA SSD", hdparm_i=HDPARM_SSD_NONE), "/dev/sdc")
    assert none.category == P.DESTROY
    for m in (crypto, ese, none):
        assert not any(c[0] == "nwipe" for c in m.commands), "SSD に上書きは使わない"


@pytest.mark.parametrize("nvme_id,name,cmd", [
    ({"sanicap": 3, "oacs": 2, "fna": 4, "sn": "S4EWNX0R123456"}, "Crypto Erase", "--sanact=0x04"),
    ({"sanicap": 2, "oacs": 2, "fna": 0, "sn": "S4EWNX0R123456"}, "Block Erase", "--sanact=0x02"),
    ({"sanicap": 0, "oacs": 2, "fna": 4, "sn": "S4EWNX0R123456"}, "SES=2", "--ses=2"),
])
def test_nvme_methods(nvme_id, name, cmd):
    m = P.select_method(_probe("S4EWNX0R123456", "NVMe SSD", nvme_id=nvme_id), "/dev/nvme0n1")
    assert m.category == P.PURGE and name in m.name and cmd in m.commands[0]


def test_usb_attached_ssd_requires_direct_connection():
    p = _probe("USBSSD0000001", "SATA SSD", hdparm_i=HDPARM_SSD)
    m = P.select_method(p, "/dev/sdd")
    assert p.media == "usb_ssd"
    assert m.category is None and m.name == P.DIRECT_CONNECT and not m.commands and not m.executable


def test_usb_flash_and_unreadable():
    m = P.select_method(_probe("4C530001230101", "USB メモリ"), "/dev/sde")
    assert m.category == P.CLEAR and m.commands[0][0] == "nwipe"
    dead = P.select_method(_probe("4C530001230101", "USB メモリ", readable=False))
    assert dead.category == P.DESTROY


# ---------------------------------------------------------------- E2
@pytest.fixture
def lg(tmp_path):
    led = Ledger(tmp_path / "erase-home")
    yield led
    led.close()


def _register(lg, serial, kind, **kw):
    return lg.register(serial=serial, kind=kind, requester="山田商事", origin="法人", consent_doc="承諾書 No.7",
                       location="棚 A-1", **kw)


def test_register_requires_serial_and_consent(lg):
    with pytest.raises(EraseError):
        lg.register(serial=" ", kind="HDD", requester="x", origin="個人", consent_doc="c")
    with pytest.raises(EraseError, match="承諾書"):
        lg.register(serial="X1", kind="HDD", requester="x", origin="個人", consent_doc=None)
    lg.register(serial="X2", kind="HDD", requester="自社", origin="自社買取", consent_doc=None)


def test_dry_run_generates_commands_without_executing(lg):
    _register(lg, "WD-WCC4E1234567", "HDD")
    p = _probe("WD-WCC4E1234567", "HDD", hdparm_i=HDPARM_HDD, hdparm_n=HPA_OFF)
    plan = R.plan(lg, "WD-WCC4E1234567", p, P.select_method, lsblk=LSBLK)
    assert plan.device == "/dev/sdb"
    assert plan.commands[0][-1] == "/dev/sdb"
    run = lg.one("SELECT * FROM runs WHERE id=?", plan.run_id)
    assert run["dry_run"] == 1 and run["completion"] == "dry-run"
    ev = [e["op"] for e in lg.all("SELECT op FROM events")]
    assert "erase.plan.dryrun" in ev and "erase.exec" not in ev


def test_refusals(lg, tmp_path):
    p = _probe("WD-WCC4E1234567", "HDD", hdparm_i=HDPARM_HDD)
    # 未登録
    with pytest.raises(EraseRefused, match="登録されていません"):
        R.plan(lg, "WD-WCC4E1234567", p, P.select_method, lsblk=LSBLK)
    # 復旧案件のシリアル（resq export-serials から同期）
    _register(lg, "RECOVERY-CASE-9", "HDD")
    export = tmp_path / "serials.json"
    export.write_text(json.dumps({"serials": [{"serial": "RECOVERY-CASE-9", "case_id": "R2611-0003"}]}))
    assert lg.sync_blocked_from_resq(export) == 1
    with pytest.raises(EraseRefused, match="R2611-0003"):
        R.plan(lg, "RECOVERY-CASE-9", p, P.select_method, lsblk=LSBLK)
    # 起動ディスク（マウント中）
    _register(lg, "STATION-BOOT-01", "SATA SSD")
    with pytest.raises(EraseRefused, match="マウント中"):
        R.plan(lg, "STATION-BOOT-01", p, P.select_method, lsblk=LSBLK)
    # ステーション自身のディスクとして設定されたシリアル
    _register(lg, "S3Z1NB0K123456A", "SATA SSD")
    with pytest.raises(EraseRefused, match="ステーション自身"):
        R.plan(lg, "S3Z1NB0K123456A", p, P.select_method, lsblk=LSBLK, station_serials={"S3Z1NB0K123456A"})
    # 接続されていない
    _register(lg, "NOT-CONNECTED", "HDD")
    with pytest.raises(EraseRefused, match="接続されていません"):
        R.plan(lg, "NOT-CONNECTED", p, P.select_method, lsblk=LSBLK)


def test_execute_requires_last4_station_and_same_device(lg, monkeypatch, tmp_path):
    _register(lg, "WD-WCC4E1234567", "HDD")
    p = _probe("WD-WCC4E1234567", "HDD", hdparm_i=HDPARM_HDD, hdparm_n=HPA_OFF)
    plan = R.plan(lg, "WD-WCC4E1234567", p, P.select_method, lsblk=LSBLK)
    with pytest.raises(EraseRefused, match="下 4 桁"):
        R.execute(lg, plan, confirm_last4="0000", get_lsblk=lambda: LSBLK)
    # 開発機＝消去ステーションではない → 実行しない
    monkeypatch.setattr(ex, "STATION_MARKER", tmp_path / "no-marker")
    with pytest.raises(EraseRefused, match="消去ステーション"):
        R.execute(lg, plan, confirm_last4="4567", get_lsblk=lambda: LSBLK)
    # デバイス名が変わった（接続し直し）
    moved = json.loads(json.dumps(LSBLK))
    for d in moved["blockdevices"]:
        if d["serial"] == "WD-WCC4E1234567":
            d["name"] = "sdg"
    with pytest.raises(EraseRefused, match="デバイス名が変わりました"):
        R.execute(lg, plan, confirm_last4="4567", get_lsblk=lambda: moved)
    assert lg.one("SELECT COUNT(*) AS n FROM runs WHERE dry_run=0")["n"] == 0


def test_executor_classification_and_station_marker(lg, monkeypatch, tmp_path):
    assert not ex.is_destructive(["hdparm", "-I", "/dev/sdb"])
    assert not ex.is_destructive(["hdparm", "-N", "/dev/sdb"])
    assert not ex.is_destructive(["hdparm", "--sanitize-status", "/dev/sdb"])
    assert ex.is_destructive(["hdparm", "--yes-i-know-what-i-am-doing", "--sanitize-block-erase", "/dev/sdb"])
    assert ex.is_destructive(["hdparm", "--user-master", "u", "--security-erase-enhanced", "p", "/dev/sdb"])
    assert ex.is_destructive(["hdparm", "-N", "p1953525168", "/dev/sdb"])
    assert not ex.is_destructive(["nvme", "id-ctrl", "/dev/nvme0n1", "-o", "json"])
    assert ex.is_destructive(["nvme", "sanitize", "/dev/nvme0n1", "--sanact=0x04"])
    assert ex.is_destructive(["nwipe", "--autonuke", "/dev/sdb"])
    # 消去コマンドは execute=False なら実行せず記録のみ
    assert ex.run(["nwipe", "--autonuke", "/dev/sdb"], ledger=lg, op="t") is None
    with pytest.raises(EraseRefused):
        ex.run(["rm", "-rf", "/"], ledger=lg, op="t")
    # マーカーと環境変数が一致しないと消去ステーションとみなさない
    marker = tmp_path / "marker"
    marker.write_text("ST-01\n")
    monkeypatch.setattr(ex, "STATION_MARKER", marker)
    monkeypatch.setenv("RESQ_ERASE_STATION_ID", "ST-02")
    assert ex.station_id() is None
    monkeypatch.setenv("RESQ_ERASE_STATION_ID", "ST-01")
    assert ex.station_id() == "ST-01"


def test_inventory_check(lg):
    _register(lg, "A1", "HDD")
    _register(lg, "A2", "HDD")
    res = lg.inventory_check(["A1", "Z9"])
    assert res == {"missing": ["A2"], "unregistered": ["Z9"], "ok": ["A1"]}


# ---------------------------------------------------------------- E3
def test_verify_zero_filled_passes(lg, tmp_path):
    mid = _register(lg, "ZERO-1", "HDD")
    img = tmp_path / "zero.img"
    img.write_bytes(b"\0" * (8 << 20))
    res = V.verify(lg, mid, img, img.stat().st_size, expected=b"\0", scope="full", completion="commands-ok")
    assert res["passed"] and res["readback"]["ok"] and res["recovery"]["recovered"] == 0
    assert lg.one("SELECT status FROM media WHERE id=?", mid)["status"] == "消去済"


def test_verify_remaining_data_fails(lg, tmp_path, fixtures):
    mid = _register(lg, "LEFT-1", "HDD")
    img = tmp_path / "left.img"
    img.write_bytes((fixtures / "deleted.img").read_bytes())
    res = V.verify(lg, mid, img, img.stat().st_size, expected=b"\0", scope="sample")
    assert not res["passed"] and not res["readback"]["ok"]
    assert res["recovery"]["recovered"] >= 6
    assert lg.one("SELECT status FROM media WHERE id=?", mid)["status"] == "検証不合格"


def test_verify_crypto_erased_random_passes(lg, tmp_path):
    mid = _register(lg, "CRYPTO-1", "NVMe SSD")
    img = tmp_path / "crypto.img"
    img.write_bytes(random.Random(1).randbytes(4 << 20))
    res = V.verify(lg, mid, img, img.stat().st_size, expected=None, scope="sample", completion="completed",
                   use_photorec=False)
    assert res["passed"], res


def test_completion_status_parsers():
    assert V.nvme_sanitize_status({"sstat": 0x101}) == "completed"
    assert V.nvme_sanitize_status({"sstat": 2}) == "in_progress"
    assert V.nvme_sanitize_status({"sstat": 3}) == "failed"
    assert V.hdparm_sanitize_status("Sanitize status:\n    State:    SD2 Sanitize operation In Process") == "in_progress"
    assert V.hdparm_sanitize_status("    State:    SD0 Sanitize Idle\n    Last Sanitize Operation Completed Without Error") == "completed"
    assert V.hdparm_sanitize_status("    State:    SD3 Sanitize Operation Failed") == "failed"
    assert V.hdparm_sanitize_status("    State:    SD1 Sanitize Frozen") == "unknown"


def test_monthly_validation_table(lg):
    V.record_validation(lg, model="WD10EZEX", kind="HDD", method="nwipe zero", planted_files=50, recovered=0)
    V.record_validation(lg, model="WD10EZEX", kind="HDD", method="nwipe zero", planted_files=50, recovered=0)
    V.record_validation(lg, model="CT500MX500", kind="SATA SSD", method="Crypto Scramble", planted_files=50,
                        recovered=2)
    t = {(r["model"], r["method"]): r for r in V.validation_table(lg)}
    assert t[("WD10EZEX", "nwipe zero")]["all_passed"] and t[("WD10EZEX", "nwipe zero")]["runs"] == 2
    assert not t[("CT500MX500", "Crypto Scramble")]["all_passed"]


# ---------------------------------------------------------------- E4
def _passed_media(lg, tmp_path, serial="CERT-1"):
    mid = _register(lg, serial, "HDD", maker="WDC", model="WD10EZEX", capacity=1000204886016)
    lg.insert("runs", media_id=mid, category="Clear", method="全領域 1 回上書き（ゼロ）＋全域検証", commands="[]",
              dry_run=0, started_at="2026-11-14T10:00:00+09:00", finished_at="2026-11-14T12:10:00+09:00",
              completion="commands-ok")
    img = tmp_path / f"{serial}.img"
    img.write_bytes(b"\0" * (2 << 20))
    V.verify(lg, mid, img, img.stat().st_size, expected=b"\0", scope="full", completion="commands-ok",
             use_photorec=False)
    return mid


def test_certificate_and_tamper_detection(lg, tmp_path):
    mid = _passed_media(lg, tmp_path)
    r = C.issue(lg, mid, operator="店長", verify_base_url="https://example.invalid/verify")
    data = Path(r["path"]).read_bytes()
    assert data.startswith(b"%PDF") and hashlib.sha256(data).hexdigest() == r["sha256"]
    assert C.verify_document(lg, r["number"], data)
    tampered = bytearray(data)
    tampered[len(tampered) // 2] ^= 0x01
    assert not C.verify_document(lg, r["number"], bytes(tampered))
    html = Path(r["path"]).with_suffix(".html").read_text()
    assert "NIST SP 800-88 Rev.2 の区分" in html and "認証を示すものではありません" in html
    assert "回収 0 件" in html and "data:image/png;base64" in html  # QR
    assert "絶対" not in html


def test_certificate_refused_without_passing_verification(lg, tmp_path, fixtures):
    mid = _register(lg, "FAIL-1", "HDD")
    img = tmp_path / "f.img"
    img.write_bytes((fixtures / "deleted.img").read_bytes())
    V.verify(lg, mid, img, img.stat().st_size, expected=b"\0", use_photorec=False)
    with pytest.raises(EraseError, match="検証に合格していない"):
        C.issue(lg, mid)


def test_verification_page_has_no_personal_data(lg, tmp_path):
    mid = _passed_media(lg, tmp_path, "SECRET-SERIAL-77")
    r = C.issue(lg, mid, pdf=False)
    j, h = C.export_verification_list(lg, tmp_path / "public")
    text = j.read_text() + h.read_text()
    assert r["number"] in text and r["sha256"] in text
    assert "SECRET-SERIAL-77" not in text and "山田商事" not in text


def _photo(tmp_path, name="photo.jpg") -> Path:
    p = tmp_path / name
    Image.new("RGB", (60, 40), "gray").save(p, "JPEG")
    return p


def test_destroy_requires_photo(lg, tmp_path):
    mid = _register(lg, "DEAD-1", "SATA SSD")
    with pytest.raises(EraseError, match="写真"):
        C.destroy(lg, mid, photos=[])
    C.destroy(lg, mid, photos=[str(_photo(tmp_path))])
    r = C.issue(lg, mid, pdf=False)
    assert "Destroy" in Path(r["path"]).read_text()


# ---------------------------------------------------------------- E5
def test_mobile_checklist_gates_certificate(lg, tmp_path):
    mid = _register(lg, "PHONE-IMEI-1", "スマホ")
    with pytest.raises(EraseError, match="チェックリスト"):
        C.issue(lg, mid, pdf=False)
    MC.save(lg, mid, {k: True for k in MC.ITEMS[:-1]})
    assert not MC.is_complete(lg, mid)
    MC.save(lg, mid, {MC.ITEMS[-1]: True})
    assert not MC.is_complete(lg, mid), "写真がないと完了にしない"
    MC.save(lg, mid, {}, photos=[str(_photo(tmp_path))])
    assert MC.is_complete(lg, mid)
    r = C.issue(lg, mid, pdf=False)
    assert "端末標準の初期化" in Path(r["path"]).read_text()


def test_mobile_checklist_rejects_non_phone(lg):
    mid = _register(lg, "HDD-9", "HDD")
    with pytest.raises(EraseError):
        MC.save(lg, mid, {MC.ITEMS[0]: True})


def test_erase_web_checklist_flow(tmp_path):
    from resq_erase.web import create_app

    home = tmp_path / "eh"
    c = TestClient(create_app(home), base_url="http://127.0.0.1")
    assert TestClient(create_app(home), base_url="http://evil.example").get("/").status_code == 403
    r = c.post("/media/new", data={"serial": "IMEI-35000000000001", "kind": "スマホ", "requester": "佐藤",
                                   "origin": "個人", "consent_doc": "承諾書 No.3"}, follow_redirects=False)
    assert r.status_code == 303
    url = r.headers["location"]
    assert c.post(f"{url}/certificate").status_code == 400
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "JPEG")
    form = {f"item_{i}": "on" for i in range(len(MC.ITEMS))}
    r = c.post(f"{url}/checklist", data=form, files={"photo": ("setup.jpg", buf.getvalue(), "image/jpeg")},
               follow_redirects=False)
    assert r.status_code == 303
    assert c.post(f"{url}/certificate", data={"operator": "店長"}, follow_redirects=False).status_code == 303
    page = c.get(url).text
    num = re.search(r"E-\d{8}-\d{4}", page).group(0)
    assert c.get(f"/certificates/{num}").content.startswith(b"%PDF")


# ---------------------------------------------------------------- ビルドの分離
def test_recovery_code_never_imports_erase():
    pat = re.compile(r"^\s*(from|import)\s+resq_erase", re.M)
    offenders = [str(p) for p in (ROOT / "src" / "resq").rglob("*.py") if pat.search(p.read_text())]
    assert offenders == []


def test_recovery_wheel_excludes_erase(tmp_path):
    import subprocess
    import sys
    import zipfile

    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q",
                    "-w", str(tmp_path), str(ROOT)], check=True)
    whl = next(tmp_path.glob("resq-*.whl"))
    names = zipfile.ZipFile(whl).namelist()
    assert any(n.startswith("resq/") for n in names)
    assert not any(n.startswith("resq_erase/") for n in names)
    assert any(n.endswith("templates/catalog.html") for n in names)


# ---------------------------------------------------------------- CLI（復旧側 → 消去側の連携とドライラン）
def test_cli_sync_and_dry_run(tmp_path, monkeypatch, ws):
    from typer.testing import CliRunner

    from resq.cases import create_case
    from resq.cli import app as resq_app
    from resq.intake import add_device
    from resq_erase.cli import app as erase_app

    w, db = ws
    c = create_case(w, db, customer="復旧のお客様")
    add_device(c, kind="HDD", serial="RECOVERY-CASE-9")
    export = tmp_path / "serials.json"
    r = CliRunner().invoke(resq_app, ["export-serials", str(export)])
    assert r.exit_code == 0, r.output
    assert json.loads(export.read_text())["serials"][0]["serial"] == "RECOVERY-CASE-9"

    monkeypatch.setenv("RESQ_ERASE_HOME", str(tmp_path / "station"))
    mock = tmp_path / "mock"
    mock.mkdir()
    (mock / "lsblk.json").write_text(json.dumps(LSBLK))
    (mock / "hdparm_I.txt").write_text(HDPARM_HDD)
    (mock / "hdparm_N.txt").write_text(HPA_OFF)
    run = CliRunner().invoke
    assert run(erase_app, ["sync-blocked", str(export)]).exit_code == 0
    for serial in ("WD-WCC4E1234567", "RECOVERY-CASE-9"):
        r = run(erase_app, ["register", "--serial", serial, "--kind", "HDD", "--requester", "山田商事",
                            "--origin", "法人", "--consent-doc", "No.7", "--location", "棚A"])
        assert r.exit_code == 0, r.output
    r = run(erase_app, ["probe", "WD-WCC4E1234567", "--mock-dir", str(mock)])
    assert r.exit_code == 0 and "Clear" in r.output
    r = run(erase_app, ["erase", "WD-WCC4E1234567", "--mock-dir", str(mock)])
    assert r.exit_code == 0 and "ドライラン" in r.output and "nwipe" in r.output
    r = run(erase_app, ["erase", "RECOVERY-CASE-9", "--mock-dir", str(mock)])
    assert r.exit_code == 1 and "消去禁止" in r.output
