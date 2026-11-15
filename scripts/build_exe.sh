#!/usr/bin/env bash
# Linux（Ubuntu 24.04 以降）向けの単体実行ファイルを作る。
#   dist/resq-<版>-linux-x86_64.tar.gz        復旧作業機用（resq / resq-web）
#   dist/resq-erase-<版>-linux-x86_64.tar.gz  消去ステーション用（resq-erase）※復旧作業機には入れない
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import re;print(re.search(r'__version__ = \"(.+)\"', open('src/resq/__init__.py').read()).group(1))")
python3 -m PyInstaller packaging/resq.spec --distpath dist/bin --workpath build/pyi --noconfirm --log-level WARN
[ -f fixtures/expected.json ] || ./scripts/make_fixtures.sh
python3 scripts/smoke_exe.py dist/bin fixtures
STAGE=build/pkg
rm -rf "$STAGE" && mkdir -p "$STAGE/resq-$VERSION" "$STAGE/resq-erase-$VERSION"
cp dist/bin/resq dist/bin/resq-web packaging/README-linux.txt "$STAGE/resq-$VERSION/"
cp dist/bin/resq-erase packaging/README-erase.txt "$STAGE/resq-erase-$VERSION/"
tar -C "$STAGE" -czf "dist/resq-$VERSION-linux-x86_64.tar.gz" "resq-$VERSION"
tar -C "$STAGE" -czf "dist/resq-erase-$VERSION-linux-x86_64.tar.gz" "resq-erase-$VERSION"
( cd dist && sha256sum resq-*"$VERSION"-linux-x86_64.tar.gz > SHA256SUMS-linux.txt )
ls -la dist/*.tar.gz dist/SHA256SUMS-linux.txt
