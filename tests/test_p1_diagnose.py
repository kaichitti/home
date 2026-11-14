"""P1: 診断と判定。"""
from __future__ import annotations

from pathlib import Path

import pytest

from resq import diagnose as D

DATA = Path(__file__).parent / "data"


def _img(fixtures):
    return str(fixtures / "deleted.img")


def test_healthy_degraded_danger_differ(fixtures):
    h = D.diagnose(_img(fixtures), smart_json=DATA / "smart_healthy.json")
    g = D.diagnose(_img(fixtures), smart_json=DATA / "smart_degraded.json")
    x = D.diagnose(_img(fixtures), smart_json=DATA / "smart_danger.json")
    assert (h.verdict, h.level, h.requires_confirmation) == (D.IN_HOUSE, "論理", False)
    assert (g.verdict, g.level, g.requires_confirmation) == (D.IN_HOUSE, "軽度物理", True)
    assert x.verdict == D.REFER and x.level == "重度物理"
    assert g.smart["pending"] == 8
    assert {"fat32"} <= {f["type"] for f in h.filesystems}
    assert not x.filesystems  # 危険機は構造の読み取りを省略


def test_nvme_critical_warning_refers(fixtures):
    d = D.diagnose(_img(fixtures), smart_json=DATA / "smart_nvme_critical.json")
    assert d.verdict == D.REFER


def test_bitlocker_pseudo_header_is_conditional(tmp_path):
    p = tmp_path / "bitlocker.img"
    sector = bytearray(512)
    sector[0:3] = b"\xeb\x58\x90"
    sector[3:11] = b"-FVE-FS-"
    sector[510:512] = b"\x55\xaa"
    p.write_bytes(bytes(sector) + b"\0" * (1 << 20))
    d = D.diagnose(str(p))
    assert d.verdict == D.CONDITIONAL
    assert d.encryption and d.encryption[0]["type"] == "BitLocker"
    assert any("回復キー" in r for r in d.reasons)


def test_bitlocker_inside_partition(tmp_path, fixtures):
    raw = bytearray((fixtures / "parttable_intact.img").read_bytes())
    off = 2048 * 512
    raw[off + 3:off + 11] = b"-FVE-FS-"
    p = tmp_path / "bl_part.img"
    p.write_bytes(raw)
    d = D.diagnose(str(p))
    assert d.verdict == D.CONDITIONAL and d.encryption[0]["offset"] == off


def test_luks_header_is_conditional(tmp_path):
    p = tmp_path / "luks.img"
    p.write_bytes(b"LUKS\xba\xbe\x00\x02" + b"\0" * 8192)
    assert D.diagnose(str(p)).verdict == D.CONDITIONAL


def test_abnormal_noise_refers_without_touching_media(tmp_path):
    # 存在しないパス＝媒体に一切アクセスしていないこと
    d = D.diagnose(str(tmp_path / "never-opened.img"), symptoms=["カチカチと異音"])
    assert d.verdict == D.REFER
    assert any("アクセスせず" in w for w in d.warnings)


@pytest.mark.parametrize("symptom,verdict", [
    ("SSD削除", D.REJECT), ("スマホ初期化", D.REJECT), ("パスコード不明", D.REJECT), ("認識しない", D.REFER),
])
def test_symptom_rules(tmp_path, symptom, verdict):
    assert D.diagnose(str(tmp_path / "x.img"), symptoms=[symptom]).verdict == verdict


def test_unformatted_image_warns(tmp_path):
    p = tmp_path / "blank.img"
    p.write_bytes(b"\0" * (2 << 20))
    d = D.diagnose(str(p))
    assert d.verdict == D.IN_HOUSE and any("S5" in w for w in d.warnings)


def test_save_and_advance(case, fixtures):
    d = D.diagnose(_img(fixtures), smart_json=DATA / "smart_healthy.json", ctx=case.ctx)
    D.save(d, case)
    assert case.row["status"] == "診断済"
    assert D.latest(case)["verdict"] == D.IN_HOUSE
    ops = {r["op"] for r in case.db.all("SELECT op FROM events WHERE case_id=?", case.id)}
    assert {"diagnose.mmls", "diagnose.fsstat"} <= ops
