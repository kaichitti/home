"""resq-erase 消去ステーションアプリ（デスクトップ版）。ブラウザもネットワークも使わない。

  左：媒体一覧（受付）
  右：概要 / 消去 / 検証 / 証明書 / スマホ初期化
  上：消去ステーションとして登録済みか（未登録なら消去コマンドは実行されない）
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog,
                               QGridLayout, QGroupBox, QInputDialog, QLineEdit, QMainWindow, QPlainTextEdit,
                               QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from resq.gui.common import (Dialogs, LogPanel, PathEdit, Runner, button, confirm, error, fill, form, hbox,
                             human_bytes, info, label, make_app, noninteractive, open_local, selected_data, table)

from . import __version__
from . import certificate as C
from . import exec as ex
from . import mobile_checklist as MC
from . import probe as P
from . import run as R
from . import verify as V
from .collect import collect, device_size, lsblk_live
from .errors import EraseError
from .ledger import KINDS, ORIGINS, Ledger, station_home

ACCENT = "#8a2f1f"
STATUS_COLOR = {"消去済": "#2e7d32", "物理破壊済": "#2e7d32", "検証不合格": "#b3261e", "保管中": "#1f5f99"}


class RegisterDialog(QDialog):
    def __init__(self, parent, lg: Ledger):
        super().__init__(parent)
        self.lg = lg
        self.media_id = None
        self.setWindowTitle("媒体の受付")
        self.resize(560, 0)
        v = QVBoxLayout(self)
        self.serial, self.requester, self.consent = QLineEdit(), QLineEdit(), QLineEdit()
        self.serial.setPlaceholderText("媒体ラベルのシリアル（必須）")
        self.kind, self.origin = QComboBox(), QComboBox()
        self.kind.addItems(KINDS)
        self.origin.addItems(ORIGINS)
        self.maker, self.model = QLineEdit(), QLineEdit()
        self.dmaker, self.dmodel, self.dserial, self.location = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.location.setPlaceholderText("施錠棚 A-1 など")
        self.photos = PathEdit(filter="写真 (*.jpg *.jpeg *.png)", placeholder="（任意）媒体ラベルの写真")
        v.addWidget(form([("シリアル *", self.serial), ("種別 *", self.kind), ("依頼者 *", self.requester),
                          ("依頼元 *", self.origin), ("消去承諾書", self.consent), ("媒体メーカー", self.maker),
                          ("媒体型番", self.model), ("機器メーカー", self.dmaker), ("機器型番", self.dmodel),
                          ("機器シリアル", self.dserial), ("保管場所", self.location), ("ラベル写真", self.photos)]))
        self.msg = label("", err=True)
        v.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("登録")
        bb.accepted.connect(self.submit)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def submit(self) -> None:
        def t(w):
            return w.text().strip() or None
        try:
            self.media_id = self.lg.register(
                serial=self.serial.text(), kind=self.kind.currentText(), requester=self.requester.text().strip(),
                origin=self.origin.currentText(), consent_doc=t(self.consent), maker=t(self.maker),
                model=t(self.model), device_maker=t(self.dmaker), device_model=t(self.dmodel),
                device_serial=t(self.dserial), location=t(self.location),
                photos=[self.photos.text()] if self.photos.text() else [])
        except Exception as e:  # noqa: BLE001 - シリアル重複なども表示
            self.msg.setText(str(e))
            return
        self.accept()


class EraseWindow(QMainWindow):
    def __init__(self, home: Path | None = None, *, sync: bool = False):
        super().__init__()
        self.home = (home or station_home())
        self.lg = Ledger(self.home)
        self.media_id: int | None = None
        self.plan: R.Plan | None = None
        self.mock_lsblk: dict | None = None
        self.setWindowTitle(f"resq-erase 消去ステーション {__version__}　—　{self.home}")
        self.resize(1240, 860)
        self.log = LogPanel()
        dock = QDockWidget("実行の記録")
        dock.setWidget(self.log)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.runner = Runner(self, self.log, sync=sync)

        root = QWidget()
        rv = QVBoxLayout(root)
        self.banner = label("")
        rv.addWidget(self.banner)
        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(button("＋ 媒体の受付", self.register, primary=True))
        self.media = table(["#", "シリアル", "種別", "状態", "保管場所"], stretch_col=1)
        self.media.itemSelectionChanged.connect(self.on_select)
        lv.addWidget(self.media, 1)
        sp.addWidget(left)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._overview(), "概要")
        self.tabs.addTab(self._erase(), "消去")
        self.tabs.addTab(self._verify(), "検証")
        self.tabs.addTab(self._cert(), "証明書")
        self.tabs.addTab(self._phone(), "スマホ初期化")
        self.stack = QStackedWidget()
        empty = label("左の一覧から媒体を選ぶか、「媒体の受付」で登録してください。", muted=True)
        empty.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(empty)
        self.stack.addWidget(self.tabs)
        sp.addWidget(self.stack)
        sp.setSizes([380, 860])
        rv.addWidget(sp, 1)
        self.setCentralWidget(root)
        self._menu()
        self.refresh()

    # ------------------------------------------------------------ 画面の組み立て
    def _overview(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.ov_title = label("")
        self.ov_title.setStyleSheet("font-size: 15pt; font-weight: bold;")
        v.addWidget(self.ov_title)
        self.ov_blocked = label("", err=True)
        v.addWidget(self.ov_blocked)
        g = QGroupBox("媒体")
        self.ov_grid = QGridLayout(g)
        v.addWidget(g)
        g2 = QGroupBox("記録写真")
        g2v = QVBoxLayout(g2)
        self.ov_photos = label("", muted=True)
        g2v.addWidget(self.ov_photos)
        g2v.addWidget(hbox(button("写真を追加…", self.add_photos)))
        v.addWidget(g2)
        v.addStretch(1)
        return w

    def _erase(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g1 = QGroupBox("1. 識別と方式の選択（読み取りのみ）")
        g1v = QVBoxLayout(g1)
        self.mock = PathEdit(directory=True, placeholder="（訓練用）識別出力のモックのフォルダ。空なら接続中の媒体を読む")
        g1v.addWidget(form([("識別データ", self.mock)]))
        g1v.addWidget(hbox(button("識別する", self.do_probe, primary=True)))
        self.probe_out = QPlainTextEdit()
        self.probe_out.setReadOnly(True)
        self.probe_out.setMinimumHeight(180)
        g1v.addWidget(self.probe_out)
        v.addWidget(g1)
        g2 = QGroupBox("2. 実行（既定はドライラン。実行にはシリアル下 4 桁の入力が必要）")
        g2v = QVBoxLayout(g2)
        self.operator = QLineEdit()
        g2v.addWidget(form([("作業者", self.operator)]))
        self.btn_dry = button("ドライラン（実行予定コマンドの確認）", self.do_dryrun)
        self.btn_exec = button("消去を実行…", self.do_execute, danger=True)
        g2v.addWidget(hbox(self.btn_dry, self.btn_exec))
        self.exec_note = label("", muted=True)
        g2v.addWidget(self.exec_note)
        v.addWidget(g2)
        v.addStretch(1)
        return w

    def _verify(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("検証：読み戻し検査と、当店の復旧手法による復旧試行（回収 0 件で合格）")
        gv = QVBoxLayout(g)
        self.target = PathEdit(placeholder="消去した媒体のデバイス（/dev/sdX）またはそのイメージファイル")
        self.scope = QComboBox()
        self.scope.addItem("サンプリング（先頭・末尾＋無作為）", "sample")
        self.scope.addItem("全域", "full")
        self.expected = QComboBox()
        for t, k in (("自動（上書き方式ならゼロ）", "auto"), ("ゼロであること", "zero"), ("指定しない（暗号消去など）", "none")):
            self.expected.addItem(t, k)
        gv.addWidget(form([("対象", self.target), ("範囲", self.scope), ("期待する内容", self.expected)]))
        gv.addWidget(hbox(button("検証する", self.do_verify, primary=True)))
        v.addWidget(g)
        self.vers = table(["日時", "完了ステータス", "読み戻し", "復旧試行", "結果"], stretch_col=0)
        v.addWidget(self.vers, 1)
        return w

    def _cert(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("消去証明書（検証合格・物理破壊・初期化代行の完了のいずれかが必要）")
        gv = QVBoxLayout(g)
        self.verify_url = QLineEdit()
        self.verify_url.setPlaceholderText("（任意）照合ページの URL。QR コードに入れる")
        self.cert_operator = QLineEdit()
        gv.addWidget(form([("照合ページ", self.verify_url), ("作業者", self.cert_operator)]))
        gv.addWidget(hbox(button("証明書を発行", self.do_cert, primary=True),
                          button("物理破壊を記録…", self.do_destroy, danger=True)))
        v.addWidget(g)
        self.certs = table(["番号", "発行", "SHA-256"], stretch_col=2)
        v.addWidget(self.certs, 1)
        v.addWidget(hbox(button("選んだ証明書を開く", self.open_cert)))
        return w

    def _phone(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("スマホ初期化代行チェックリスト（全項目と写真が揃うまで証明書は発行できません）")
        gv = QVBoxLayout(g)
        self.items = [QCheckBox(t) for t in MC.ITEMS]
        for cb in self.items:
            gv.addWidget(cb)
        self.phone_photos = label("", muted=True)
        gv.addWidget(self.phone_photos)
        gv.addWidget(hbox(button("写真を追加…", self.add_phone_photos), button("保存", self.save_phone, primary=True)))
        v.addWidget(g)
        self.phone_note = label("", muted=True)
        v.addWidget(self.phone_note)
        v.addStretch(1)
        return w

    def _menu(self) -> None:
        m = self.menuBar().addMenu("管理")
        for text, slot in (("消去禁止シリアルの取り込み…", self.sync_blocked), ("台数照合…", self.inventory),
                           ("妥当性確認の記録…", self.record_validation), ("妥当性確認の実績表", self.validation_report),
                           ("照合ページの書き出し…", self.export_verify),
                           ("データのフォルダを開く", lambda: open_local(self.home))):
            a = QAction(text, self)
            a.triggered.connect(slot)
            m.addAction(a)

    # ------------------------------------------------------------ 表示の更新
    def refresh(self) -> None:
        sid = ex.station_id()
        if sid:
            self.banner.setText(f"消去ステーションとして登録済み（{sid}）")
            self.banner.setStyleSheet("background:#e6f2e7; color:#1b5e20; padding:6px; border-radius:4px;")
        else:
            self.banner.setText("このパソコンは消去ステーションとして登録されていません。消去コマンドは実行されません（ドライランのみ）。")
            self.banner.setStyleSheet("background:#fff3dc; color:#7a4a00; padding:6px; border-radius:4px;")
        rows = self.lg.all("SELECT * FROM media ORDER BY id DESC")
        self.media.blockSignals(True)
        fill(self.media, [[r["id"], r["serial"], r["kind"], r["status"], r["location"] or "—"] for r in rows],
             data=[r["id"] for r in rows], colors={3: lambda s: STATUS_COLOR.get(s)})
        for i, r in enumerate(rows):
            if r["id"] == self.media_id:
                self.media.selectRow(i)
        self.media.blockSignals(False)
        if self.media_id is None:
            self.stack.setCurrentIndex(0)
            return
        m = self.lg.one("SELECT * FROM media WHERE id=?", self.media_id)
        self.stack.setCurrentIndex(1)
        self.ov_title.setText(f"媒体 #{m['id']}　{m['kind']}　{m['serial']}　［{m['status']}］")
        reason = self.lg.blocked_reason(m["serial"])
        self.ov_blocked.setText(f"消去禁止：{reason}" if reason else "")
        while self.ov_grid.count():
            self.ov_grid.takeAt(0).widget().deleteLater()
        cells = [("依頼者", f"{m['requester']}（{m['origin']}）"), ("承諾書", m["consent_doc"] or "—"),
                 ("保管場所", m["location"] or "—"), ("媒体", f"{m['maker'] or ''} {m['model'] or ''}".strip() or "—"),
                 ("機器", f"{m['device_maker'] or ''} {m['device_model'] or ''} {m['device_serial'] or ''}".strip() or "—"),
                 ("受付", m["received_at"][:16].replace("T", " "))]
        for i, (k, val) in enumerate(cells):
            self.ov_grid.addWidget(label(k, muted=True), i // 3 * 2, i % 3)
            self.ov_grid.addWidget(label(val), i // 3 * 2 + 1, i % 3)
        photos = json.loads(m["photos"] or "[]")
        self.ov_photos.setText("\n".join(photos) or "（なし）")
        vers = self.lg.all("SELECT * FROM verifications WHERE media_id=? ORDER BY id DESC", self.media_id)
        fill(self.vers, [[x["created_at"][:16].replace("T", " "), x["completion"] or "—",
                          f"{x['readback_scope']}：{'兆候なし' if x['readback_ok'] else '残存の兆候あり'}",
                          f"回収 {x['recovered']} 件", "合格" if x["passed"] else "不合格"] for x in vers],
             colors={4: lambda s: "#2e7d32" if s == "合格" else "#b3261e"})
        certs = self.lg.all("SELECT * FROM certificates WHERE media_id=? ORDER BY id DESC", self.media_id)
        fill(self.certs, [[c["number"], c["issued_at"][:16].replace("T", " "), c["sha256"]] for c in certs],
             data=[c["path"] for c in certs])
        phone = m["kind"] == "スマホ"
        self.tabs.setTabEnabled(4, phone)
        if phone:
            cl = MC.get(self.lg, self.media_id)
            for cb in self.items:
                cb.setChecked(cl["items"][cb.text()])
            self.phone_photos.setText(f"写真 {len(cl['photos'])} 枚：" + (", ".join(Path(p).name for p in cl["photos"])
                                                                         or "なし"))
            self.phone_note.setText("すべて揃っています。「証明書」タブで発行できます。"
                                    if MC.is_complete(self.lg, self.media_id) else "未完了")
        can_exec = ex.station_id() is not None and self.plan is not None and self.plan.method.executable
        self.btn_exec.setEnabled(can_exec)
        self.exec_note.setText("" if can_exec else
                               ("先に「ドライラン」で方式と対象を確認してください" if self.plan is None else
                                "この方式は実行できません（要対応の事項あり）" if not self.plan.method.executable else
                                "消去ステーションとして登録されていないため実行できません"))

    def on_select(self) -> None:
        mid = selected_data(self.media)
        if mid is not None and mid != self.media_id:
            self.media_id = mid
            self.plan = None
            self.probe_out.clear()
            self.refresh()

    def current(self):
        return self.lg.one("SELECT * FROM media WHERE id=?", self.media_id)

    # ------------------------------------------------------------ 操作
    def register(self) -> None:
        dlg = RegisterDialog(self, self.lg)
        if dlg.exec() and dlg.media_id:
            self.log.add(f"媒体 #{dlg.media_id} を受付しました")
            self.media_id = dlg.media_id
            self.refresh()

    def _probe(self):
        m = self.current()
        mock = Path(self.mock.text()) if self.mock.text() else None
        lsblk, outs = collect(self.lg, m["serial"], mock)
        p = P.probe_from_outputs(m["serial"], lsblk=lsblk, declared_kind=m["kind"], **outs)
        return lsblk, p

    def do_probe(self) -> None:
        try:
            lsblk, p = self._probe()
        except Exception as e:  # noqa: BLE001
            error(self, "識別", str(e))
            return
        try:
            dev, _ = R.resolve_device(lsblk, p.serial or "")
        except EraseError:
            dev = "（未接続）"
        meth = P.select_method(p, dev)
        lines = [f"媒体の種類：{p.media}（接続 {p.transport or '—'}・回転 {p.rotational}）",
                 f"方式：{meth.category or '—'}　{meth.name}"]
        lines += [f"  $ {' '.join(c)}" for c in meth.commands]
        lines += [f"要対応：{b}" for b in meth.blockers] + [f"注意：{n}" for n in meth.notes]
        self.probe_out.setPlainText("\n".join(lines))

    def do_dryrun(self) -> None:
        try:
            lsblk, p = self._probe()
            self.mock_lsblk = lsblk if self.mock.text() else None
            self.plan = R.plan(self.lg, self.current()["serial"], p, P.select_method, lsblk=lsblk,
                               operator=self.operator.text().strip())
        except EraseError as e:
            self.plan = None
            error(self, "ドライラン", str(e))
            self.refresh()
            return
        cmds = "\n".join("  $ " + " ".join(c) for c in self.plan.commands) or "（実行するコマンドなし）"
        self.probe_out.setPlainText(f"[ドライラン] 対象 {self.plan.device}（シリアル {self.current()['serial']}）\n"
                                    f"{self.plan.method.category or '—'}　{self.plan.method.name}\n{cmds}\n"
                                    + "\n".join(f"要対応：{b}" for b in self.plan.method.blockers))
        self.log.add(f"ドライラン：{self.plan.method.name}（実行はしていません）")
        self.refresh()

    def do_execute(self) -> None:
        if self.plan is None:
            return
        serial = self.plan.media["serial"]
        last4, ok = QInputDialog.getText(self, "消去の実行",
                                         f"{self.plan.device} を {self.plan.method.name} で消去します。元に戻せません。\n"
                                         "媒体ラベルのシリアル下 4 桁を入力してください：")
        if not ok:
            return
        plan, home, op = self.plan, self.home, self.operator.text().strip()
        mock = self.mock_lsblk

        def job(stream):
            lg = Ledger(home)
            try:
                return R.execute(lg, plan, confirm_last4=last4,
                                 get_lsblk=(lambda: mock) if mock else (lambda: lsblk_live(lg)), operator=op)
            finally:
                lg.close()
        self.runner.start(f"消去の実行（{serial}）", job, lambda rid: (self.log.add(f"実行記録 #{rid}。続けて検証してください"),
                                                                 self.tabs.setCurrentIndex(2), self.refresh()))

    def do_verify(self) -> None:
        tgt = self.target.text()
        if not tgt:
            error(self, "検証", "対象を指定してください")
            return
        m = self.current()
        home, mid = self.home, m["id"]
        exp_key = self.expected.currentData()
        scope = self.scope.currentData()

        def job(stream):
            lg = Ledger(home)
            try:
                run = lg.one("SELECT * FROM runs WHERE media_id=? AND dry_run=0 ORDER BY id DESC LIMIT 1", mid)
                exp = {"zero": b"\0", "none": None}.get(exp_key)
                if exp_key == "auto":
                    exp = b"\0" if run and ("上書き" in run["method"] or "Overwrite" in run["method"]) else None
                return V.verify(lg, mid, tgt, device_size(lg, tgt), expected=exp, scope=scope,
                                completion=run["completion"] if run else None, run_id=run["id"] if run else None,
                                allow_device=tgt.startswith("/dev/"))
            finally:
                lg.close()
        self.runner.start("検証", job, lambda r: (info(self, "検証の結果",
                                                     ("合格" if r["passed"] else "不合格")
                                                     + f"\n読み戻し：{'兆候なし' if r['readback']['ok'] else '残存の兆候あり'}"
                                                     + f"\n復旧試行：回収 {r['recovery']['recovered']} 件"), self.refresh()))

    def do_cert(self) -> None:
        try:
            r = C.issue(self.lg, self.media_id, operator=self.cert_operator.text().strip(),
                        verify_base_url=self.verify_url.text().strip() or None)
            info(self, "証明書を発行しました", f"{r['number']}\n{r['path']}")
        except EraseError as e:
            error(self, "証明書", str(e))
        self.refresh()

    def do_destroy(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "破壊後の写真", str(Path.home()), "写真 (*.jpg *.jpeg *.png)")
        if not files:
            return
        if not confirm(self, "物理破壊", "この媒体を物理破壊済みとして記録します。よろしいですか？"):
            return
        try:
            C.destroy(self.lg, self.media_id, photos=self._store_photos(files, "destroy"),
                      operator=self.cert_operator.text().strip())
        except EraseError as e:
            error(self, "物理破壊", str(e))
        self.refresh()

    def open_cert(self) -> None:
        p = selected_data(self.certs)
        if p:
            open_local(p)

    def _store_photos(self, files: list[str], prefix: str) -> list[str]:
        d = self.home / "photos" / str(self.media_id)
        d.mkdir(parents=True, exist_ok=True)
        out = []
        for f in files:
            dest = d / f"{prefix}_{len(list(d.iterdir())) + 1:03d}{Path(f).suffix.lower()}"
            shutil.copyfile(f, dest)
            out.append(str(dest))
        return out

    def add_photos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "写真", str(Path.home()), "写真 (*.jpg *.jpeg *.png)")
        if files:
            m = self.current()
            photos = json.loads(m["photos"] or "[]") + self._store_photos(files, "label")
            self.lg.execute("UPDATE media SET photos=? WHERE id=?", json.dumps(photos, ensure_ascii=False), m["id"])
            self.refresh()

    def add_phone_photos(self, files: list[str] | None = None) -> None:
        if not files:
            files, _ = QFileDialog.getOpenFileNames(self, "写真", str(Path.home()), "写真 (*.jpg *.jpeg *.png)")
        if files:
            MC.save(self.lg, self.media_id, {}, self._store_photos(files, "phone"))
            self.refresh()

    def save_phone(self) -> None:
        try:
            MC.save(self.lg, self.media_id, {cb.text(): cb.isChecked() for cb in self.items})
        except EraseError as e:
            error(self, "チェックリスト", str(e))
        self.refresh()

    def sync_blocked(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "復旧側が書き出したファイル（serials.json）", str(Path.home()),
                                           "JSON (*.json)")
        if p:
            n = self.lg.sync_blocked_from_resq(Path(p))
            info(self, "取り込み", f"消去禁止シリアル {n} 件を取り込みました")
            self.refresh()

    def inventory(self) -> None:
        text, ok = QInputDialog.getMultiLineText(self, "台数照合", "棚にある媒体のシリアルを 1 行に 1 つずつ入力：")
        if ok:
            r = self.lg.inventory_check([s for s in text.splitlines() if s.strip()])
            info(self, "台数照合", f"照合 OK：{len(r['ok'])} 台\n見当たらない：{', '.join(r['missing']) or 'なし'}\n"
                                   f"台帳に無い：{', '.join(r['unregistered']) or 'なし'}")

    def record_validation(self) -> None:
        model, ok = QInputDialog.getText(self, "妥当性確認", "型番：")
        if not ok or not model:
            return
        kind, ok = QInputDialog.getItem(self, "妥当性確認", "種別：", list(KINDS), 0, False)
        method, ok2 = QInputDialog.getText(self, "妥当性確認", "方式：")
        planted, ok3 = QInputDialog.getInt(self, "妥当性確認", "書き込んだ既知ファイル数：", 50, 1, 100000)
        recovered, ok4 = QInputDialog.getInt(self, "妥当性確認", "復旧試行で回収された件数：", 0, 0, 100000)
        if ok and ok2 and ok3 and ok4:
            V.record_validation(self.lg, model=model, kind=kind, method=method, planted_files=planted,
                                recovered=recovered, operator=self.operator.text().strip())
            info(self, "妥当性確認", "記録しました" + ("" if recovered == 0 else "（不合格：方式を見直してください）"))

    def validation_report(self) -> None:
        rows = V.validation_table(self.lg)
        info(self, "妥当性確認の実績表", "\n".join(
            f"{r['model']}／{r['method']}：{r['passes']}/{r['runs']} 合格（最終 {r['last'][:10]}）"
            f"{'' if r['all_passed'] else '　要見直し'}" for r in rows) or "まだ記録がありません")

    def export_verify(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "照合ページの書き出し先")
        if d:
            j, h = C.export_verification_list(self.lg, Path(d))
            info(self, "照合ページ", f"{j}\n{h}\n（証明書番号・発行日・SHA-256 のみ。個人情報は含みません）")

    def closeEvent(self, e) -> None:  # noqa: N802
        if self.runner.busy and not confirm(self, "終了", "処理を実行中です。終了しますか？"):
            e.ignore()
            return
        self.lg.close()
        super().closeEvent(e)


def selftest(out: Path) -> int:
    """画面を組み立てて 受付→識別（モック）→ドライラン→実行拒否→スマホのチェックリスト→証明書 を通す。"""
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"ok": False}
    try:
        make_app(sys.argv, ACCENT)
        noninteractive()
        win = EraseWindow(out / "station", sync=True)
        win.show()
        hdd = win.lg.register(serial="SELFTEST-HDD-1", kind="HDD", requester="動作確認", origin="法人",
                              consent_doc="No.1", location="棚 A-1")
        mock = out / "mock"
        mock.mkdir(exist_ok=True)
        (mock / "lsblk.json").write_text(json.dumps({"blockdevices": [
            {"name": "sdb", "serial": "SELFTEST-HDD-1", "model": "TEST", "size": 1000204886016, "tran": "sata",
             "rota": True, "rm": False, "type": "disk"}]}), encoding="utf-8")
        (mock / "hdparm_N.txt").write_text(" max sectors = 100/100, HPA is disabled\n", encoding="utf-8")
        win.media_id = hdd
        win.refresh()
        win.mock.setText(str(mock))
        win.do_dryrun()
        result["dryrun"] = bool(win.plan and win.plan.commands and win.plan.commands[0][0] == "nwipe")
        result["exec_disabled"] = not win.btn_exec.isEnabled()  # 登録されていないステーションでは押せない
        phone = win.lg.register(serial="SELFTEST-PHONE-1", kind="スマホ", requester="動作確認", origin="個人",
                                consent_doc="No.2")
        win.media_id = phone
        win.refresh()
        for cb in win.items:
            cb.setChecked(True)
        win.save_phone()
        from PIL import Image

        photo = out / "setup.jpg"
        Image.new("RGB", (40, 30), "white").save(photo)
        win.add_phone_photos([str(photo)])
        win.tabs.setCurrentIndex(4)
        win.grab().save(str(out / "resq-erase-gui.png"))
        win.do_cert()
        result["certificate"] = win.certs.rowCount() == 1
        result["messages"] = Dialogs.shown
        result["ok"] = result["dryrun"] and result["certificate"] and (result["exec_disabled"] or ex.station_id())
        win.close()
    except Exception as e:  # noqa: BLE001
        import traceback

        result["error"] = f"{e}\n{traceback.format_exc()}"
    (out / "selftest.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    from resq.gui.common import setup_offscreen_if_requested

    argv = list(sys.argv if argv is None else argv)
    setup_offscreen_if_requested(argv)
    if "--selftest" in argv:
        return selftest(Path(argv[argv.index("--selftest") + 1]))
    app = make_app(argv, ACCENT)
    win = EraseWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
