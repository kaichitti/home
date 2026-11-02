"""LPの本文（docs/lp.fragment.html）から、単体で開ける docs/index.html を作る。

  python tools/build_lp.py

本文は <title> / <meta> / <link> / <style> を先頭に置き、その後にページ内容を書く形式。
最初の </style> までを <head> に、残りを <body> に入れる。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "lp.fragment.html"
DST = ROOT / "docs" / "index.html"


def build(fragment: str) -> str:
    head, sep, body = fragment.partition("</style>")
    if not sep:
        raise SystemExit("lp.fragment.html に </style> がありません")
    return (
        "<!doctype html>\n<html lang=\"ja\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        + head + sep + "\n</head>\n<body>\n" + body.strip() + "\n</body>\n</html>\n"
    )


def main() -> int:
    DST.write_text(build(SRC.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    print(f"作成しました: {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
