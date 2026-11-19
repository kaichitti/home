"""resq 復旧アプリ（デスクトップ版）。ブラウザもネットワークも使わない。

  左：案件一覧（検索・状態で絞り込み）
  右：案件の詳細タブ（概要 / 作業 / 復旧ファイル / 納品・消去 / 操作ログ）
  下：実行した処理の記録
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLineEdit, QMainWindow, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
                               QTabWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import __version__, catalog, deliver, diagnose, intake, wipe, workspace_crypt
from ..cases import STATES, TRANSITIONS, get_case, open_workspace
from ..config import Workspace
from ..errors import ResqError
from ..recover import STAGES, stage_label
from ..validate import KIND_LABEL
from ..recover.ingest import ALLOWED_ENGINES
from ..unlock import TYPES as UNLOCK_TYPES
from . import tasks
from .common import (RANK_COLOR, VERDICT_COLOR, Dialogs, LogPanel, PathEdit, Runner, button, confirm, error, fill, form,
                     hbox, human_bytes, info, label, make_app, noninteractive, open_local, selected_data, table)
from .dialogs import ConfirmStepsDialog, DeviceDialog, DevicePickerDialog, IntakeDialog

ACCENT = "#1f5f99"
RANK_LABEL = {"A": "A 名前付き・開ける", "B": "B 名前なし・開ける", "C": "C 一部破損", "D": "D サムネイル",
              "U": "U 要確認"}
IS_LINUX = sys.platform.startswith("linux")


def _scroll(w: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setWidget(w)
    return s


# ======================================================================== 概要
class OverviewTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        self.title = label("")
        self.title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        v.addWidget(self.title)
        g = QGroupBox("お客様・同意")
        self.grid = QGridLayout(g)
        v.addWidget(g)
        g2 = QGroupBox("状態の変更（決められた順序でのみ変えられます）")
        self.trans = QHBoxLayout(g2)
        v.addWidget(g2)
        g3 = QGroupBox("お預かり媒体")
        v3 = QVBoxLayout(g3)
        self.devices = table(["#", "種別", "メーカー / 型番", "シリアル", "症状"], stretch_col=4)
        self.devices.setMaximumHeight(150)
        v3.addWidget(self.devices)
        v3.addWidget(hbox(button("媒体を追加…", self.add_device)))
        v.addWidget(g3)
        g4 = QGroupBox("診断")
        self.diag = QVBoxLayout(g4)
        v.addWidget(g4)
        v.addStretch(1)

    def refresh(self, c) -> None:
        r = c.row
        self.title.setText(f"{r['id']}　{r['customer']} 様　［{r['status']}］")
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        cons = c.db.all("SELECT * FROM consents WHERE case_id=?", c.id)
        items = [("連絡先", r["contact"] or "—"), ("受付", r["received_at"][:16].replace("T", " ")),
                 ("見積上限額", f"{r['price_cap']:,} 円" if r["price_cap"] else "—"),
                 ("保管期限", r["retention_until"] or "—"),
                 ("同意書", " ／ ".join(f"版 {s['form_version']}・{s['id_method']}・{s['ownership']}" for s in cons)
                  or "未記録")]
        for i, (k, val) in enumerate(items):
            self.grid.addWidget(label(k, muted=True), i // 3 * 2, i % 3)
            self.grid.addWidget(label(val, err=(val == "未記録")), i // 3 * 2 + 1, i % 3)
        while self.trans.count():
            w = self.trans.takeAt(0).widget()
            if w:
                w.deleteLater()
        nexts = TRANSITIONS[r["status"]]
        for t in nexts:
            self.trans.addWidget(button(f"→ {t}", lambda _=False, t=t: self.change(t)))
        if not nexts:
            self.trans.addWidget(label("これ以上の状態変更はありません", muted=True))
        self.trans.addStretch(1)
        devs = c.db.all("SELECT * FROM devices WHERE case_id=?", c.id)
        fill(self.devices, [[d["id"], d["kind"], f"{d['maker'] or ''} {d['model'] or ''}".strip(), d["serial"] or "—",
                             d["symptom"] or "—"] for d in devs])
        while self.diag.count():
            w = self.diag.takeAt(0).widget()
            if w:
                w.deleteLater()
        d = diagnose.latest(c)
        if not d:
            self.diag.addWidget(label("未診断です（「作業」タブで診断します）", muted=True))
        else:
            v = label(f"判定：{d['verdict']}（{d['level']}）")
            v.setStyleSheet(f"font-size: 13pt; font-weight: bold; color: {VERDICT_COLOR.get(d['verdict'], '#333')};")
            self.diag.addWidget(v)
            for x in d["reasons"]:
                self.diag.addWidget(label("・" + x))
            for x in d["warnings"]:
                self.diag.addWidget(label("注意：" + x, warn=True))

    def change(self, status: str) -> None:
        c = self.win.case()
        try:
            c.set_status(status)
        except ResqError as e:
            error(self, "状態の変更", str(e))
        self.win.refresh()

    def add_device(self) -> None:
        dlg = DeviceDialog(self)
        if dlg.exec():
            try:
                intake.add_device(self.win.case(), **dlg.values())
            except ResqError as e:
                error(self, "媒体を追加", str(e))
            self.win.refresh()


# ======================================================================== 作業
class WorkTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        inner = QWidget()
        v = QVBoxLayout(inner)

        # 診断・イメージ化
        g1 = QGroupBox("1. 診断とイメージ化（原本は読むだけ。書き込みません）")
        v1 = QVBoxLayout(g1)
        self.source = PathEdit(placeholder="原本：/dev/sdX（接続中のディスクから選択）またはイメージファイル")
        pick = button("接続中のディスク…", self.pick_device, tip="Linux の作業機でのみ一覧できます")
        pick.setEnabled(IS_LINUX)
        self.symptoms = {k: QCheckBox(k) for k in diagnose.SYMPTOM_RULES}
        sym = QWidget()
        sg = QGridLayout(sym)
        sg.setContentsMargins(0, 0, 0, 0)
        for i, cb in enumerate(self.symptoms.values()):
            sg.addWidget(cb, i // 4, i % 4)
        self.smart = PathEdit(filter="SMART (*.json)", placeholder="（任意）smartctl -j -a の出力。デバイスなら自動で取得")
        self.accept_risk = QCheckBox("SMART の危険兆候を説明済みで続行する")
        self.retry = QSpinBox()
        self.retry.setRange(0, 20)
        self.retry.setValue(3)
        v1.addWidget(form([("原本", hbox(self.source, pick, stretch=False)), ("症状", sym), ("SMART", self.smart),
                           ("再試行回数", hbox(self.retry, self.accept_risk))]))
        img_btn = button("イメージ化を開始", self.do_image, primary=True)
        img_btn.setEnabled(IS_LINUX)
        if not IS_LINUX:
            img_btn.setToolTip("媒体からのイメージ化は Ubuntu の作業機で行います")
        v1.addWidget(hbox(button("診断する", self.do_diagnose, primary=True), img_btn,
                          button("取得済みイメージを登録…", self.do_register)))
        v.addWidget(g1)

        # 解錠
        g2 = QGroupBox("2. BitLocker / LUKS の解錠（回復キーは保存も記録もしません）")
        v2 = QVBoxLayout(g2)
        self.unlock_image = QComboBox()
        self.unlock_kind = QComboBox()
        for k, name in UNLOCK_TYPES.items():
            self.unlock_kind.addItem(name, k)
        self.partition = QLineEdit()
        self.partition.setPlaceholderText("パーティション内の場合「開始セクタ:セクタ数」")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("お客様に入力してもらう回復キー（48 桁）")
        v2.addWidget(form([("イメージ", self.unlock_image), ("方式", self.unlock_kind), ("範囲", self.partition),
                           ("回復キー", self.key)]))
        ub = button("解錠して復号済みイメージを取得", self.do_unlock, primary=True)
        ub.setEnabled(IS_LINUX)
        v2.addWidget(hbox(ub))
        v.addWidget(g2)

        # 復旧
        g3 = QGroupBox("3. 復旧（多段サルベージ）")
        v3 = QVBoxLayout(g3)
        self.rec_image = QComboBox()
        self.stage_checks = {s: QCheckBox(f"{s} {STAGES[s]}") for s in ("S1", "S2", "S3", "S4", "S5", "S6", "S7")}
        st = QWidget()
        sgl = QGridLayout(st)
        sgl.setContentsMargins(0, 0, 0, 0)
        for i, cb in enumerate(self.stage_checks.values()):
            cb.setChecked(True)
            sgl.addWidget(cb, i // 3, i % 3)
        self.use_testdisk = QCheckBox("S1 で TestDisk も使う")
        self.use_testdisk.setChecked(True)
        v3.addWidget(form([("イメージ", self.rec_image), ("実行する段", st), ("", self.use_testdisk)]))
        v3.addWidget(hbox(button("復旧を実行", self.do_recover, primary=True)))
        v.addWidget(g3)

        # 取り込み・比較
        g4 = QGroupBox("4. 商用エンジンの結果の取り込み・比較")
        v4 = QVBoxLayout(g4)
        self.engine = QComboBox()
        self.engine.addItems(list(ALLOWED_ENGINES))
        self.engine_dir = PathEdit(directory=True, placeholder="DMDE / R-Studio で書き出したフォルダ")
        self.cmp_a, self.cmp_b = QComboBox(), QComboBox()
        v4.addWidget(form([("エンジン", self.engine), ("書き出しフォルダ", self.engine_dir)]))
        v4.addWidget(hbox(button("取り込んで統合", self.do_ingest), label("　比較："), self.cmp_a, label("と"),
                          self.cmp_b, button("比較", self.do_compare)))
        v.addWidget(g4)

        # スマホ
        g5 = QGroupBox("5. スマホ吸い出し（起動して持ち主がロックを解除できる端末のみ）")
        g5l = QHBoxLayout(g5)
        g5l.addWidget(button("iPhone から吸い出す…", self.do_ios))
        g5l.addWidget(button("Android から吸い出す…", self.do_android))
        g5l.addStretch(1)
        v.addWidget(g5)
        v.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_scroll(inner))

    def refresh(self, c) -> None:
        imgs = c.db.all("SELECT * FROM images WHERE case_id=? ORDER BY id", c.id)
        for combo in (self.rec_image, self.unlock_image):
            combo.clear()
            for i in imgs:
                state = "完了" if i["sha256"] else "未完了"
                combo.addItem(f"#{i['id']} {Path(i['path']).name}（{human_bytes(i['size'])}・{state}）", i["id"])
        stages = sorted({r["stage"] for r in c.db.all("SELECT stage FROM stage_runs WHERE case_id=?", c.id)})
        for combo in (self.cmp_a, self.cmp_b):
            combo.clear()
            combo.addItems(stages)

    # -- 操作
    def _w(self):
        return self.win.ws.root, self.win.case_id

    def pick_device(self) -> None:
        from ..devices import list_disks

        dlg = DevicePickerDialog(self, list_disks())
        if dlg.exec() and dlg.path:
            self.source.setText(dlg.path)

    def do_diagnose(self) -> None:
        src = self.source.text()
        syms = [k for k, cb in self.symptoms.items() if cb.isChecked()]
        if not src and not syms:
            error(self, "診断", "原本（デバイスまたはイメージ）を指定するか、症状を選んでください")
            return
        root, cid = self._w()
        self.win.runner.start("診断", lambda s: tasks.run_diagnose(root, cid, src or "(未接続)", syms,
                                                                    self.smart.text() or None, None, s),
                              lambda d: self.win.refresh(tab=0))

    def do_image(self) -> None:
        src = self.source.text()
        if not src:
            error(self, "イメージ化", "原本を指定してください")
            return
        root, cid = self._w()
        risk, retry = self.accept_risk.isChecked(), self.retry.value()
        self.win.runner.start("イメージ化", lambda s: tasks.run_image(root, cid, src, risk, retry, s),
                              lambda iid: self.win.refresh())

    def do_register(self) -> None:
        p = self.source.text()
        if not p:
            from PySide6.QtWidgets import QFileDialog

            p, _ = QFileDialog.getOpenFileName(self, "取得済みイメージ（読み取り専用にしたもの）")
        if not p:
            return
        root, cid = self._w()
        self.win.runner.start("イメージの登録", lambda s: tasks.run_register(root, cid, p, s),
                              lambda iid: self.win.refresh())

    def do_unlock(self) -> None:
        iid = self.unlock_image.currentData()
        key = self.key.text()
        self.key.clear()  # 画面に残さない
        if iid is None or not key:
            error(self, "解錠", "イメージを選び、回復キーを入力してください")
            return
        part = None
        if self.partition.text().strip():
            try:
                a, b = (int(x) for x in self.partition.text().split(":"))
                part = (a, b)
            except ValueError:
                error(self, "解錠", "範囲は「開始セクタ:セクタ数」で入力してください")
                return
        root, cid = self._w()
        kind = self.unlock_kind.currentData()
        self.win.runner.start("解錠と復号済みイメージの取得",
                              lambda s: tasks.run_unlock(root, cid, iid, key, kind, part, s),
                              lambda r: self.win.refresh())
        del key

    def do_recover(self) -> None:
        iid = self.rec_image.currentData()
        stages = [s for s, cb in self.stage_checks.items() if cb.isChecked()]
        if iid is None:
            error(self, "復旧", "先にイメージを取得または登録してください")
            return
        root, cid = self._w()
        td = self.use_testdisk.isChecked()
        self.win.runner.start("復旧", lambda s: tasks.run_recover(root, cid, iid, stages, td, s),
                              lambda rep: self.win.refresh(tab=2))

    def do_ingest(self) -> None:
        folder = self.engine_dir.text()
        if not folder:
            error(self, "取り込み", "書き出しフォルダを指定してください")
            return
        root, cid = self._w()
        eng = self.engine.currentText()
        self.win.runner.start("商用エンジン結果の取り込み", lambda s: tasks.run_ingest(root, cid, folder, eng, s),
                              lambda rep: self.win.refresh(tab=2))

    def do_compare(self) -> None:
        a, b = self.cmp_a.currentText(), self.cmp_b.currentText()
        if not a or not b or a == b:
            error(self, "比較", "異なる 2 つの段を選んでください")
            return
        root, cid = self._w()
        self.win.runner.start(f"{a} と {b} の比較", lambda s: tasks.run_compare(root, cid, a, b, s),
                              lambda rep: info(self, "比較の結果",
                                               json.dumps(rep["count"], ensure_ascii=False, indent=1)
                                               + f"\n\n記録: {rep['path']}"))

    def _mobile(self, title, steps, id_label, fn) -> None:
        dlg = ConfirmStepsDialog(self, title, steps, id_label)
        if not dlg.exec():
            return
        root, cid = self._w()
        ident, confirmed = dlg.ident.text().strip(), dlg.confirmed()
        self.win.runner.start(title, lambda s: fn(root, cid, ident, confirmed, s),
                              lambda n: (info(self, title, f"{n} 件を取り出しました"), self.win.refresh(tab=2)))

    def do_ios(self) -> None:
        from ..mobile import ios

        self._mobile("iPhone から吸い出す", ios.STEPS, "UDID", tasks.run_ios)

    def do_android(self) -> None:
        from ..mobile import android

        self._mobile("Android から吸い出す", android.STEPS, "シリアル", tasks.run_android)


# ======================================================================== 復旧ファイル
class FilesTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        self.summary = label("")
        v.addWidget(self.summary)
        self.rank = QComboBox()
        self.rank.addItem("すべて（ランク外を除く）", None)
        for k, t in RANK_LABEL.items():
            self.rank.addItem(t, k)
        self.rank.currentIndexChanged.connect(lambda _: self.refresh(self.win.case()))
        v.addWidget(hbox(label("表示："), self.rank, button("A・B を納品対象に", self.select_ab),
                         button("選択を保存", self.save_selection, primary=True),
                         button("顧客向け一覧（PDF）を作成", self.build_catalog),
                         button("一覧を開く", self.open_catalog)))
        sp = QSplitter(Qt.Horizontal)
        self.t = table(["納品", "#", "ランク", "ファイル名", "元の場所", "種類", "サイズ", "確認結果", "手法"], stretch_col=4)
        self.t.setSelectionMode(self.t.SelectionMode.SingleSelection)
        self.t.itemSelectionChanged.connect(self.preview)
        sp.addWidget(self.t)
        pv = QWidget()
        pvl = QVBoxLayout(pv)
        self.thumb = label("")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setMinimumSize(260, 200)
        self.meta = label("", muted=True)
        pvl.addWidget(self.thumb)
        pvl.addWidget(self.meta)
        pvl.addStretch(1)
        sp.addWidget(pv)
        sp.setStretchFactor(0, 3)
        v.addWidget(sp, 1)
        v.addWidget(label("ランク外（上書き・破損で中身が残っていないもの）は表示しません。復旧したものとして扱いません。",
                          muted=True))
        self.rows: list = []

    def refresh(self, c) -> None:
        rank = self.rank.currentData()
        q = "SELECT * FROM recovered_files WHERE case_id=? AND rank!='X'"
        args: list = [c.id]
        if rank:
            q += " AND rank=?"
            args.append(rank)
        self.rows = c.db.all(q + " ORDER BY rank, id", *args)
        counts = {r["rank"]: r["n"] for r in c.db.all(
            "SELECT rank, COUNT(*) AS n FROM recovered_files WHERE case_id=? GROUP BY rank", c.id)}
        sel = c.db.one("SELECT COUNT(*) AS n FROM recovered_files WHERE case_id=? AND selected=1", c.id)["n"]
        self.summary.setText("　".join(f"{k}: {counts.get(k, 0)} 件" for k in "ABCDU")
                             + f"　／ ランク外 {counts.get('X', 0)} 件　／ 納品対象 {sel} 件")
        self.t.setRowCount(0)
        for i, r in enumerate(self.rows):
            self.t.insertRow(i)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if r["selected"] else Qt.Unchecked)
            chk.setData(Qt.UserRole, r["id"])
            self.t.setItem(i, 0, chk)
            vals = [r["id"], r["rank"], r["name"], catalog.display_path(r["orig_path"]) or "（元のフォルダ不明）",
                    KIND_LABEL.get(r["kind"] or "bin", r["kind"]), human_bytes(r["size"]),
                    catalog.VERIFY_LABEL.get(r["verify"], r["verify"]), r["method"]]
            for j, val in enumerate(vals, 1):
                it = QTableWidgetItem(str(val))
                if j == 2:
                    from PySide6.QtGui import QColor

                    it.setForeground(QColor(RANK_COLOR.get(r["rank"], "#333")))
                self.t.setItem(i, j, it)

    def checked_ids(self) -> list[int]:
        return [self.t.item(i, 0).data(Qt.UserRole) for i in range(self.t.rowCount())
                if self.t.item(i, 0).checkState() == Qt.Checked]

    def save_selection(self) -> None:
        c = self.win.case()
        shown = {r["id"] for r in self.rows}
        keep = [r["id"] for r in c.db.all("SELECT id FROM recovered_files WHERE case_id=? AND selected=1", c.id)
                if r["id"] not in shown]
        n = deliver.select(c, ranks=None, ids=keep + self.checked_ids())
        self.win.log.add(f"納品対象を保存しました（{n} 件）")
        self.win.refresh()

    def select_ab(self) -> None:
        n = deliver.select(self.win.case(), ranks=("A", "B"))
        self.win.log.add(f"ランク A・B を納品対象にしました（{n} 件）")
        self.win.refresh()

    def build_catalog(self) -> None:
        root, cid = self.win.ws.root, self.win.case_id
        self.win.runner.start("顧客向け一覧の作成", lambda s: tasks.run_catalog(root, cid, s),
                              lambda r: (self.win.refresh(), info(self, "一覧を作成しました",
                                                                  str(r["pdf"] or r["html"]))))

    def open_catalog(self) -> None:
        d = self.win.case().dir / "catalog"
        p = d / "list.pdf" if (d / "list.pdf").exists() else d / "list.html"
        if not p.exists():
            error(self, "一覧", "まだ作成されていません")
            return
        open_local(p)

    def preview(self) -> None:
        rows = self.t.selectionModel().selectedRows()
        if not rows:
            return
        rid = self.t.item(rows[0].row(), 0).data(Qt.UserRole)
        r = next((x for x in self.rows if x["id"] == rid), None)
        if not r:
            return
        f = self.win.case().dir / r["stored_path"]
        pm = QPixmap(str(f)) if r["kind"] in ("jpg", "png", "gif", "bmp", "tif", "webp") else QPixmap()
        if not pm.isNull():
            self.thumb.setPixmap(pm.scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb.setText("（プレビューなし）")
        alts = json.loads(r["alt_names"]) if r["alt_names"] else []
        self.meta.setText(f"{r['name']}\n{catalog.display_path(r['orig_path']) or '（元のフォルダ不明）'}\n"
                          f"SHA-256 {r['sha256'][:16]}…\n手法: {', '.join(json.loads(r['all_methods'] or '[]'))}"
                          + (f"\n別名: {', '.join(alts)}" if alts else ""))


# ======================================================================== 納品・消去
class DeliverTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        g1 = QGroupBox("納品（選んだファイルを新品のメディアへ。全件ハッシュ照合）")
        v1 = QVBoxLayout(g1)
        self.target = PathEdit(directory=True, placeholder="納品用メディアのフォルダ（USB メモリ・外付け HDD）")
        self.operator = QLineEdit()
        v1.addWidget(form([("納品先", self.target), ("担当者", self.operator)]))
        v1.addWidget(hbox(button("納品する", self.do_deliver, primary=True), button("納品書を開く", self.open_note)))
        self.deliveries = table(["日時", "ファイル数", "サイズ", "納品先"], stretch_col=3)
        self.deliveries.setMaximumHeight(120)
        v1.addWidget(self.deliveries)
        v.addWidget(g1)
        g2 = QGroupBox("作業データの消去（納品・キャンセル・返却のあと）")
        v2 = QVBoxLayout(g2)
        self.wipe_state = label("")
        v2.addWidget(self.wipe_state)
        v2.addWidget(hbox(button("消去の対象を確認", self.wipe_dry),
                          button("作業データを消去して証明書を発行…", self.wipe_exec, danger=True),
                          button("LUKS 破棄スクリプトを作成", self.wipe_plan),
                          button("破棄の完了を確認して証明書を発行", self.wipe_confirm)))
        self.size = QLineEdit("500G")
        v2.addWidget(hbox(label("暗号化作業領域（LUKS）："), self.size,
                          button("作成スクリプトを作る", self.ws_create)))
        v.addWidget(g2)
        g3 = QGroupBox("証明書")
        v3 = QVBoxLayout(g3)
        self.certs = table(["番号", "種類", "発行", "SHA-256"], stretch_col=3)
        self.certs.setMaximumHeight(120)
        v3.addWidget(self.certs)
        v3.addWidget(hbox(button("選んだ証明書を開く", self.open_cert)))
        v.addWidget(g3)
        v.addStretch(1)

    def refresh(self, c) -> None:
        ds = c.db.all("SELECT * FROM deliveries WHERE case_id=? ORDER BY id DESC", c.id)
        fill(self.deliveries, [[d["delivered_at"][:16].replace("T", " "), d["files"], human_bytes(d["bytes"]),
                                d["target"]] for d in ds], data=[d["note_path"] for d in ds])
        cs = c.db.all("SELECT * FROM certificates WHERE case_id=? ORDER BY id DESC", c.id)
        fill(self.certs, [[x["number"], x["kind"], x["issued_at"][:16].replace("T", " "), x["sha256"]] for x in cs],
             data=[x["path"] for x in cs])
        enc = workspace_crypt.is_encrypted_workspace(c.ws, c.id)
        self.wipe_state.setText(f"状態：{c.row['status']}　／ 作業領域：{'暗号化コンテナ（LUKS）' if enc else '通常のフォルダ'}"
                                f"　／ 消去できる状態：{' / '.join(wipe.WIPE_FROM)}")

    def do_deliver(self) -> None:
        tgt = self.target.text()
        if not tgt:
            error(self, "納品", "納品先のフォルダを指定してください")
            return
        root, cid, op = self.win.ws.root, self.win.case_id, self.operator.text().strip()
        self.win.runner.start("納品", lambda s: tasks.run_deliver(root, cid, tgt, op, s),
                              lambda r: (self.win.refresh(), info(self, "納品しました",
                                                                  f"{r['count']} 件（全件ハッシュ一致）\n{r['root']}")))

    def open_note(self) -> None:
        p = selected_data(self.deliveries) or (self.deliveries.item(0, 0).data(Qt.UserRole)
                                               if self.deliveries.rowCount() else None)
        if p:
            open_local(p)

    def open_cert(self) -> None:
        p = selected_data(self.certs)
        if p:
            open_local(p)

    def wipe_dry(self) -> None:
        try:
            r = wipe.wipe_plain(self.win.case(), execute=False)
            info(self, "消去の対象", f"{r['target']}\n{json.dumps(r['summary'], ensure_ascii=False)}")
        except ResqError as e:
            error(self, "消去", str(e))

    def wipe_exec(self) -> None:
        if not confirm(self, "作業データの消去", "この案件の作業データ（イメージ・復旧結果）をすべて削除します。元に戻せません。"
                                             "\n本当に消去しますか？"):
            return
        self._issue(lambda c: wipe.wipe_plain(c, execute=True, operator=self.operator.text().strip()))

    def wipe_plan(self) -> None:
        try:
            p = wipe.plan(self.win.case())
            info(self, "破棄スクリプト", f"作業機で root として実行してください：\n{p}")
        except ResqError as e:
            error(self, "消去", str(e))

    def wipe_confirm(self) -> None:
        self._issue(lambda c: wipe.confirm(c, operator=self.operator.text().strip()))

    def _issue(self, fn) -> None:
        try:
            r = fn(self.win.case())
            info(self, "消去証明書", f"{r['number']}\n{r['path']}")
        except ResqError as e:
            error(self, "消去", str(e))
        self.win.refresh()

    def ws_create(self) -> None:
        c = self.win.case()
        p = workspace_crypt.write_script(c.ws, c.id, "create",
                                         workspace_crypt.create_commands(c.ws, c.id, self.size.text().strip()))
        info(self, "作成スクリプト", f"作業機で root として実行してください：\n{p}")


# ======================================================================== 操作ログ
class EventsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        v = QVBoxLayout(self)
        self.t = table(["日時", "操作", "rc", "内容"], stretch_col=3)
        v.addWidget(self.t)

    def refresh(self, c) -> None:
        fill(self.t, [[e["ts"][:19].replace("T", " "), e["op"], "" if e["rc"] is None else e["rc"],
                       (e["command"] or "")[:200]]
                      for e in c.db.all("SELECT * FROM events WHERE case_id=? ORDER BY id DESC LIMIT 500", c.id)])


# ======================================================================== メイン
class MainWindow(QMainWindow):
    def __init__(self, ws: Workspace, *, sync: bool = False):
        super().__init__()
        self.ws, self.db = open_workspace(ws)
        self.case_id: str | None = None
        self.setWindowTitle(f"resq データ復旧 {__version__}　—　作業領域 {self.ws.root}")
        self.resize(1280, 860)

        self.log = LogPanel()
        dock = QDockWidget("実行の記録")
        dock.setWidget(self.log)
        dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.runner = Runner(self, self.log, sync=sync)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(button("＋ 新規受付", self.new_case, primary=True))
        self.search = QLineEdit()
        self.search.setPlaceholderText("案件番号・お客様名で検索")
        self.search.textChanged.connect(lambda _: self.load_cases())
        self.status = QComboBox()
        self.status.addItem("すべての状態", None)
        for s in STATES:
            self.status.addItem(s, s)
        self.status.currentIndexChanged.connect(lambda _: self.load_cases())
        lv.addWidget(self.search)
        lv.addWidget(self.status)
        self.cases = table(["案件番号", "お客様", "状態"], stretch_col=1)
        self.cases.itemSelectionChanged.connect(self.on_select)
        lv.addWidget(self.cases, 1)

        self.tabs = QTabWidget()
        self.overview, self.work, self.files = OverviewTab(self), WorkTab(self), FilesTab(self)
        self.deliver_tab, self.events = DeliverTab(self), EventsTab(self)
        for w, t in ((self.overview, "概要"), (self.work, "作業"), (self.files, "復旧ファイル"),
                     (self.deliver_tab, "納品・消去"), (self.events, "操作ログ")):
            self.tabs.addTab(w, t)
        self.stack = QStackedWidget()
        empty = label("左の一覧から案件を選ぶか、「新規受付」で登録してください。", muted=True)
        empty.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(empty)
        self.stack.addWidget(self.tabs)

        sp = QSplitter(Qt.Horizontal)
        sp.addWidget(left)
        sp.addWidget(self.stack)
        sp.setStretchFactor(1, 1)
        sp.setSizes([330, 950])
        self.setCentralWidget(sp)
        self._menu()
        self.load_cases()

    def _menu(self) -> None:
        m = self.menuBar().addMenu("ファイル")
        a = QAction("新規受付…", self)
        a.triggered.connect(self.new_case)
        m.addAction(a)
        b = QAction("作業領域のフォルダを開く", self)
        b.triggered.connect(lambda: open_local(self.ws.root))
        m.addAction(b)
        c = QAction("消去禁止シリアルを書き出す…", self)
        c.triggered.connect(self.export_serials)
        m.addAction(c)
        d = QAction("保管期限切れの案件", self)
        d.triggered.connect(self.show_due)
        m.addAction(d)

    # -- 案件
    def case(self):
        return get_case(self.ws, self.db, self.case_id)

    def load_cases(self) -> None:
        q, args = "SELECT * FROM cases WHERE 1=1", []
        if self.status.currentData():
            q += " AND status=?"
            args.append(self.status.currentData())
        s = self.search.text().strip()
        if s:
            q += " AND (id LIKE ? OR customer LIKE ?)"
            args += [f"%{s}%", f"%{s}%"]
        rows = self.db.all(q + " ORDER BY id DESC", *args)
        self.cases.blockSignals(True)
        fill(self.cases, [[r["id"], r["customer"], r["status"]] for r in rows], data=[r["id"] for r in rows])
        for i, r in enumerate(rows):
            if r["id"] == self.case_id:
                self.cases.selectRow(i)
        self.cases.blockSignals(False)

    def on_select(self) -> None:
        cid = selected_data(self.cases)
        if cid:
            self.select_case(cid)

    def select_case(self, cid: str) -> None:
        self.case_id = cid
        self.refresh()

    def refresh(self, tab: int | None = None) -> None:
        self.load_cases()
        if not self.case_id:
            self.stack.setCurrentIndex(0)
            return
        c = self.case()
        for t in (self.overview, self.work, self.files, self.deliver_tab, self.events):
            t.refresh(c)
        self.stack.setCurrentIndex(1)
        if tab is not None:
            self.tabs.setCurrentIndex(tab)

    def new_case(self) -> None:
        dlg = IntakeDialog(self, self.ws, self.db)
        if dlg.exec() and dlg.case:
            self.log.add(f"案件 {dlg.case.id} を受付しました")
            self.select_case(dlg.case.id)

    def export_serials(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from ..db import now

        p, _ = QFileDialog.getSaveFileName(self, "消去ステーションへ渡すファイル", "serials.json", "JSON (*.json)")
        if not p:
            return
        rows = self.db.all("""SELECT d.serial, d.case_id FROM devices d JOIN cases c ON c.id = d.case_id
                              WHERE d.serial IS NOT NULL AND d.serial != '' AND c.status NOT IN ('返却', '消去済')""")
        Path(p).write_text(json.dumps({"exported_at": now(), "serials": [dict(r) for r in rows]}, ensure_ascii=False,
                                      indent=1), encoding="utf-8")
        info(self, "書き出し", f"{len(rows)} 件を書き出しました\n{p}")

    def show_due(self) -> None:
        due = wipe.due(self.db)
        info(self, "保管期限切れ", "\n".join(f"{d['id']} {d['customer']}（{d['status']}・期限 {d['retention_until']}）"
                                            for d in due) or "ありません")

    def closeEvent(self, e) -> None:  # noqa: N802
        if self.runner.busy and not confirm(self, "終了", "処理を実行中です。終了すると中断されます（イメージ化は後で再開できます）。"
                                                         "終了しますか？"):
            e.ignore()
            return
        self.db.close()
        super().closeEvent(e)


# ======================================================================== 起動・自己診断
def selftest(fixtures: Path, out: Path) -> int:
    """画面を実際に組み立てて、フィクスチャで 受付→登録→復旧→一覧 を通す（ビルド後の確認用）。"""
    import os
    import shutil
    import stat

    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"ok": False}
    try:
        make_app(sys.argv, ACCENT)
        noninteractive()
        ws = Workspace(out / "ws")
        win = MainWindow(ws, sync=True)
        win.show()
        from ..cases import create_case

        c = create_case(win.ws, win.db, customer="動作確認", price_cap=9800)
        intake.add_consent(c, form_version="2026.11", id_method="運転免許証", ownership="本人所有")
        img = out / "ntfs_qf.img"
        shutil.copyfile(fixtures / "ntfs_qf.img", img)
        os.chmod(img, stat.S_IREAD)
        win.select_case(c.id)
        win.work.source.setText(str(img))
        win.work.do_register()
        win.work.use_testdisk.setChecked(False)
        win.work.do_recover()
        win.files.build_catalog()
        win.refresh(tab=2)
        names = [win.files.t.item(i, 3).text() for i in range(win.files.t.rowCount())]
        expected = [f["name"] for f in json.loads((fixtures / "expected.json").read_text(encoding="utf-8"))
                    ["images"]["ntfs_qf"]["files"]]
        cat = c.dir / "catalog"
        result.update(names=names, missing=[n for n in expected if n not in names],
                      pdf=(cat / "list.pdf").exists(), html=(cat / "list.html").exists())
        win.grab().save(str(out / "resq-gui.png"))
        result["messages"] = Dialogs.shown
        result["ok"] = not result["missing"] and result["html"] and not [m for m in Dialogs.shown if m[0] == "error"]
        win.close()
    except Exception as e:  # noqa: BLE001
        import traceback

        result["error"] = f"{e}\n{traceback.format_exc()}"
    (out / "selftest.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    from .common import setup_offscreen_if_requested

    argv = list(sys.argv if argv is None else argv)
    setup_offscreen_if_requested(argv)
    if "--selftest" in argv:
        i = argv.index("--selftest")
        return selftest(Path(argv[i + 1]), Path(argv[i + 2]))
    app = make_app(argv, ACCENT)
    win = MainWindow(Workspace.from_env())
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
