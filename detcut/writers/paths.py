"""出力ファイルに書き込むメディアのパス表記。"""

from __future__ import annotations

import os
import re


def output_path(path: str, path_map: list[list[str]] | None = None, windows_paths: object = "auto") -> str:
    """絶対パス化し、path_map の前方一致置換（例: /mnt/c/ → C:\\）と区切り文字の統一をする。"""
    p = os.path.normpath(os.path.abspath(path))
    mapped = False
    for src, dst in path_map or []:
        s = src.replace("\\", "/")
        q = p.replace("\\", "/")
        if q.lower().startswith(s.lower()) if os.name == "nt" else q.startswith(s):
            p = dst + q[len(s):]
            mapped = True
            break
    use_win = windows_paths is True or (
        windows_paths == "auto" and (os.name == "nt" or mapped and re.match(r"^[A-Za-z]:[\\/]", p))
    )
    if use_win:
        p = p.replace("/", "\\")
        p = re.sub(r"\\{2,}", r"\\", p) if not p.startswith("\\\\") else "\\\\" + re.sub(r"\\{2,}", r"\\", p[2:])
    return p
