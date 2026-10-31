"""GUIの動作確認（tkinter と画面がある環境だけで実行。Linuxなら xvfb-run で動く）。"""

from __future__ import annotations

import os
import time

import pytest

from conftest import ROOT, needs_ffmpeg

tk = pytest.importorskip("tkinter")


@needs_ffmpeg
@pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="画面（DISPLAY）が必要")
def test_gui_end_to_end(sample_mp4, tmp_path, monkeypatch):
    from detcut.gui import app as A
    revealed = []
    monkeypatch.setattr(A, "reveal_in_explorer", lambda p: revealed.append(p))
    root, dnd = A._make_root()
    gui = A.App(root, dnd, str(sample_mp4), str(ROOT / "presets" / "gadget_review.yaml"))
    gui.v_output.set(str(tmp_path / "out"))

    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            root.update()
            time.sleep(0.02)

    def wait_idle(timeout=60):
        pump(0.3)
        t0 = time.time()
        while gui.busy and time.time() - t0 < timeout:
            pump(0.1)
        pump(0.2)

    try:
        pump(0.5)
        wait_idle()
        assert gui.preview is not None and len(gui.preview.keeps_ms) == 3
        assert "3区間を残す" in gui.v_stats.get()
        gui.export()
        wait_idle()
        assert (tmp_path / "out" / "sample_talk.aup2").exists()
        buttons = gui.sc_frame.winfo_children()
        assert [b.cget("text") for b in buttons] == ["驚き（テロップ＋SE）", "ポイント解説"]
        buttons[1].invoke()
        wait_idle()
        assert (tmp_path / "out" / "shortcuts" / "point.exo").exists()
        assert revealed and revealed[-1].endswith("point.exo")
    finally:
        root.destroy()
