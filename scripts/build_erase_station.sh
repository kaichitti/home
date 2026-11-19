#!/usr/bin/env bash
# 消去ステーション向けビルド（resq-erase）を作る。
#
# - 復旧ビルド（ルートの pyproject.toml）は resq_erase を含まない
# - このビルドは resq_erase に加え、消去後の検証で使う復旧エンジン（resq）を含む
#   （復旧機に消去機能は入れない。消去機に復旧エンジン（読み取り専用の検証用）は入れる。企画書 §8.2）
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=build/erase-station
rm -rf "$OUT"
mkdir -p "$OUT/src" dist
cp -r src/resq src/resq_erase "$OUT/src/"
find "$OUT/src" -name __pycache__ -type d -prune -exec rm -rf {} +
VERSION=$(python3 -c "import re;print(re.search(r'__version__ = \"(.+)\"', open('src/resq_erase/__init__.py').read()).group(1))")
cat > "$OUT/pyproject.toml" <<EOF
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "resq-erase"
version = "$VERSION"
description = "消去ステーション専用ビルド（完全消去＋検証用の復旧エンジン）"
requires-python = ">=3.12"
license = { text = "GPL-3.0-or-later" }
dependencies = ["typer>=0.12", "rich>=13", "jinja2>=3.1", "pillow>=10", "PySide6-Essentials>=6.6",
                "weasyprint>=60", "qrcode>=7"]

[project.scripts]
resq-erase = "resq_erase.cli:app"

[project.gui-scripts]
resq-erase-gui = "resq_erase.gui:main"

[tool.setuptools.packages.find]
where = ["src"]
include = ["resq*"]

[tool.setuptools.package-data]
resq = ["reports/templates/*.html", "reports/templates/*.css"]
resq_erase = ["templates/*.html"]
EOF
python3 -m pip wheel --no-deps -q -w dist "$OUT"
ls -1 dist/resq_erase-*.whl
