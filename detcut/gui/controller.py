"""GUIのロジック部分（画面に依存しないのでテストできる）。"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from detcut.analysis.rms import envelope_db
from detcut.analysis.suggest import Suggestion, suggest
from detcut.config import Config, find_presets, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# GUIで調整できる項目（キー, ラベル, 最小, 最大, 刻み）
CUT_FIELDS = [
    ("speech_on_db", "発話開始 dB", -90, 0, 1),
    ("speech_off_db", "発話終了 dB", -90, 0, 1),
    ("min_silence_ms", "最小無音長 ms", 0, 5000, 10),
    ("min_speech_ms", "最小発話長 ms", 0, 2000, 10),
    ("pad_before_ms", "前の余白 ms", 0, 2000, 10),
    ("pad_after_ms", "後の余白 ms", 0, 2000, 10),
    ("merge_gap_ms", "結合する隙間 ms", 0, 2000, 10),
    ("compress_to_ms", "圧縮後の間 ms", 0, 3000, 10),
]
FEATURE_FLAGS = [("telop.enabled", "テロップ"), ("se.enabled", "SE"), ("bgm.enabled", "BGM"), ("zoom.enabled", "ズーム")]


@dataclass
class PreviewData:
    envelope: list[float]
    duration_ms: int
    keeps_ms: list[tuple[int, int]]
    on_db: float
    off_db: float
    stats: str
    suggestion: Suggestion | None = None


@dataclass
class UiState:
    input_path: str = ""
    preset_path: str = ""
    output_dir: str = ""
    target: str = "aup2"
    mode: str = "jetcut"
    cut: dict[str, float] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)

    def overrides(self, base: Config | None = None) -> list[str]:
        """プリセットとの差分だけを --set 形式で返す（差分がなければ空）。"""
        out = []
        cut0 = base["cut"] if base else {}
        if base is None or self.mode != cut0.get("mode"):
            out.append(f"cut.mode={self.mode}")
        for k, v in sorted(self.cut.items()):
            if base is None or cut0.get(k) != v:
                out.append(f"cut.{k}={_num(v)}")
        for k, v in sorted(self.flags.items()):
            sec, key = k.split(".")
            if base is None or base[sec][key] != v:
                out.append(f"{k}={'true' if v else 'false'}")
        return out


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def list_presets() -> list[Path]:
    return find_presets(Path.cwd() / "presets", REPO_ROOT / "presets")


def state_from_config(cfg: Config, input_path: str = "") -> UiState:
    return UiState(
        input_path=input_path,
        preset_path=cfg.preset_path or "",
        output_dir=cfg["output"]["dir"],
        target=cfg["project"]["target"],
        mode=cfg["cut"]["mode"],
        cut={k: cfg["cut"][k] for k, *_ in CUT_FIELDS},
        flags={k: bool(cfg[k.split(".")[0]][k.split(".")[1]]) for k, _ in FEATURE_FLAGS},
    )


class Controller:
    def __init__(self, log: Callable[[str], None] = print):
        self.log = log
        self.prep = None
        self.prep_key: tuple[str, str] | None = None

    def config(self, state: UiState) -> Config:
        base = load_config(state.preset_path or None)
        return load_config(state.preset_path or None, state.overrides(base))

    def analyze(self, state: UiState, progress: Callable[[float], None] | None = None) -> PreviewData:
        from detcut.pipeline import detect, prepare
        cfg = self.config(state)
        key = (os.path.abspath(state.input_path), cfg["project"]["fps"])
        if self.prep is None or self.prep_key != key:
            self.prep = prepare(state.input_path, cfg, self.log, progress)
            self.prep_key = key
        _, cl = detect(self.prep, cfg["cut"])
        e = self.prep.energy
        tb = self.prep.tb
        dur = e.total_samples * 1000 // e.sample_rate
        keeps = [(tb.frame_to_ms(k.src_start_frame), tb.frame_to_ms(k.src_end_frame)) for k in cl.keeps]
        red = 100 - cl.total_tl_frames * 100 // cl.total_src_frames if cl.total_src_frames else 0
        stats = (f"{len(cl.keeps)}区間を残す / {len(cl.cuts)}区間をカット  "
                 f"{dur / 1000:.1f}s → {tb.frame_to_ms(cl.total_tl_frames) / 1000:.1f}s（-{red}%）")
        return PreviewData(envelope=envelope_db(e.energies, e.window, 1200), duration_ms=dur, keeps_ms=keeps,
                           on_db=cfg["cut"]["speech_on_db"], off_db=cfg["cut"]["speech_off_db"], stats=stats,
                           suggestion=suggest(e.energies, e.window))

    def export(self, state: UiState):
        from detcut.pipeline import make_plan, prepare, write_outputs
        cfg = self.config(state)
        prep = prepare(state.input_path, cfg, self.log)
        plan = make_plan(prep, cfg, self.log)
        return write_outputs(plan, state.output_dir or None, state.target)

    def shortcut(self, state: UiState, sid: str) -> list[str]:
        from detcut.shortcuts import find_shortcut, write_shortcut
        cfg = self.config(state)
        fps = self.prep.tb.fps if self.prep is not None else None
        return write_shortcut(find_shortcut(cfg, sid), cfg, state.output_dir or cfg["output"]["dir"], fps)


# ---------------------------------------------------------------- drawing geometry

def preview_geometry(p: PreviewData, width: int, height: int, lo_db: float = -90.0) -> dict[str, Any]:
    """波形プレビューの描画要素（座標）を計算する。"""
    def y_of(db: float) -> float:
        db = max(lo_db, min(0.0, db))
        return height - (db - lo_db) / (0.0 - lo_db) * height

    n = len(p.envelope)
    points: list[float] = []
    for i, db in enumerate(p.envelope):
        x = i * (width - 1) / max(1, n - 1)
        points += [x, y_of(db)]
    keeps = []
    if p.duration_ms > 0:
        for a, b in p.keeps_ms:
            keeps.append((a * width / p.duration_ms, b * width / p.duration_ms))
    return {"line": points, "keeps": keeps, "on_y": y_of(p.on_db), "off_y": y_of(p.off_db)}


def reveal_in_explorer(path: str) -> None:
    """ファイルをエクスプローラー等で選択状態にして開く。"""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError:
        pass
