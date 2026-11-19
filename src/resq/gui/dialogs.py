"""復旧アプリのダイアログ（受付・媒体の追加・スマホの確認・デバイスの選択）。"""
from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QGroupBox, QLineEdit,
                               QSpinBox, QVBoxLayout)

from .. import intake
from ..cases import create_case
from ..errors import ResqError
from .common import fill, form, human_bytes, label, selected_data, table

DEVICE_KINDS = ("HDD", "SSD", "NVMe SSD", "USB メモリ", "SD カード", "iPhone", "Android", "その他")


class IntakeDialog(QDialog):
    """新規受付：お客様・本人確認・所有確認・同意書・預かり媒体。"""

    def __init__(self, parent, ws, db):
        super().__init__(parent)
        self.ws, self.db = ws, db
        self.case = None
        self.setWindowTitle("新規受付")
        self.resize(640, 0)
        lay = QVBoxLayout(self)

        self.customer = QLineEdit()
        self.contact = QLineEdit()
        self.price_cap = QSpinBox()
        self.price_cap.setRange(0, 10_000_000)
        self.price_cap.setSingleStep(1000)
        self.price_cap.setSuffix(" 円")
        self.price_cap.setSpecialValueText("（未定）")
        self.retention = QDateEdit(QDate.currentDate().addDays(30))
        self.retention.setCalendarPopup(True)
        self.retention.setDisplayFormat("yyyy-MM-dd")
        g1 = QGroupBox("お客様")
        QVBoxLayout(g1).addWidget(form([("お名前 *", self.customer), ("連絡先", self.contact),
                                        ("見積上限額", self.price_cap), ("保管期限", self.retention)]))
        lay.addWidget(g1)

        self.form_version = QLineEdit("2026.11")
        self.id_method = QComboBox()
        self.id_method.addItems(intake.ID_METHODS)
        self.ownership = QComboBox()
        self.ownership.addItems(intake.OWNERSHIP_CHOICES)
        self.auth_doc = QLineEdit()
        self.auth_doc.setPlaceholderText("本人所有でない場合は必須（書類番号など）")
        g2 = QGroupBox("本人確認・所有確認・同意書")
        QVBoxLayout(g2).addWidget(form([("同意書の版 *", self.form_version), ("本人確認方法 *", self.id_method),
                                        ("所有確認 *", self.ownership), ("権限者の同意書面", self.auth_doc)]))
        lay.addWidget(g2)

        self.kind = QComboBox()
        self.kind.addItems(("（後で登録）",) + DEVICE_KINDS)
        self.maker, self.model, self.serial = QLineEdit(), QLineEdit(), QLineEdit()
        self.symptom = QLineEdit()
        self.symptom.setPlaceholderText("誤削除 / 起動しない / 異音 など")
        self.request = QLineEdit()
        g3 = QGroupBox("お預かり媒体")
        v3 = QVBoxLayout(g3)
        v3.addWidget(form([("種別", self.kind), ("メーカー", self.maker), ("型番", self.model),
                           ("シリアル", self.serial), ("症状", self.symptom), ("ご依頼内容", self.request)]))
        v3.addWidget(label("異音・通電の繰り返しがある媒体は電源を入れずに取次へ。ロック解除・回避のご依頼はお受けできません。",
                           muted=True))
        lay.addWidget(g3)

        self.message = label("", err=True)
        lay.addWidget(self.message)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("受付を登録")
        bb.button(QDialogButtonBox.Cancel).setText("やめる")
        bb.accepted.connect(self.submit)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def submit(self) -> None:
        try:
            self.case = self.register()
        except ResqError as e:
            self.message.setText(str(e))
            return
        self.accept()

    def register(self):
        customer = self.customer.text().strip()
        if not customer:
            raise ResqError("お名前を入力してください")
        ownership = self.ownership.currentText()
        auth = self.auth_doc.text().strip()
        if ownership != intake.OWNERSHIP_SELF and not auth:
            raise ResqError("本人所有でない端末は、権限者の同意書面（書類番号等）の記録が必要です")
        req = self.request.text().strip()
        for key, reason in intake.REFUSED_REQUESTS.items():
            if key in req:
                raise ResqError(f"受付できません: {reason}")
        c = create_case(self.ws, self.db, customer=customer, contact=self.contact.text().strip() or None,
                        price_cap=self.price_cap.value() or None,
                        retention_until=self.retention.date().toString("yyyy-MM-dd"))
        intake.add_consent(c, form_version=self.form_version.text().strip(), id_method=self.id_method.currentText(),
                           ownership=ownership, authorization_doc=auth or None)
        if self.kind.currentIndex() > 0:
            intake.add_device(c, kind=self.kind.currentText(), maker=self.maker.text().strip() or None,
                              model=self.model.text().strip() or None, serial=self.serial.text().strip() or None,
                              symptom=self.symptom.text().strip() or None, request=req or None)
        return c


class DeviceDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("媒体を追加")
        lay = QVBoxLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(DEVICE_KINDS)
        self.maker, self.model, self.serial, self.symptom = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        lay.addWidget(form([("種別", self.kind), ("メーカー", self.maker), ("型番", self.model),
                            ("シリアル", self.serial), ("症状", self.symptom)]))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> dict:
        return {"kind": self.kind.currentText(), "maker": self.maker.text().strip() or None,
                "model": self.model.text().strip() or None, "serial": self.serial.text().strip() or None,
                "symptom": self.symptom.text().strip() or None}


class ConfirmStepsDialog(QDialog):
    """持ち主本人の操作を 1 つずつ確認する（スマホ吸い出し）。全部チェックするまで進めない。"""

    def __init__(self, parent, title: str, steps: list[str], id_label: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(label("持ち主本人に次の操作をしてもらい、確認できたものにチェックを入れてください。"))
        self.checks = [QCheckBox(s) for s in steps]
        for c in self.checks:
            lay.addWidget(c)
        self.ident = QLineEdit()
        lay.addWidget(form([(id_label, self.ident)]))
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText("吸い出しを開始")
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        lay.addWidget(self.bb)
        for c in self.checks:
            c.toggled.connect(self._update)
        self.ident.textChanged.connect(self._update)
        self._update()

    def _update(self) -> None:
        self.bb.button(QDialogButtonBox.Ok).setEnabled(all(c.isChecked() for c in self.checks)
                                                      and bool(self.ident.text().strip()))

    def confirmed(self) -> dict[str, bool]:
        return {c.text(): c.isChecked() for c in self.checks}


class DevicePickerDialog(QDialog):
    """接続中のディスクから原本を選ぶ（読み取りのみ）。マウント中のディスクは選べない。"""

    def __init__(self, parent, disks: list[dict]):
        super().__init__(parent)
        self.setWindowTitle("接続中のディスク")
        self.resize(760, 320)
        lay = QVBoxLayout(self)
        lay.addWidget(label("原本は必ずライトブロッカー経由で接続し、読み取り専用にしてから選んでください。"
                            "マウント中のディスク（作業機自身のディスク等）は選べません。", warn=True))
        self.t = table(["デバイス", "容量", "型番", "シリアル", "接続", "読み取り専用", "マウント"], stretch_col=2)
        fill(self.t, [[d["path"], human_bytes(d["size"]), d["model"], d["serial"], d["tran"],
                       "はい" if d["ro"] else "いいえ", ", ".join(d["mounts"]) or "—"] for d in disks], data=disks)
        lay.addWidget(self.t)
        if not disks:
            lay.addWidget(label("ディスクが見つかりません（Linux の作業機でのみ一覧できます）", muted=True))
        self.msg = label("", err=True)
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.pick)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.path = None

    def pick(self) -> None:
        d = selected_data(self.t)
        if not d:
            self.msg.setText("ディスクを選んでください")
            return
        if d["mounts"]:
            self.msg.setText("マウント中のディスクは選べません（作業機自身のディスクの可能性）")
            return
        self.path = d["path"]
        self.accept()
