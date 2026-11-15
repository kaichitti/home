"""P9 残骸スキャン（S3）・P10 名前の付け直し（S6）・P11 シャドウコピー（S4）とサムネイル（S7）。

完了条件:
  P9  クイックフォーマット後のフィクスチャで、フォルダ構造付きで戻る件数が S2 単独より増える。
      商用エンジンの結果と件数を比較し、差分を記録する。
  P10 カービングでしか戻らなかったファイルの一部に、元の名前が付く。
  P11 シャドウコピー内の旧版とサムネイルが回収される（シャドウコピー実物は作業機で検証）。
"""
from __future__ import annotations

import io
import json
import shutil
import struct
from pathlib import Path

import pytest
from PIL import Image

from resq import catalog
from resq import diagnose as D
from resq import image as I
from resq.recover import compare, pipeline, thumbs, vss
from resq.recover import ingest as ING
from resq.recover import merge as M
from resq.recover.manifest import Manifest, has_folder_info
from resq.recover.remnants import common, ntfs

DATA = Path(__file__).parent / "data"
SHOWN = ("A", "B", "C", "D", "U")


def _prepare(case, fixtures, ro, name):
    src = ro(fixtures / f"{name}.img")
    D.save(D.diagnose(str(src), smart_json=DATA / "smart_healthy.json", ctx=case.ctx), case)
    return I.acquire(case, str(src))


def _shown(case):
    return {r["sha256"]: r for r in case.db.all("SELECT * FROM recovered_files WHERE case_id=?", case.id)
            if r["rank"] in SHOWN}


def _stage(case, stage) -> Manifest:
    return Manifest.read(next((case.dir / "stages").glob(f"img*/{stage}/manifest.json")))


def _folder_count(case, stage, expected_files) -> int:
    """その段で『中身が正しく、フォルダ名付き（またはルート直下と確定）』で戻った件数。"""
    from resq.hashing import sha256_file

    want = {f["sha256"] for f in expected_files}
    n = 0
    for c in _stage(case, stage).candidates:
        if sha256_file(case.dir / c.stored) in want and (c.path_known or has_folder_info(c.orig_path)):
            n += 1
    return n


# ---------------------------------------------------------------- P9
def test_qf_nested_fat_rebuilds_tree_and_long_names(case, fixtures, expected, ro):
    _prepare(case, fixtures, ro, "qf_nested")
    pipeline.run(case, stages=("S1", "S2", "S3", "S5"), use_testdisk=False)
    files = expected["images"]["qf_nested"]["files"]
    # FAT32 のクイックフォーマットはルートを作り直すため、最上位フォルダ名（DCIM 等）はどの手法でも戻らない。
    # 件数では S2（TSK の孤立エントリ）と同等以上。S3 の上積みは長い名前とフォルダのまとまり（下で確認）。
    # 「件数が S2 単独より増える」ことは NTFS の再フォーマット（次のテスト）で確認する。
    s2, s3 = _folder_count(case, "S2", files), _folder_count(case, "S3", files)
    assert s3 >= s2 and s3 == 4, (s2, s3)
    shown = _shown(case)
    for f in files:
        assert f["sha256"] in shown, f["path"]
    memo = shown[next(f["sha256"] for f in files if f["name"] == "memo notes.docx")]
    assert memo["name"] == "memo notes.docx"        # TSK だけでは MEMONO~1.DOC になる
    trip = shown[next(f["sha256"] for f in files if f["name"] == "Family Trip 01.jpg")]
    assert trip["orig_path"].endswith("100RESQ/Family Trip 01.jpg")
    # 同じ親（元 DCIM）の下に 100RESQ と 101RESQ がまとまる
    i101 = shown[next(f["sha256"] for f in files if f["name"] == "IMG_0101.JPG")]
    assert trip["orig_path"].split("/")[0] == i101["orig_path"].split("/")[0]


def test_ntfs_reformat_recovered_only_by_remnants(case, fixtures, expected, ro):
    _prepare(case, fixtures, ro, "ntfs_qf")
    pipeline.run(case, stages=("S1", "S2", "S3", "S4"), use_testdisk=False)
    files = expected["images"]["ntfs_qf"]["files"]
    assert _folder_count(case, "S2", files) == 0
    assert _folder_count(case, "S3", files) == len(files)
    shown = _shown(case)
    for f in files:
        row = shown[f["sha256"]]
        assert row["rank"] == "A" and row["orig_path"] == f["path"]
    # S4: VSS なしのボリューム → ストア 0 件として正常終了
    assert _stage(case, "S4").info.get("vol0_stores") == 0


def test_exfat_deleted_folder(case, fixtures, expected, ro):
    _prepare(case, fixtures, ro, "exfat_deleted")
    pipeline.run(case, stages=("S1", "S2", "S3"), use_testdisk=False)
    shown = _shown(case)
    for f in expected["images"]["exfat_deleted"]["files"]:
        row = shown[f["sha256"]]
        assert row["orig_path"] == f["path"] and row["rank"] == "A"
        assert row["deleted"] == 1


def test_compare_with_commercial_engine(case, fixtures, expected, ro, tmp_path):
    _prepare(case, fixtures, ro, "qf_nested")
    pipeline.run(case, stages=("S1", "S3"), use_testdisk=False)
    # DMDE の書き出しを模したフォルダ：2 件は S3 と同じ、1 件は DMDE だけが戻したもの
    s3 = _stage(case, "S3")
    export = tmp_path / "dmde"
    for c in s3.candidates[:2]:
        dest = export / "Root" / c.orig_path.split("/", 1)[-1]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(case.dir / c.stored, dest)
    (export / "Root" / "only_dmde.pdf").write_bytes(
        b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\nxref\n0 1\n0000000000 65535 f \ntrailer\n<<>>\nstartxref\n33\n%%EOF\n")
    ING.ingest(case, export, engine="DMDE", image_id=1)
    rep = compare.compare(case, "S3", "COM1")
    assert rep["count"]["both"] == 2
    assert rep["count"]["only_COM1"] == 1 and rep["count"]["only_S3"] == len(s3.candidates) - 2
    assert Path(rep["path"]).exists()


def test_ntfs_runlist_decoding():
    # 16 クラスタ @LCN 256、8 クラスタ @+16（=272）、疎 4 クラスタ、-0x10（=256 へ戻る）2 クラスタ
    data = bytes([0x21, 0x10, 0x00, 0x01, 0x11, 0x08, 0x10, 0x01, 0x04, 0x11, 0x02, 0xF0, 0x00])
    assert ntfs.decode_runlist(data, 0) == [(256, 16), (272, 8), (None, 4), (256, 2)]


def test_read_runs_concatenates_fragments(tmp_path):
    img = tmp_path / "frag.img"
    img.write_bytes(b"A" * 100 + b"B" * 100 + b"C" * 100)
    e = common.Entry(fs="ntfs", name="x", is_dir=False, deleted=False, size=250, parent="root",
                     runs=[(200, 100), (None, 50), (0, 100)])
    assert common.read_runs(img, e) == b"C" * 100 + b"\0" * 50 + b"A" * 100


# ---------------------------------------------------------------- P10
def test_carved_files_get_names_back(case, fixtures, expected, ro):
    _prepare(case, fixtures, ro, "hiword")
    pipeline.run(case, stages=("S1", "S2", "S3", "S5"), use_testdisk=False)
    photos = expected["images"]["hiword"]["files"]
    shown = _shown(case)
    for f in photos:
        # 名前付きの削除エントリは上位ワードを失っており中身が別物 → ランク外。カービングでは名前なし（B）
        assert shown[f["sha256"]]["rank"] == "B"
    pipeline.run(case, stages=("S6",))
    s6 = _stage(case, "S6")
    assert s6.info["renamed"] == len(photos)
    assert {c.extra["match"] for c in s6.candidates} == {"fat32_hiword"}
    shown = _shown(case)
    for f in photos:
        row = shown[f["sha256"]]
        assert row["rank"] == "A" and row["method"] == "PhotoRec+名前復元"
        assert row["orig_path"].startswith("DCIM/") and row["name"][1:] == f["name"][1:]
    # 名前は付いたが中身が別物の削除エントリは、復旧扱いにしない
    bad = [r for r in case.db.all("SELECT * FROM recovered_files WHERE case_id=? AND rank='X'", case.id)
           if r["name"].endswith(".JPG")]
    assert bad and all(r["verify"] == "BROKEN" for r in bad)


# ---------------------------------------------------------------- P11
def _jpeg(color, size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def _png(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buf, "PNG")
    return buf.getvalue()


def make_thumbcache(images: list[bytes], ver: int = 0x20) -> bytes:
    """thumbcache_*.db（Win10 = 0x20 / Win7 = 0x15）を組み立てる。"""
    entries = b""
    for i, img in enumerate(images):
        ident = f"{i:016x}".encode("utf-16-le")
        if ver == 0x15:
            hdr = struct.pack("<4sIQIIII QQ", b"CMMM", 0, i, len(ident), 0, len(img), 0, 0, 0)
        else:
            hdr = struct.pack("<4sIQIIIIII QQ", b"CMMM", 0, i, len(ident), 0, len(img), 64, 48, 0, 0, 0)
        body = hdr + ident + img
        body = body[:4] + struct.pack("<I", len(body)) + body[8:]
        entries += body
    if ver == 0x15:
        head = struct.pack("<4sIIIII", b"CMMM", ver, 0, 24, 0, len(images))
    else:
        head = struct.pack("<4sIIIIII", b"CMMM", ver, 0, 0, 28, 0, len(images))
    return head + entries


@pytest.mark.parametrize("ver", [0x15, 0x20])
def test_parse_thumbcache_versions(ver):
    imgs = [_jpeg("red"), _png("blue"), _jpeg("green")]
    got = thumbs.parse_thumbcache(make_thumbcache(imgs, ver))
    assert [g["data"] for g in got] == imgs
    assert [g["ext"] for g in got] == ["jpg", "png", "jpg"]


def test_thumbnails_become_rank_d(case, tmp_path):
    # 他の段（ここでは商用エンジンの書き出し）に thumbcache が含まれていた想定
    export = tmp_path / "export" / "Users" / "taro" / "AppData" / "Local" / "Microsoft" / "Windows" / "Explorer"
    export.mkdir(parents=True)
    (export / "thumbcache_256.db").write_bytes(make_thumbcache([_jpeg("red"), _jpeg("navy"), _png("olive")]))
    ING.ingest(case, tmp_path / "export", engine="DMDE")
    srcs = thumbs.collect_sources(case)
    assert len(srcs) == 1
    stage_dir = case.sub("stages") / "img0" / "S7"
    man = thumbs.run(case, None, srcs, stage_dir)
    assert len(man.candidates) == 3
    rep = M.merge(case)
    assert rep["ranks"]["D"] == 3
    res = catalog.build(case, pdf=False)
    html = Path(res["html"]).read_text()
    assert "サムネイル・低解像度版のみ（3 件）" in html


def test_vss_info_parsing_and_commands(tmp_path):
    sample = """vshadowinfo 20190323

Volume Shadow Snapshot information:
\tNumber of stores:\t2

Store: 1
\tIdentifier\t\t: 0c5ffbb2-...
"""
    assert vss.parse_info(sample) == 2
    assert vss.parse_info("No Volume Shadow Snapshots found.") == 0
    mount, umount = vss.mount_commands(Path("/w/img01.dd"), 1048576, Path("/w/mnt"))
    assert mount == ["vshadowmount", "-o", "1048576", "/w/img01.dd", "/w/mnt"]
    assert umount[0] in ("fusermount", "fusermount3") and umount[1:] == ["-u", "/w/mnt"]
