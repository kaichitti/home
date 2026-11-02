"""AviUtl2 のオブジェクトエイリアス（.object）の書き出し（ショートカットボタン F15 用）。

  [Object]     frame=0,長さ-1
  [Object.0]   effect.name=… （メディア入力）
  [Object.N]   最後が描画/再生
"""

from __future__ import annotations

from detcut.timeline.model import Clip
from detcut.writers.aup2 import Aup2Writer
from detcut.writers.ini import Section, serialize_ini


def build_object(writer: Aup2Writer, clip: Clip) -> str:
    sections = [Section("Object", [("frame", f"0,{clip.length - 1}")])]
    for j, eff in enumerate(writer.effects_for(clip)):
        sections.append(Section(f"Object.{j}", list(eff)))
    return serialize_ini(sections, "\r\n")
