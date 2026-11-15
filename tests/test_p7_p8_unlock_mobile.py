"""P7 BitLocker 解錠・P8 スマホ吸い出し。

外部ツール（cryptsetup / idevicebackup2 / adb）は、引数と標準入力を記録する偽物を PATH に置いて検証する。
P7 完了条件: キー文字列が DB・ログ・例外メッセージに一切出ない。
P8 完了条件: 開発機ではコマンド生成のみ（＋偽ツールでの流れ）。実機テストは作業機で人間が行う。
"""
from __future__ import annotations

import hashlib
import io
import plistlib
import sqlite3
import textwrap
from pathlib import Path

import pytest
from PIL import Image

from resq import image as I
from resq import unlock
from resq.errors import ResqError
from resq.mobile import android, ios, next_stage_dir
from resq.recover import merge as M

GROUPS = [f"{11 * n:06d}" for n in (1234, 5678, 9012, 3456, 7890, 2345, 6789, 1111)]
KEY = "-".join(GROUPS)


def _fake_bin(tmp_path, monkeypatch, name: str, body: str) -> Path:
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body), encoding="utf-8")
    p.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}:{__import__('os').environ['PATH']}")
    return p


def _fake_cryptsetup(tmp_path, monkeypatch, fail=False):
    rec = tmp_path / "cryptsetup-record"
    _fake_bin(tmp_path, monkeypatch, "cryptsetup", f"""
        printf '%s\\n' "$@" > "{rec}.args"
        if [ "$1" = open ]; then cat > "{rec}.stdin"; fi
        {'cat "' + str(rec) + '.stdin" >&2; echo " : No key available with this passphrase." >&2; exit 2' if fail else 'exit 0'}
    """)
    return rec


def _all_text(root: Path) -> str:
    out = []
    for p in root.rglob("*"):
        if p.is_file():
            try:
                out.append(p.read_bytes().decode("utf-8", errors="ignore"))
            except OSError:
                pass
    return "\n".join(out)


def _key_variants():
    return [KEY, KEY.replace("-", ""), GROUPS[0] + GROUPS[1]]


@pytest.fixture
def registered(case, fixtures, ro):
    iid = I.register_existing(case, ro(fixtures / "deleted.img"))
    return case, iid


# ---------------------------------------------------------------- P7
def test_recovery_password_validation():
    assert unlock.normalize_recovery_password(KEY.replace("-", " ")) == KEY
    bad = KEY[:-1] + ("0" if KEY[-1] != "0" else "1")
    with pytest.raises(ResqError) as ei:
        unlock.normalize_recovery_password(bad)
    assert "8 組目" in str(ei.value) and GROUPS[0] not in str(ei.value)
    with pytest.raises(ResqError):
        unlock.normalize_recovery_password("1234")


def test_open_command_is_readonly_and_reads_key_from_stdin():
    cmd = unlock.open_command("bitlk", Path("/w/img01.dd"), "resq-x")
    assert cmd == ["cryptsetup", "open", "--type", "bitlk", "--readonly", "--key-file=-", "/w/img01.dd", "resq-x"]


def test_unlock_never_leaks_key(registered, tmp_path, monkeypatch):
    case, iid = registered
    rec = _fake_cryptsetup(tmp_path, monkeypatch)
    dev = unlock.unlock(case, iid, KEY.replace("-", " "))
    assert dev == f"/dev/mapper/resq-{case.id}-img{iid}-dec"
    args = (Path(f"{rec}.args")).read_text(encoding="utf-8")
    assert "--readonly" in args and "--key-file=-" in args
    assert all(k not in args for k in _key_variants()), "キーをコマンドラインに載せない"
    assert Path(f"{rec}.stdin").read_text(encoding="utf-8") == KEY, "キーは標準入力で渡す"
    everything = _all_text(case.ws.root)
    dump = "\n".join(case.db.conn.iterdump())
    for k in _key_variants():
        assert k not in everything and k not in dump


def test_unlock_failure_message_is_redacted(registered, tmp_path, monkeypatch):
    case, iid = registered
    _fake_cryptsetup(tmp_path, monkeypatch, fail=True)
    with pytest.raises(ResqError) as ei:
        unlock.unlock(case, iid, KEY)
    msg = str(ei.value)
    assert "解錠できませんでした" in msg
    for k in _key_variants():
        assert k not in msg
        assert k not in _all_text(case.ws.root)
        assert k not in "\n".join(case.db.conn.iterdump())


def test_extract_partition_for_encrypted_volume(case, fixtures, ro):
    iid = I.register_existing(case, ro(fixtures / "parttable_intact.img"))
    pid = unlock.extract_partition(case, iid, 2048, 81920)
    row = case.db.one("SELECT * FROM images WHERE id=?", pid)
    raw = (fixtures / "parttable_intact.img").read_bytes()[2048 * 512:(2048 + 81920) * 512]
    assert row["sha256"] == hashlib.sha256(raw).hexdigest()
    assert not Path(row["path"]).stat().st_mode & 0o222


# ---------------------------------------------------------------- P8 iPhone
def _jpeg(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "JPEG")
    return buf.getvalue()


def make_ios_backup(root: Path, files: dict[tuple[str, str], bytes], encrypted=False) -> Path:
    udid = "00008030-001A2B3C4D5E6F70"
    b = root / udid
    b.mkdir(parents=True)
    with open(b / "Manifest.plist", "wb") as fh:
        plistlib.dump({"IsEncrypted": encrypted}, fh)
    con = sqlite3.connect(b / "Manifest.db")
    con.execute("CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)")
    for (domain, rel), data in files.items():
        fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
        con.execute("INSERT INTO Files VALUES (?,?,?,?,?)", (fid, domain, rel, 1, b""))
        (b / fid[:2]).mkdir(exist_ok=True)
        (b / fid[:2] / fid).write_bytes(data)
    con.execute("INSERT INTO Files VALUES ('dir1','CameraRollDomain','Media/DCIM',2,x'')")
    con.commit()
    con.close()
    return root


def test_ios_camera_roll_extraction(case, tmp_path):
    photos = {("CameraRollDomain", "Media/DCIM/100APPLE/IMG_0001.JPG"): _jpeg("red"),
              ("CameraRollDomain", "Media/DCIM/100APPLE/IMG_0002.JPG"): _jpeg("blue")}
    other = {("HomeDomain", "Library/SMS/sms.db"): b"SQLite format 3\0"}
    bk = make_ios_backup(tmp_path / "bk", {**photos, **other})
    stage = next_stage_dir(case)
    man = ios.extract_camera_roll(case, bk, stage)
    assert sorted(c.orig_path for c in man.candidates) == ["DCIM/100APPLE/IMG_0001.JPG", "DCIM/100APPLE/IMG_0002.JPG"]
    rep = M.merge(case)
    assert rep["ranks"]["A"] == 2 and "MOB1" in rep["stages"]


def test_ios_encrypted_backup_is_not_parsed(case, tmp_path):
    bk = make_ios_backup(tmp_path / "bk", {("CameraRollDomain", "Media/DCIM/1.JPG"): _jpeg("red")}, encrypted=True)
    with pytest.raises(ResqError, match="暗号化バックアップ"):
        ios.extract_camera_roll(case, bk, next_stage_dir(case))


def test_ios_backup_requires_owner_confirmation(case, tmp_path, monkeypatch):
    with pytest.raises(ResqError, match="持ち主"):
        ios.backup(case, "UDID", {ios.STEPS[0]: True})
    for tool in ("idevice_id", "ideviceinfo", "idevicebackup2"):
        _fake_bin(tmp_path, monkeypatch, tool, "exit 0\n")
    out = ios.backup(case, "UDID-1", {s: True for s in ios.STEPS})
    cmds = [r["command"] for r in case.db.all("SELECT command FROM events WHERE op='mobile.ios'")]
    assert cmds[-1] == f"idevicebackup2 -u UDID-1 backup --full {out}"


# ---------------------------------------------------------------- P8 Android
def test_android_commands():
    cmds = android.commands("R58M123", Path("/w/out"), ("/sdcard/DCIM",))
    assert cmds == [["adb", "devices", "-l"], ["adb", "-s", "R58M123", "pull", "-a", "/sdcard/DCIM", "/w/out/DCIM"]]


def test_android_pull_with_fake_adb(case, tmp_path, monkeypatch):
    jpg = tmp_path / "sample.jpg"
    jpg.write_bytes(_jpeg("green"))
    _fake_bin(tmp_path, monkeypatch, "adb", f"""
        if [ "$3" = pull ]; then
          case "$5" in */DCIM) mkdir -p "$6/Camera" && cp "{jpg}" "$6/Camera/IMG_20261101.jpg";; *) exit 1;; esac
        fi
        exit 0
    """)
    with pytest.raises(ResqError):
        android.pull(case, "R58M123", {})
    man = android.pull(case, "R58M123", {s: True for s in android.STEPS})
    assert [c.orig_path for c in man.candidates] == ["sdcard/DCIM/Camera/IMG_20261101.jpg"]
    rep = M.merge(case)
    assert rep["ranks"]["A"] == 1
