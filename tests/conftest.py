from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from resq.cases import create_case, open_workspace
from resq.config import Workspace
from resq.intake import add_consent

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
DATA = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def fixtures() -> Path:
    if not (FIXTURES / "expected.json").exists():
        subprocess.run([str(ROOT / "scripts" / "make_fixtures.sh")], check=True)
    return FIXTURES


@pytest.fixture(scope="session")
def expected(fixtures) -> dict:
    return json.loads((fixtures / "expected.json").read_text())


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "resq-data"
    monkeypatch.setenv("RESQ_HOME", str(root))
    w, db = open_workspace(Workspace(root))
    yield w, db
    db.close()


@pytest.fixture
def case(ws):
    w, db = ws
    c = create_case(w, db, customer="テスト 太郎", price_cap=19800)
    add_consent(c, form_version="2026.11", id_method="運転免許証", ownership="本人所有")
    return c


def ro_copy(src: Path, dest_dir: Path) -> Path:
    """フィクスチャを読み取り専用コピーにする（＝ライトブロッカー越しの原本に相当）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    shutil.copyfile(src, dst)
    os.chmod(dst, 0o444)
    return dst


@pytest.fixture
def ro(tmp_path):
    def _ro(src: Path) -> Path:
        return ro_copy(src, tmp_path / "originals")
    return _ro
