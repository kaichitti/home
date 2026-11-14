"""P0: フィクスチャ・audit・safety・DB・受付の基盤。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from resq import audit, intake, safety
from resq.cases import create_case
from resq.errors import ResqError, SafetyError

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- フィクスチャ
def test_fixtures_and_expected_json(fixtures, expected):
    assert set(expected["images"]) >= {"deleted", "overwrite", "quickformat", "parttable"}
    for name, img in expected["images"].items():
        p = fixtures / img["file"]
        assert p.is_file(), name
        assert hashlib.sha256(p.read_bytes()).hexdigest() == img["image_sha256"]
        kinds = {f["type"] for f in img["files"]}
        assert {"jpg", "pdf", "docx"} <= kinds
    states = {f["state"] for f in expected["images"]["deleted"]["files"]}
    assert states == {"present", "deleted"}
    assert any(f["state"] == "overwritten" for f in expected["images"]["overwrite"]["files"])


# ---------------------------------------------------------------- audit
@pytest.mark.parametrize("prog", ["dd", "mkfs.vfat", "wipefs", "fdisk", "blkdiscard", "shred", "hdparm",
                                  "/usr/sbin/mkfs.ext4", "nwipe", "sg_sanitize", "mount"])
def test_audit_refuses_destructive_programs(prog):
    with pytest.raises(SafetyError):
        audit.run([prog, "--help"], op="test")


def test_audit_refuses_device_args_unless_allowed():
    with pytest.raises(SafetyError):
        audit.run(["echo", "/dev/sda"], op="test")
    r = audit.run(["echo", "/dev/null-ish"], op="test", allow_device=True)
    assert r.returncode == 0


def test_audit_logs_and_redacts(case):
    secret = "123456-654321-111111-222222-333333-444444-555555-666666"
    r = audit.run(["echo", f"key={secret}"], op="test.secret", ctx=case.ctx, secrets=[secret])
    assert secret not in r.stdout
    logs = (case.dir / "logs" / "events.jsonl").read_text() + case.ws.log_path.read_text()
    assert "test.secret" in logs and secret not in logs
    rows = case.db.all("SELECT command FROM events WHERE case_id=? AND op='test.secret'", case.id)
    assert rows and all(secret not in r["command"] for r in rows)


def test_audit_failure_message_redacted():
    secret = "s3cr3t-passphrase"
    with pytest.raises(Exception) as ei:
        audit.run(["sh", "-c", f"echo {secret} >&2; exit 3"], op="t", secrets=[secret])
    assert secret not in str(ei.value)


def test_events_are_append_only(case):
    case.db.add_event(case.id, "x", "y", 0)
    with pytest.raises(sqlite3.DatabaseError):
        case.db.execute("UPDATE events SET op='tampered'")
    with pytest.raises(sqlite3.DatabaseError):
        case.db.execute("DELETE FROM events")


def test_no_secret_columns(case):
    cols = []
    for (t,) in case.db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols += [r[1].lower() for r in case.db.conn.execute(f"PRAGMA table_info({t})")]
    assert not [c for c in cols if any(k in c for k in ("key", "pass", "pin", "secret"))]


# ---------------------------------------------------------------- safety
@pytest.mark.parametrize("target", ["/dev/sda", "/dev/nvme0n1", "/dev/mmcblk0", "/dev/null"])
def test_safety_rejects_device_targets(case, target):
    with pytest.raises(SafetyError):
        safety.assert_writable_target(target, case_dir=case.dir)


def test_safety_rejects_outside_case_dir(case, tmp_path):
    with pytest.raises(SafetyError):
        safety.assert_writable_target(tmp_path / "elsewhere.img", case_dir=case.dir)
    with pytest.raises(SafetyError):
        safety.assert_writable_target(case.dir / ".." / "other" / "x", case_dir=case.dir)
    assert safety.assert_writable_target(case.dir / "images" / "a.dd", case_dir=case.dir)


def test_safety_rejects_same_file_as_source(case):
    p = case.dir / "images" / "src.dd"
    p.write_bytes(b"x")
    with pytest.raises(SafetyError):
        safety.assert_writable_target(p, case_dir=case.dir, source=p)


def test_safety_space_check(case):
    with pytest.raises(SafetyError, match="空き容量"):
        safety.assert_writable_target(case.dir / "images" / "big.dd", case_dir=case.dir,
                                      required_bytes=1 << 60)


def test_safety_source_must_be_readonly(tmp_path):
    p = tmp_path / "orig.img"
    p.write_bytes(b"\0" * 1024)
    with pytest.raises(SafetyError, match="書き込み権限"):
        safety.assert_source_readonly(p)
    p.chmod(0o444)
    safety.assert_source_readonly(p)
    with pytest.raises(SafetyError):
        safety.assert_source_readonly(tmp_path / "missing.img")


def test_safe_join_blocks_traversal(tmp_path):
    base = tmp_path / "out"
    base.mkdir()
    assert safety.safe_join(base, "../../etc/passwd") == base / "etc" / "passwd"
    assert safety.safe_join(base, "a\\..\\b") == base / "a" / "b"


# ---------------------------------------------------------------- Claude Code ガードレール
@pytest.mark.parametrize("cmd,rc", [
    ("ddrescue -n /dev/sdb out.img out.map", 2),
    ("smartctl -a /dev/nvme0", 2),
    ("cat /dev/mmcblk0 > x", 2),
    ("pytest -q", 0),
    ("./scripts/make_fixtures.sh", 0),
])
def test_hook_blocks_device_commands(cmd, rc):
    hook = ROOT / ".claude" / "hooks" / "block_devices.py"
    p = subprocess.run([sys.executable, str(hook)], input=json.dumps({"tool_input": {"command": cmd}}),
                       text=True, capture_output=True)
    assert p.returncode == rc


def test_settings_deny_list():
    s = json.loads((ROOT / ".claude" / "settings.json").read_text())
    deny = s["permissions"]["deny"]
    for needle in ("Bash(sudo *)", "Bash(dd *)", "Bash(mkfs*)", "Bash(nvme *)", "Bash(nwipe *)"):
        assert needle in deny


def test_recovery_build_cannot_import_erase():
    with pytest.raises(ImportError):
        __import__("resq_erase")


# ---------------------------------------------------------------- 受付・状態遷移
def test_consent_requires_authorization_for_non_owner(ws):
    w, db = ws
    c = create_case(w, db, customer="法人A")
    with pytest.raises(ResqError):
        intake.add_consent(c, form_version="2026.11", id_method="運転免許証",
                           ownership="法人所有（権限者の同意書面あり）")
    intake.add_consent(c, form_version="2026.11", id_method="運転免許証",
                       ownership="法人所有（権限者の同意書面あり）", authorization_doc="承認書 No.12")


def test_refused_requests(case):
    with pytest.raises(ResqError, match="ロック解除"):
        intake.add_device(case, kind="iPhone", request="パスコード解除してほしい")


def test_invalid_state_transition(case):
    with pytest.raises(ResqError):
        case.set_status("納品済")
    case.set_status("診断済")
    assert case.row["status"] == "診断済"
