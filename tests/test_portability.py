"""Windows 版（resq.exe）を想定した移植性のテスト。

Windows には ddrescue / TSK / PhotoRec が標準で無いため、ツールが無い段は省略して記録し、
自作の段（S3 残骸スキャン・S7 サムネイル・S8 統合）と一覧作成は動くことを確認する。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from resq import audit, catalog, image as I, safety, tools
from resq.errors import SafetyError
from resq.recover import pipeline

MISSING = {"mmls", "fsstat", "fls", "icat", "testdisk", "testdisk_win", "photorec", "photorec_win",
           "vshadowinfo", "vshadowmount", "fusermount", "ddrescue"}


@pytest.fixture
def no_oss_tools(monkeypatch):
    real = shutil.which
    monkeypatch.setattr(tools.shutil, "which", lambda name, *a, **k: None if name in MISSING else real(name, *a, **k))


def test_pipeline_without_oss_tools_still_salvages(case, fixtures, expected, ro, no_oss_tools):
    iid = I.register_existing(case, ro(fixtures / "ntfs_qf.img"))
    rep = pipeline.run(case, image_id=iid)
    assert [v["fstype"] for v in rep["volumes"]] == ["ntfs"]       # ブートセクタ走査だけで特定
    skipped = {r["stage"]: r["note"] for r in case.db.all("SELECT * FROM stage_runs WHERE method='（省略）'")}
    assert set(skipped) == {"S2", "S4", "S5"} and "fls" in skipped["S2"] and "photorec" in skipped["S5"]
    shown = {r["sha256"]: r for r in case.db.all("SELECT * FROM recovered_files WHERE rank='A'")}
    for f in expected["images"]["ntfs_qf"]["files"]:
        assert shown[f["sha256"]]["orig_path"] == f["path"]
    res = catalog.build(case, pdf=False)
    assert "Holiday Photo.jpg" in Path(res["html"]).read_text(encoding="utf-8")


def test_missing_ddrescue_gives_clear_message(case, fixtures, ro, no_oss_tools, monkeypatch):
    from resq import diagnose as D

    src = ro(fixtures / "deleted.img")
    D.save(D.diagnose(str(src), smart_json=Path(__file__).parent / "data" / "smart_healthy.json"), case)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(Exception, match="見つかりません"):
        I.acquire(case, str(src))


@pytest.mark.parametrize("arg0", ["dd", "DD.EXE", r"C:\tools\dd.exe", "mkfs.ntfs.exe", "/usr/sbin/wipefs"])
def test_forbidden_programs_with_windows_names(arg0):
    with pytest.raises(SafetyError):
        audit.check_program([arg0, "x"])


@pytest.mark.parametrize("path", [r"\\.\PhysicalDrive0", r"\\?\GLOBALROOT\Device\Harddisk0\Partition1",
                                  "//./PhysicalDrive1", "/dev/sdb"])
def test_windows_device_paths(path, case):
    assert safety.is_device(path)
    with pytest.raises(SafetyError):
        safety.assert_writable_target(path, case_dir=case.dir)
    with pytest.raises(SafetyError):
        audit.check_device_args(["fls", path], allow_device=False)


def test_tool_aliases(monkeypatch):
    monkeypatch.setattr(tools.shutil, "which", lambda n, *a, **k: "C:/x/photorec_win.exe" if n == "photorec_win" else None)
    assert tools.resolve("photorec") == "photorec_win"
    assert tools.available("photorec") and not tools.available("fls")
    assert tools.missing_for_stage("S5") == [] and tools.missing_for_stage("S2") == ["fls", "icat"]


@pytest.mark.parametrize("seg,win,want", [
    ("a:b", True, "a_b"), ("x?y*.jpg ", True, "x_y_.jpg"), ("CON.txt", True, "_CON.txt"), ("nul", True, "_nul"),
    ("trail.", True, "trail"), ("a:b", False, "a:b"), ("..", True, ""), ("ok\x01name", False, "okname"),
])
def test_clean_segment(seg, win, want):
    assert safety.clean_segment(seg, windows=win) == want


def test_all_text_io_specifies_encoding():
    """ファイルの読み書き・外部コマンドの出力の文字コードを必ず明示する。

    Windows の既定の文字コードは cp1252 / cp932 のため、省略すると日本語を含む JSON・帳票で失敗する
    （resq.exe の CI で実際に見つかった不具合の再発防止）。
    """
    import ast

    root = Path(__file__).resolve().parent.parent
    files = [*(root / "src").rglob("*.py"), root / "scripts" / "smoke_exe.py", root / "scripts" / "fixturegen.py"]
    bad = []
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kws = {k.arg for k in node.keywords}
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if name in ("read_text", "write_text") and "encoding" not in kws:
                bad.append(f"{f.name}:{node.lineno} {name}")
            if name == "open" and "encoding" not in kws:
                mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
                if isinstance(mode, ast.Constant) and "b" not in str(mode.value):
                    bad.append(f"{f.name}:{node.lineno} open({mode.value!r})")
            if name in ("run", "Popen") and any(k.arg == "text" for k in node.keywords) and "encoding" not in kws:
                bad.append(f"{f.name}:{node.lineno} subprocess.{name}(text=True)")
    assert bad == []
