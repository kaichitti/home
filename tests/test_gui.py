"""デスクトップアプリ（復旧 resq-gui・消去ステーション resq-erase-gui）のテスト。

画面のない環境（offscreen）で、実際のウィンドウ・ボタン・入力欄を操作して確認する。
処理は同期実行（Runner(sync=True)）にして結果を決定的にする。メッセージは表示せず記録する。
"""
from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

from resq.config import Workspace
from resq.gui import common
from resq.gui.app import ACCENT, MainWindow
from resq.gui.dialogs import ConfirmStepsDialog, IntakeDialog

DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def qapp():
    return common.make_app(["test"], ACCENT)


@pytest.fixture
def win(qapp, tmp_path):
    common.noninteractive(confirm_answer=True)
    w = MainWindow(Workspace(tmp_path / "ws"), sync=True)
    yield w
    w.db.close()
    w.deleteLater()


def _errors():
    return [m for m in common.Dialogs.shown if m[0] == "error"]


def _new_case(win, **kw) -> str:
    dlg = IntakeDialog(win, win.ws, win.db)
    dlg.customer.setText(kw.get("customer", "鈴木 一郎"))
    dlg.price_cap.setValue(9800)
    if "ownership" in kw:
        dlg.ownership.setCurrentText(kw["ownership"])
    if "request" in kw:
        dlg.request.setText(kw["request"])
    dlg.kind.setCurrentText("USB メモリ")
    dlg.serial.setText("4C5300012301")
    dlg.submit()
    if dlg.case is None:
        return dlg.message.text()
    win.select_case(dlg.case.id)
    return dlg.case.id


def test_intake_validation_in_dialog(win):
    assert "権限者の同意書面" in _new_case(win, ownership="法人所有（権限者の同意書面あり）")
    assert "ロック解除" in _new_case(win, request="パスコード解除をお願いしたい")
    assert win.db.one("SELECT COUNT(*) AS n FROM cases")["n"] == 0, "失敗した受付で半端な案件を残さない"
    cid = _new_case(win)
    assert cid.startswith("R") and win.cases.rowCount() == 1
    assert "鈴木 一郎" in win.overview.title.text()
    assert win.overview.devices.rowCount() == 1


def test_only_defined_transitions_are_offered(win):
    _new_case(win)
    buttons = [win.overview.trans.itemAt(i).widget() for i in range(win.overview.trans.count())]
    texts = [b.text() for b in buttons if b is not None and hasattr(b, "clicked")]
    assert texts == ["→ 診断済", "→ キャンセル"]
    next(b for b in buttons if b is not None and getattr(b, "text", lambda: "")() == "→ 診断済").click()
    assert win.case().row["status"] == "診断済"


def test_full_flow_through_the_window(win, fixtures, expected, ro, tmp_path):
    cid = _new_case(win)
    src = ro(fixtures / "qf_nested.img")
    w = win.work
    w.source.setText(str(src))
    w.smart.setText(str(DATA / "smart_healthy.json"))
    w.do_diagnose()
    assert "自社" in win.overview.diag.itemAt(0).widget().text()
    w.do_image()
    assert w.rec_image.count() == 1 and "完了" in w.rec_image.itemText(0)
    w.use_testdisk.setChecked(False)
    w.do_recover()
    assert not _errors(), _errors()
    # 全ファイルが中身（SHA-256）一致で一覧に出る。ルート直下の KEEP.PDF はクイックフォーマットで
    # 名前が消えるため、カービング（名前なし・ランク B）で戻る
    ids = {int(win.files.t.item(i, 1).text()) for i in range(win.files.t.rowCount())}
    shown_sha = {r["sha256"] for r in win.db.all("SELECT * FROM recovered_files WHERE case_id=?", cid)
                 if r["id"] in ids}
    for f in expected["images"]["qf_nested"]["files"]:
        assert f["sha256"] in shown_sha, f["name"]
    names = [win.files.t.item(i, 3).text() for i in range(win.files.t.rowCount())]
    assert "memo notes.docx" in names and "Family Trip 01.jpg" in names
    # 表示はお客様向けの言葉（内部の記号を出さない）
    shown = {win.files.t.item(i, 7).text() for i in range(win.files.t.rowCount())}
    assert shown <= {"開ける", "一部破損", "未確認"} and "OK" not in shown
    paths = [win.files.t.item(i, 4).text() for i in range(win.files.t.rowCount())]
    assert not any("不明フォルダ_c" in p for p in paths)

    # 納品対象：1 件だけチェックを外して保存
    win.files.select_ab()
    n_ab = win.db.one("SELECT COUNT(*) AS n FROM recovered_files WHERE case_id=? AND selected=1", cid)["n"]
    win.files.t.item(0, 0).setCheckState(Qt.Unchecked)
    win.files.save_selection()
    assert win.db.one("SELECT COUNT(*) AS n FROM recovered_files WHERE case_id=? AND selected=1", cid)["n"] == n_ab - 1

    win.files.build_catalog()
    assert (win.case().dir / "catalog" / "list.pdf").exists()

    media = tmp_path / "usb"
    media.mkdir()
    win.deliver_tab.target.setText(str(media))
    win.deliver_tab.operator.setText("店長")
    win.deliver_tab.do_deliver()
    assert not _errors(), _errors()
    assert win.case().row["status"] == "納品済" and win.deliver_tab.deliveries.rowCount() == 1

    win.deliver_tab.wipe_exec()  # 確認ダイアログは「はい」（テスト設定）
    assert not _errors(), _errors()
    assert win.case().row["status"] == "消去済" and win.deliver_tab.certs.rowCount() == 1
    assert not win.case().dir.exists()
    win.refresh(tab=4)
    assert win.events.t.rowCount() > 10


def test_wipe_is_not_done_when_user_says_no(win, fixtures, ro, tmp_path):
    from resq import deliver, image as I
    from resq.recover import pipeline

    cid = _new_case(win)
    c = win.case()
    I.register_existing(c, ro(fixtures / "deleted.img"))
    pipeline.run(c, stages=("S1", "S2"), use_testdisk=False)
    c.set_status("キャンセル") if c.row["status"] == "受付" else None
    common.Dialogs.confirm_answer = False
    win.refresh()
    win.deliver_tab.wipe_exec()
    assert win.case().dir.exists() and win.case().row["status"] == "キャンセル"
    assert deliver  # noqa: B018


def test_recovery_key_is_cleared_from_the_screen(win, fixtures, ro, tmp_path, monkeypatch):
    from resq import image as I

    _new_case(win)
    I.register_existing(win.case(), ro(fixtures / "deleted.img"))
    win.refresh()
    w = win.work
    assert w.key.echoMode() == QLineEdit.Password
    captured = {}
    monkeypatch.setattr("resq.gui.tasks.run_unlock",
                        lambda root, cid, iid, key, kind, part, s: captured.setdefault("key", key) and 0)
    w.unlock_image.setCurrentIndex(0)
    w.key.setText("123456-654321")
    w.do_unlock()
    assert w.key.text() == "" and captured["key"] == "123456-654321"


def test_mobile_requires_every_owner_step(qapp):
    from resq.mobile import android

    dlg = ConfirmStepsDialog(None, "Android", android.STEPS, "シリアル")
    ok = dlg.bb.button(dlg.bb.StandardButton.Ok)
    dlg.ident.setText("R58M123")
    for c in dlg.checks[:-1]:
        c.setChecked(True)
    assert not ok.isEnabled()
    dlg.checks[-1].setChecked(True)
    assert ok.isEnabled()


def test_selftest_mode(qapp, fixtures, tmp_path):
    from resq.gui.app import selftest

    assert selftest(fixtures, tmp_path / "st") == 0
    res = json.loads((tmp_path / "st" / "selftest.json").read_text(encoding="utf-8"))
    assert res["ok"] and not res["missing"] and (tmp_path / "st" / "resq-gui.png").exists()


# ---------------------------------------------------------------- 消去ステーション
@pytest.fixture
def ewin(qapp, tmp_path):
    from resq_erase.gui import EraseWindow

    common.noninteractive(confirm_answer=True)
    w = EraseWindow(tmp_path / "station", sync=True)
    yield w
    w.lg.close()
    w.deleteLater()


def _mock_dir(tmp_path, serial="WD-WCC4E1234567") -> Path:
    d = tmp_path / "mock"
    d.mkdir(exist_ok=True)
    (d / "lsblk.json").write_text(json.dumps({"blockdevices": [
        {"name": "sdb", "serial": serial, "model": "WDC", "size": 1000204886016, "tran": "sata", "rota": True,
         "rm": False, "type": "disk"}]}), encoding="utf-8")
    (d / "hdparm_N.txt").write_text(" max sectors = 1/1, HPA is disabled\n", encoding="utf-8")
    return d


def test_erase_station_dry_run_and_execute_guard(ewin, tmp_path, monkeypatch):
    from resq_erase import exec as ex

    mid = ewin.lg.register(serial="WD-WCC4E1234567", kind="HDD", requester="山田商事", origin="法人",
                           consent_doc="No.7", location="棚 A-1")
    ewin.media_id = mid
    ewin.refresh()
    assert "登録されていません" in ewin.banner.text()
    ewin.mock.setText(str(_mock_dir(tmp_path)))
    ewin.do_probe()
    assert "Clear" in ewin.probe_out.toPlainText()
    ewin.do_dryrun()
    assert "[ドライラン]" in ewin.probe_out.toPlainText() and "nwipe" in ewin.probe_out.toPlainText()
    assert not ewin.btn_exec.isEnabled(), "消去ステーションとして登録されていなければ押せない"
    # 登録済みのステーションでも、シリアル下 4 桁を間違えれば実行されない
    marker = tmp_path / "marker"
    marker.write_text("ST-01")
    monkeypatch.setattr(ex, "STATION_MARKER", marker)
    monkeypatch.setenv("RESQ_ERASE_STATION_ID", "ST-01")
    ewin.refresh()
    assert ewin.btn_exec.isEnabled() and "登録済み" in ewin.banner.text()
    ran = []
    monkeypatch.setattr(ex.subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr("resq_erase.gui.QInputDialog.getText", lambda *a, **k: ("0000", True))
    ewin.do_execute()
    assert ran == [], "消去コマンドを実行していない"
    assert any("下 4 桁" in m[2] for m in common.Dialogs.shown if m[0] == "error")


def test_erase_station_blocked_serial(ewin, tmp_path):
    mid = ewin.lg.register(serial="RECOVERY-CASE-9", kind="HDD", requester="x", origin="法人", consent_doc="c")
    export = tmp_path / "serials.json"
    export.write_text(json.dumps({"serials": [{"serial": "RECOVERY-CASE-9", "case_id": "R2611-0003"}]}),
                      encoding="utf-8")
    ewin.lg.sync_blocked_from_resq(export)
    ewin.media_id = mid
    ewin.refresh()
    assert "消去禁止" in ewin.ov_blocked.text()
    ewin.mock.setText(str(_mock_dir(tmp_path, "RECOVERY-CASE-9")))
    ewin.do_dryrun()
    assert ewin.plan is None and any("R2611-0003" in m[2] for m in common.Dialogs.shown)


def test_erase_station_phone_checklist_and_certificate(ewin, tmp_path):
    mid = ewin.lg.register(serial="IMEI-1", kind="スマホ", requester="伊藤", origin="個人", consent_doc="No.22")
    ewin.media_id = mid
    ewin.refresh()
    assert ewin.tabs.isTabEnabled(4)
    for cb in ewin.items[:-1]:
        cb.setChecked(True)
    ewin.save_phone()
    ewin.do_cert()
    assert ewin.certs.rowCount() == 0 and any("チェックリスト" in m[2] for m in common.Dialogs.shown)
    ewin.items[-1].setChecked(True)
    ewin.save_phone()
    photo = tmp_path / "p.jpg"
    Image.new("RGB", (20, 20)).save(photo)
    ewin.add_phone_photos([str(photo)])
    ewin.do_cert()
    assert ewin.certs.rowCount() == 1


def test_erase_selftest_mode(qapp, tmp_path):
    from resq_erase.gui import selftest

    assert selftest(tmp_path / "est") == 0


# ---------------------------------------------------------------- 完全ローカル
NETWORK_MODULES = {"socket", "http", "urllib", "requests", "httpx", "aiohttp", "websockets", "fastapi", "uvicorn",
                   "starlette", "webbrowser", "smtplib", "ftplib", "PySide6.QtNetwork", "PySide6.QtWebEngineWidgets"}


def test_no_network_code_in_the_apps():
    """アプリのコードは通信・待ち受け・ブラウザ起動の部品を一切読み込まない。"""
    bad = []
    for f in [*(ROOT / "src" / "resq").rglob("*.py"), *(ROOT / "src" / "resq_erase").rglob("*.py")]:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for n in names:
                if n in NETWORK_MODULES or n.split(".")[0] in NETWORK_MODULES:
                    bad.append(f"{f.name}:{node.lineno} {n}")
    assert bad == []
