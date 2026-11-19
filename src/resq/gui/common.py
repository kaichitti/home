"""デスクトップアプリ（Qt / PySide6）の共通部品。復旧アプリと消去ステーションアプリで共用する。

- ネットワークは一切使わない（待ち受けも通信もしない）
- 時間のかかる処理（診断・イメージ化・復旧など）は別スレッドで動かし、画面を固めない。
  別スレッドでは DB を開き直す（SQLite の接続はスレッドをまたいで使えないため）
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QWidget)

STYLE = """
QWidget { font-size: 10.5pt; }
QMainWindow, QDialog { background: #f6f6f4; }
QGroupBox { background: #ffffff; border: 1px solid #d9d8d2; border-radius: 6px; margin-top: 14px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #333; font-weight: bold; }
QTableWidget { background: #ffffff; gridline-color: #e6e5df; selection-background-color: #cfe0f1; selection-color: #111; }
QHeaderView::section { background: #efeee9; color: #555; padding: 4px 6px; border: 0; border-bottom: 1px solid #d9d8d2; }
QPushButton { padding: 5px 12px; border-radius: 4px; border: 1px solid #c9c8c2; background: #ffffff; }
QPushButton:hover { background: #f0f4f8; }
QPushButton:disabled { color: #aaa; }
QPushButton[primary="true"] { background: ACCENT; color: white; border: 1px solid ACCENT; }
QPushButton[danger="true"] { background: #b3261e; color: white; border: 1px solid #b3261e; }
QPushButton[primary="true"]:disabled, QPushButton[danger="true"]:disabled { background: #e4e3de; color: #a5a49e; border: 1px solid #d9d8d2; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: #ffffff; border: 1px solid #c9c8c2; border-radius: 3px; padding: 3px 5px; }
QTabWidget::pane { border: 1px solid #d9d8d2; background: #fbfbfa; }
QTabBar::tab { padding: 6px 14px; }
QTabBar::tab:selected { background: #fbfbfa; font-weight: bold; }
QLabel[muted="true"] { color: #6b6b66; }
QLabel[warn="true"] { color: #b26a00; }
QLabel[error="true"] { color: #b3261e; font-weight: bold; }
QLabel[badge="true"] { background: #e7eef6; color: #1f5f99; border-radius: 8px; padding: 1px 8px; }
"""

VERDICT_COLOR = {"自社": "#2e7d32", "条件付き": "#b26a00", "取次": "#6a1b9a", "不可": "#b3261e"}
RANK_COLOR = {"A": "#2e7d32", "B": "#1565c0", "C": "#ef6c00", "D": "#6a1b9a", "U": "#757575", "X": "#9e9e9e"}


def make_app(argv: list[str], accent: str) -> QApplication:
    app = QApplication.instance() or QApplication(argv)
    app.setStyleSheet(STYLE.replace("ACCENT", accent))
    f = QFont()
    f.setFamilies(["Noto Sans CJK JP", "Yu Gothic UI", "Meiryo UI", "Hiragino Sans", "IPAexGothic", "sans-serif"])
    app.setFont(f)
    return app


# ---------------------------------------------------------------- 別スレッドでの実行
class _Job(QObject):
    done = Signal(object)
    failed = Signal(str)
    line = Signal(str)

    def __init__(self, fn: Callable[["LineStream"], Any]):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(LineStream(self.line.emit)))
        except Exception as e:  # noqa: BLE001 - 画面に表示する
            self.failed.emit(_message(e))


class LineStream:
    """外部コマンドの出力（ddrescue の進捗等）を 1 行ずつ画面のログへ送る。"""

    def __init__(self, emit: Callable[[str], None]):
        self._emit = emit
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s.replace("\r", "\n")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._emit(line)
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            self._emit(self._buf)
        self._buf = ""


def _message(e: BaseException) -> str:
    from ..errors import ResqError

    if isinstance(e, ResqError):
        return str(e)
    # 消去ステーション版の業務エラー。復旧側から resq_erase を import しないよう、モジュール名で判定する
    if type(e).__module__.startswith("resq_erase."):
        return str(e)
    return f"{type(e).__name__}: {e}\n\n{traceback.format_exc(limit=3)}"


class Runner:
    """処理を別スレッドで実行する。sync=True ならその場で実行（テスト・自己診断用）。"""

    def __init__(self, parent: QWidget, log: "LogPanel", sync: bool = False):
        self.parent = parent
        self.log = log
        self.sync = sync
        self._threads: list[tuple[QThread, _Job]] = []
        self.busy = False

    def start(self, title: str, fn: Callable[[LineStream], Any], on_done: Callable[[Any], None] | None = None,
              on_fail: Callable[[str], None] | None = None) -> None:
        if self.busy:
            info(self.parent, "実行中", "別の処理が実行中です。終わってからもう一度実行してください。")
            return
        self.log.add(f"▶ {title}")

        def ok(result):
            self.busy = False
            self.log.add(f"✔ {title} が終わりました")
            if on_done:
                on_done(result)

        def ng(msg: str):
            self.busy = False
            self.log.add(f"✖ {title}: {msg.splitlines()[0] if msg else ''}")
            if on_fail:
                on_fail(msg)
            else:
                error(self.parent, title, msg)

        if self.sync:
            try:
                result = fn(LineStream(self.log.add))
            except Exception as e:  # noqa: BLE001
                ng(_message(e))
            else:
                ok(result)
            return
        self.busy = True
        th = QThread(self.parent)
        job = _Job(fn)
        job.moveToThread(th)
        th.started.connect(job.run)
        job.line.connect(self.log.add)
        job.done.connect(ok)
        job.failed.connect(ng)
        job.done.connect(th.quit)
        job.failed.connect(th.quit)
        th.finished.connect(lambda: self._threads.remove((th, job)) if (th, job) in self._threads else None)
        self._threads.append((th, job))
        th.start()

    def wait(self, ms: int = 600_000) -> None:
        """実行中の処理が終わるまで待つ（テスト用）。"""
        import time

        end = time.monotonic() + ms / 1000
        while self.busy and time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.01)


# ---------------------------------------------------------------- 画面部品
class LogPanel(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setPlaceholderText("実行した処理の記録がここに表示されます")

    def add(self, text: str) -> None:
        self.appendPlainText(text)


def label(text: str = "", *, muted=False, warn=False, err=False, badge=False, wrap=True) -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    for k, v in (("muted", muted), ("warn", warn), ("error", err), ("badge", badge)):
        if v:
            lb.setProperty(k, True)
    return lb


def button(text: str, slot: Callable | None = None, *, primary=False, danger=False, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", True)
    if danger:
        b.setProperty("danger", True)
    if tip:
        b.setToolTip(tip)
    if slot:
        b.clicked.connect(slot)
    return b


def hbox(*widgets, stretch=True) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    for x in widgets:
        lay.addWidget(x)
    if stretch:
        lay.addStretch(1)
    return w


def form(rows: list[tuple[str, QWidget]]) -> QWidget:
    w = QWidget()
    f = QFormLayout(w)
    f.setLabelAlignment(Qt.AlignRight)
    for k, v in rows:
        f.addRow(k, v)
    return w


def table(headers: list[str], *, select_rows=True, stretch_col: int | None = None) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    if select_rows:
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch_col is not None:
        h.setSectionResizeMode(stretch_col, QHeaderView.Stretch)
    return t


def fill(t: QTableWidget, rows: list[list[Any]], *, data: list[Any] | None = None,
         colors: dict[int, Callable[[Any], str | None]] | None = None) -> None:
    t.setRowCount(0)
    for i, r in enumerate(rows):
        t.insertRow(i)
        for j, v in enumerate(r):
            it = QTableWidgetItem("" if v is None else str(v))
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if colors and j in colors:
                c = colors[j](v)
                if c:
                    it.setForeground(QColor(c))
            if j == 0 and data is not None:
                it.setData(Qt.UserRole, data[i])
            t.setItem(i, j, it)


def selected_data(t: QTableWidget) -> Any:
    rows = t.selectionModel().selectedRows()
    if not rows:
        return None
    it = t.item(rows[0].row(), 0)
    return it.data(Qt.UserRole) if it else None


class PathEdit(QWidget):
    """パス入力欄＋参照ボタン。"""

    def __init__(self, *, directory=False, filter: str = "", placeholder: str = ""):
        super().__init__()
        self.directory = directory
        self.filter = filter
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit, 1)
        lay.addWidget(button("参照…", self.browse))

    def browse(self) -> None:
        if self.directory:
            p = QFileDialog.getExistingDirectory(self, "フォルダを選択", self.edit.text() or str(Path.home()))
        else:
            p, _ = QFileDialog.getOpenFileName(self, "ファイルを選択", self.edit.text() or str(Path.home()), self.filter)
        if p:
            self.edit.setText(p)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, s: str) -> None:
        self.edit.setText(s)


def open_local(path: str | Path) -> None:
    """ローカルのファイル・フォルダを OS の既定アプリで開く（PDF なら PDF ビューア）。"""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class Dialogs:
    """メッセージ表示の切り替え。自己診断・テストでは表示せず記録する（画面のない環境でも止まらない）。"""
    interactive = True
    confirm_answer = False
    shown: list[tuple[str, str, str]] = []


def noninteractive(confirm_answer: bool = False) -> None:
    Dialogs.interactive = False
    Dialogs.confirm_answer = confirm_answer
    Dialogs.shown = []


def error(parent: QWidget, title: str, msg: str) -> None:
    if not Dialogs.interactive:
        Dialogs.shown.append(("error", title, msg))
        return
    QMessageBox.warning(parent, title, msg)


def info(parent: QWidget, title: str, msg: str) -> None:
    if not Dialogs.interactive:
        Dialogs.shown.append(("info", title, msg))
        return
    QMessageBox.information(parent, title, msg)


def confirm(parent: QWidget, title: str, msg: str) -> bool:
    if not Dialogs.interactive:
        Dialogs.shown.append(("confirm", title, msg))
        return Dialogs.confirm_answer
    return QMessageBox.question(parent, title, msg, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes


def human_bytes(n: int | None) -> str:
    from ..reports import human_bytes as hb

    return hb(n)


def setup_offscreen_if_requested(argv: list[str]) -> None:
    """--selftest のときは画面のない環境でも動くよう offscreen で起動する。"""
    if "--selftest" in argv and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
