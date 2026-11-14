"""P3: 多段復旧（S1 / S2 / S5 / S8）と P3b 商用エンジン取り込み。

完了条件:
  - 削除のみ・パーティション表削除のフィクスチャで、上書きしていないファイルが全件 sha256 一致で戻る
  - 上書きしたファイルは「戻った」と表示されない
  - 段ごとの件数レポートが出る
  - OSS と商用で同じファイルが出たら 1 件に束ね、パス情報が多い方を採用する
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from resq import diagnose as D
from resq import image as I
from resq.recover import ingest as ING
from resq.recover import merge as M
from resq.recover import partitions, pipeline

DATA = Path(__file__).parent / "data"
SHOWN = ("A", "B", "C", "D", "U")


def _prepare(case, fixtures, ro, name):
    src = ro(fixtures / f"{name}.img")
    D.save(D.diagnose(str(src), smart_json=DATA / "smart_healthy.json", ctx=case.ctx), case)
    return I.acquire(case, str(src))


def _rows(case):
    return case.db.all("SELECT * FROM recovered_files WHERE case_id=?", case.id)


def _shown(case):
    return {r["sha256"]: r for r in _rows(case) if r["rank"] in SHOWN}


def _image_sha(case, iid):
    p = Path(case.db.one("SELECT path FROM images WHERE id=?", iid)["path"])
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_deleted_all_files_recovered_with_names(case, fixtures, expected, ro):
    iid = _prepare(case, fixtures, ro, "deleted")
    before = _image_sha(case, iid)
    rep = pipeline.run(case)
    shown = _shown(case)
    for f in expected["images"]["deleted"]["files"]:
        assert f["sha256"] in shown, f"not recovered: {f['path']}"
        row = shown[f["sha256"]]
        assert row["rank"] == "A", f"{f['path']} should have its name: {dict(row)}"
        # FAT の削除エントリは先頭 1 文字が失われる（_MG_0002.JPG）。フォルダは保たれる
        assert row["orig_path"].split("/")[:-1] == f["path"].split("/")[:-1]
        assert row["name"][1:] == f["name"][1:]
    # 段別レポート
    assert rep["stages"]["S2"]["found"] == 6 and rep["stages"]["S5"]["found"] >= 6
    assert (case.dir / "stages" / "stage_report.json").exists()
    stages = {r["stage"] for r in case.db.all("SELECT stage FROM stage_runs WHERE case_id=?", case.id)}
    assert {"S1", "S2", "S5"} <= stages
    # イメージは読むだけ
    assert _image_sha(case, iid) == before
    assert case.row["status"] == "復旧済"


def test_overwritten_file_is_not_shown_as_recovered(case, fixtures, expected, ro):
    _prepare(case, fixtures, ro, "overwrite")
    pipeline.run(case, use_testdisk=False)
    shown = _shown(case)
    for f in expected["images"]["overwrite"]["files"]:
        if f["state"] == "overwritten":
            assert f["sha256"] not in shown
        else:
            assert f["sha256"] in shown, f["path"]
    # 上書きされた IMG_0003 の削除エントリは中身ゼロ → ランク外（X）
    rows = [r for r in _rows(case) if r["name"].endswith("MG_0003.JPG")]
    assert rows and all(r["rank"] == "X" and r["verify"] == "ZERO" for r in rows)


def test_partition_table_deleted(case, fixtures, expected, ro):
    _prepare(case, fixtures, ro, "parttable")
    rep = pipeline.run(case)
    vols = {v["offset"]: v for v in rep["volumes"]}
    assert 2048 in vols and vols[2048]["fstype"] == "fat32"
    assert "testdisk" in vols[2048]["found_by"] and "bootscan" in vols[2048]["found_by"]
    assert "mmls" not in vols[2048]["found_by"]  # 表は消えている
    shown = _shown(case)
    for f in expected["images"]["parttable"]["files"]:
        row = shown.get(f["sha256"])
        assert row is not None, f["path"]
        assert row["rank"] == "A" and row["orig_path"] == f["path"]


def test_quick_format_recovers_everything(case, fixtures, expected, ro):
    _prepare(case, fixtures, ro, "quickformat")
    pipeline.run(case, use_testdisk=False)
    shown = _shown(case)
    for f in expected["images"]["quickformat"]["files"]:
        assert f["sha256"] in shown, f["path"]
    # S2 の孤立エントリから名前が付くもの（A）と、カービングのみ（B）が混在しうる
    assert {r["rank"] for r in shown.values()} <= {"A", "B"}


def test_testdisk_log_parser():
    log = """Disk parttable.img - 44 MB / 42 MiB - CHS 6 255 63, sector size=512
search_part()
Disk parttable.img - 44 MB / 42 MiB - CHS 6 255 63
FAT: cluster=2(0x2), pos=3340
     FAT32                    0  32 33     5  57 52      81920 [RESQFIX]
interface_write()
 1 * FAT32                    0  32 33     5  57 52      81920 [RESQFIX]
"""
    parts = partitions.parse_testdisk_log(log)
    assert parts == [{"start": 2048, "length": 81920, "fs": "FAT32", "label": "RESQFIX"}]


def test_boot_sector_scan_skips_fat32_backup(fixtures):
    hits = partitions.scan_boot_sectors(fixtures / "parttable.img")
    assert [h["start"] for h in hits] == [2048]


# ---------------------------------------------------------------- P3b 商用エンジン
def test_ingest_merges_with_oss_and_prefers_longer_path(case, fixtures, expected, ro, tmp_path):
    _prepare(case, fixtures, ro, "deleted")
    pipeline.run(case, stages=("S1", "S2"))
    # DMDE で書き出した想定のフォルダ（ルート名付きでパスが深い）＋ OSS では出なかった 1 件
    export = tmp_path / "dmde_export"
    files = {f["path"]: f for f in expected["images"]["deleted"]["files"]}
    s2_dir = next((case.dir / "stages").glob("img*/S2/vol0"))
    target = "DCIM/IMG_0001.JPG"
    (export / "Root" / "DCIM").mkdir(parents=True)
    shutil.copyfile(s2_dir / target, export / "Root" / target)
    extra = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\nxref\n0 1\n0000000000 65535 f \ntrailer\n<<>>\nstartxref\n33\n%%EOF\n"
    (export / "Root" / "ONLY_DMDE.PDF").write_bytes(extra)

    ING.ingest(case, export, engine="DMDE", image_id=1, license_note="DMDE Professional (test)")
    rep = M.merge(case)
    rows = [r for r in _rows(case) if r["sha256"] == files[target]["sha256"]]
    assert len(rows) == 1, "OSS と商用の同一ファイルは 1 件に束ねる"
    r = rows[0]
    assert r["orig_path"] == "Root/DCIM/IMG_0001.JPG" and r["method"] == "商用:DMDE"
    assert set(json.loads(r["all_methods"])) == {"TSK", "商用:DMDE"}
    com = [k for k in rep["stages"] if k.startswith("COM")]
    assert com and rep["stages"][com[0]]["unique"] == 1


def test_ingest_rejects_unknown_engine(case, tmp_path):
    from resq.errors import ResqError

    with pytest.raises(ResqError):
        ING.ingest(case, tmp_path, engine="FreeRecoveryTool")
