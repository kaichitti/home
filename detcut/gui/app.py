"""DetCut の GUI（tkinter）。

- 入力ファイルの選択（tkinterdnd2 が入っていればウィンドウへのドラッグ&ドロップも可。
  run_gui.bat に動画をドロップしても起動できる）
- プリセット選択・カット設定の調整・波形とカット位置のプレビュー
- 書き出し（.aup2 / .exo / レポート）
- ショートカットボタン（プリセットの shortcuts。押すと .object / .exo を作ってフォルダを開く）
重い処理は別スレッドで行い、結果はキュー経由で画面に反映する。
"""

from __future__ import annotations

import os
import queue
import threading
import traceback
from typing import Any, Callable

from detcut.common import DetCutError
from detcut.gui.controller import (CUT_FIELDS, FEATURE_FLAGS, Controller, PreviewData, UiState, list_presets,
                                   preview_geometry, reveal_in_explorer, state_from_config)

try:  # pragma: no cover - 実行環境依存
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError:  # pragma: no cover
    tk = None  # type: ignore


def _make_root():
    try:
        from tkinterdnd2 import TkinterDnD  # type: ignore
        return TkinterDnD.Tk(), True
    except Exception:  # noqa: BLE001 - 入っていなければ通常のTk
        return tk.Tk(), False


class App:
    def __init__(self, root, dnd: bool, input_path: str | None, preset: str | None):
        self.root = root
        self.dnd = dnd
        self.q: queue.Queue = queue.Queue()
        self.ctrl = Controller(log=lambda m: self.q.put(("log", m)))
        self.busy = False
        self.preview: PreviewData | None = None
        self._after_id = None
        root.title("DetCut - AviUtl向け 決定論的自動編集")
        root.geometry("980x760")

        self.v_input = tk.StringVar(value=input_path or "")
        presets = [str(p) for p in list_presets()]
        self.v_preset = tk.StringVar(value=preset or (presets[0] if presets else ""))
        self.v_output = tk.StringVar()
        self.v_target = tk.StringVar(value="aup2")
        self.v_mode = tk.StringVar(value="jetcut")
        self.v_cut = {k: tk.DoubleVar() for k, *_ in CUT_FIELDS}
        self.v_flags = {k: tk.BooleanVar() for k, _ in FEATURE_FLAGS}
        self.v_stats = tk.StringVar(value="入力ファイルを選んで「解析・プレビュー」を押してください")

        self._build(presets)
        self.load_preset()
        root.after(100, self._poll)
        if input_path:
            root.after(300, self.analyze)

    # ------------------------------------------------------------ layout
    def _build(self, presets: list[str]) -> None:
        r = self.root
        top = ttk.Frame(r, padding=8)
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="入力").grid(row=0, column=0, sticky="w")
        e_in = ttk.Entry(top, textvariable=self.v_input)
        e_in.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="参照…", command=self.pick_input).grid(row=0, column=2)
        if self.dnd:
            from tkinterdnd2 import DND_FILES  # type: ignore
            for w in (e_in, r):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

        ttk.Label(top, text="プリセット").grid(row=1, column=0, sticky="w")
        cb = ttk.Combobox(top, textvariable=self.v_preset, values=presets)
        cb.grid(row=1, column=1, sticky="ew", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda _e: self.load_preset())
        ttk.Button(top, text="参照…", command=self.pick_preset).grid(row=1, column=2)

        ttk.Label(top, text="出力先").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.v_output).grid(row=2, column=1, sticky="ew", padx=4)
        ttk.Button(top, text="参照…", command=self.pick_output).grid(row=2, column=2)

        mid = ttk.Frame(r, padding=(8, 0))
        mid.pack(fill="x")
        cutf = ttk.LabelFrame(mid, text="カット設定", padding=6)
        cutf.pack(side="left", fill="x", expand=True)
        ttk.Label(cutf, text="モード").grid(row=0, column=0, sticky="w")
        m = ttk.Combobox(cutf, textvariable=self.v_mode, values=["jetcut", "compress"], width=10, state="readonly")
        m.grid(row=0, column=1, sticky="w")
        m.bind("<<ComboboxSelected>>", lambda _e: self._schedule_preview())
        for i, (key, label, lo, hi, step) in enumerate(CUT_FIELDS):
            row, col = 1 + i // 2, (i % 2) * 2
            ttk.Label(cutf, text=label).grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 12, 4))
            sp = ttk.Spinbox(cutf, from_=lo, to=hi, increment=step, textvariable=self.v_cut[key], width=8,
                             command=self._schedule_preview)
            sp.grid(row=row, column=col + 1, sticky="w")
            sp.bind("<Return>", lambda _e: self._schedule_preview())
            sp.bind("<FocusOut>", lambda _e: self._schedule_preview())

        side = ttk.Frame(mid, padding=(8, 0))
        side.pack(side="left", fill="y")
        feat = ttk.LabelFrame(side, text="機能", padding=6)
        feat.pack(fill="x")
        for k, label in FEATURE_FLAGS:
            ttk.Checkbutton(feat, text=label, variable=self.v_flags[k]).pack(anchor="w")
        ttk.Label(side, text="出力形式").pack(anchor="w", pady=(8, 0))
        ttk.Combobox(side, textvariable=self.v_target, values=["aup2", "exo", "both"], width=8,
                     state="readonly").pack(anchor="w")

        btns = ttk.Frame(r, padding=8)
        btns.pack(fill="x")
        ttk.Button(btns, text="解析・プレビュー", command=self.analyze).pack(side="left")
        ttk.Button(btns, text="提案のしきい値を使う", command=self.use_suggestion).pack(side="left", padx=4)
        ttk.Button(btns, text="書き出し", command=self.export).pack(side="left", padx=4)
        ttk.Button(btns, text="出力フォルダを開く", command=self.open_output).pack(side="left", padx=4)

        self.canvas = tk.Canvas(r, height=180, background="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill="x", padx=8)
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        ttk.Label(r, textvariable=self.v_stats, padding=(8, 4)).pack(fill="x")

        self.sc_frame = ttk.LabelFrame(r, text="ショートカットボタン（押すと .object / .exo を作ってフォルダを開きます）",
                                       padding=6)
        self.sc_frame.pack(fill="x", padx=8)

        self.logbox = ScrolledText(r, height=8)
        self.logbox.pack(fill="both", expand=True, padx=8, pady=8)

    # ------------------------------------------------------------ state
    def state(self) -> UiState:
        cut = {}
        for k, *_ in CUT_FIELDS:
            try:
                cut[k] = float(self.v_cut[k].get())
            except (tk.TclError, ValueError):
                cut[k] = 0.0
        return UiState(input_path=self.v_input.get().strip().strip('"'), preset_path=self.v_preset.get().strip(),
                       output_dir=self.v_output.get().strip(), target=self.v_target.get(), mode=self.v_mode.get(),
                       cut=cut, flags={k: bool(v.get()) for k, v in self.v_flags.items()})

    def load_preset(self) -> None:
        try:
            cfg = self.ctrl.config(UiState(preset_path=self.v_preset.get().strip()))
        except DetCutError as e:
            self.log(f"エラー: {e}")
            return
        st = state_from_config(cfg)
        self.v_output.set(st.output_dir)
        self.v_target.set(st.target)
        self.v_mode.set(st.mode)
        for k, v in st.cut.items():
            self.v_cut[k].set(v)
        for k, v in st.flags.items():
            self.v_flags[k].set(v)
        for w in self.sc_frame.winfo_children():
            w.destroy()
        if not cfg["shortcuts"]:
            ttk.Label(self.sc_frame, text="（プリセットに shortcuts がありません）").pack(anchor="w")
        for sc in cfg["shortcuts"]:
            ttk.Button(self.sc_frame, text=sc["label"],
                       command=lambda sid=sc["id"]: self.shortcut(sid)).pack(side="left", padx=2)
        self.log(f"プリセットを読み込みました: {cfg.preset_path or '（既定値）'}")

    # ------------------------------------------------------------ actions
    def pick_input(self) -> None:
        p = filedialog.askopenfilename(title="動画・音声ファイル",
                                       filetypes=[("動画・音声", "*.mp4 *.mov *.mkv *.avi *.m4v *.wav *.mp3 *.m4a *.flac"),
                                                  ("すべて", "*.*")])
        if p:
            self.v_input.set(p)
            self.analyze()

    def pick_preset(self) -> None:
        p = filedialog.askopenfilename(title="プリセット", filetypes=[("YAML", "*.yaml *.yml")])
        if p:
            self.v_preset.set(p)
            self.load_preset()

    def pick_output(self) -> None:
        p = filedialog.askdirectory(title="出力先")
        if p:
            self.v_output.set(p)

    def _on_drop(self, event) -> None:
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self.v_input.set(paths[0])
            self.analyze()

    def _run(self, label: str, fn: Callable[[], Any], on_done: Callable[[Any], None]) -> None:
        if self.busy:
            return
        self.busy = True
        self.log(f"--- {label}")

        def work():
            try:
                self.q.put(("done", (on_done, fn())))
            except DetCutError as e:
                self.q.put(("error", str(e)))
            except Exception:  # noqa: BLE001
                self.q.put(("error", traceback.format_exc()))
        threading.Thread(target=work, daemon=True).start()

    def analyze(self) -> None:
        st = self.state()
        if not st.input_path:
            messagebox.showinfo("DetCut", "入力ファイルを選んでください")
            return
        self._run("解析", lambda: self.ctrl.analyze(st), self._show_preview)

    def _schedule_preview(self) -> None:
        if self.ctrl.prep is None:
            return
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(300, self.analyze)

    def _show_preview(self, p: PreviewData) -> None:
        self.preview = p
        msg = p.stats
        if p.suggestion:
            msg += f"   提案: 開始 {p.suggestion.speech_on_db}dB / 終了 {p.suggestion.speech_off_db}dB"
        self.v_stats.set(msg)
        self.draw()

    def use_suggestion(self) -> None:
        if not self.preview or not self.preview.suggestion:
            return
        self.v_cut["speech_on_db"].set(self.preview.suggestion.speech_on_db)
        self.v_cut["speech_off_db"].set(self.preview.suggestion.speech_off_db)
        self.analyze()

    def export(self) -> None:
        st = self.state()
        if not st.input_path:
            messagebox.showinfo("DetCut", "入力ファイルを選んでください")
            return

        def done(res):
            for w in res.warnings:
                self.log(f"[注意] {w}")
            for k, v in sorted(res.files.items()):
                self.log(f"{k}: {v}")
            s = res.stats
            self.log(f"完了: {s['keeps']}区間 / テロップ{s['telops']} / SE{s['se']} / BGM{s['bgm_pieces']}")
            target = res.files.get("aup2") or res.files.get("exo")
            if target:
                reveal_in_explorer(target)
        self._run("書き出し", lambda: self.ctrl.export(st), done)

    def shortcut(self, sid: str) -> None:
        st = self.state()

        def done(paths):
            for p in paths:
                self.log(p)
            if paths:
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(paths[0])
                except tk.TclError:
                    pass
                reveal_in_explorer(paths[0])
        self._run(f"ショートカット {sid}", lambda: self.ctrl.shortcut(st, sid), done)

    def open_output(self) -> None:
        d = self.v_output.get().strip()
        if d:
            os.makedirs(d, exist_ok=True)
            reveal_in_explorer(os.path.join(d, "."))

    # ------------------------------------------------------------ drawing / queue
    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        p = self.preview
        if p is None:
            return
        w, h = max(10, c.winfo_width()), max(10, c.winfo_height())
        g = preview_geometry(p, w, h)
        for a, b in g["keeps"]:
            c.create_rectangle(a, 0, b, h, fill="#20402a", outline="")
        if len(g["line"]) >= 4:
            c.create_line(*g["line"], fill="#9ecbff")
        c.create_line(0, g["on_y"], w, g["on_y"], fill="#ffb347", dash=(4, 2))
        c.create_line(0, g["off_y"], w, g["off_y"], fill="#ff6961", dash=(2, 2))
        c.create_text(6, 6, anchor="nw", fill="#cccccc",
                      text=f"緑=残す区間  橙=発話開始 {p.on_db}dB  赤=発話終了 {p.off_db}dB")

    def log(self, msg: str) -> None:
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "done":
                    self.busy = False
                    cb, value = payload
                    cb(value)
                elif kind == "error":
                    self.busy = False
                    self.log(f"エラー: {payload}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)


def main(input_path: str | None = None, preset: str | None = None) -> int:
    if tk is None:
        print("tkinter が使えません。Windows版のPython（python.org）には標準で含まれています。")
        return 1
    root, dnd = _make_root()
    App(root, dnd, input_path, preset)
    root.mainloop()
    return 0
