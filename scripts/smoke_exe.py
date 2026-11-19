#!/usr/bin/env python3
"""ビルドした実行ファイルの動作確認（Linux / Windows 共通）。

  python scripts/smoke_exe.py <実行ファイルのフォルダ> <フィクスチャのフォルダ>

フィクスチャ（NTFS 再フォーマットのイメージ）を案件に登録して復旧し、顧客向け一覧に
元のファイル名が載ることまでを確認する。実デバイスには一切触れない。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    # Windows の CI 端末は cp1252 のため、日本語を出力できるよう UTF-8 にする
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    bin_dir, fixtures = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    suffix = ".exe" if os.name == "nt" else ""
    work = Path(tempfile.mkdtemp(prefix="resq-smoke-"))
    env = dict(os.environ, RESQ_HOME=str(work / "data"), RESQ_ERASE_HOME=str(work / "station"))

    def run(name: str, *args: str, expect: int = 0) -> str:
        exe = bin_dir / f"{name}{suffix}"
        p = subprocess.run([str(exe), *args], env=env, capture_output=True, timeout=900)
        out = p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
        print(f"$ {name} {' '.join(args)}  -> rc={p.returncode}")
        print("  " + out.strip().replace("\n", "\n  ")[:1500])
        if p.returncode != expect:
            raise SystemExit(f"FAILED: {name} {args} rc={p.returncode}")
        return out

    print(run("resq", "--version"))
    out = run("resq", "case", "new", "--customer", "動作確認", "--price-cap", "9800")
    cid = re.search(r"R\d{4}-\d{4}", out).group(0)
    run("resq", "consent", "add", cid, "--form-version", "2026.11", "--id-method", "運転免許証")
    img = work / "ntfs_qf.img"
    shutil.copyfile(fixtures / "ntfs_qf.img", img)
    os.chmod(img, stat.S_IREAD)  # 読み取り専用（Windows では読み取り専用属性）
    run("resq", "image-register", cid, str(img))
    run("resq", "recover", cid, "--no-testdisk")
    out = run("resq", "catalog", cid, "--no-pdf")
    html = next((work / "data" / "cases" / cid / "catalog").glob("list.html")).read_text(encoding="utf-8")
    expected = json.loads((fixtures / "expected.json").read_text(encoding="utf-8"))
    for f in expected["images"]["ntfs_qf"]["files"]:
        if f["name"] not in html:
            raise SystemExit(f"FAILED: {f['name']} が一覧にありません")
    print("一覧に全ファイルが載りました:", [f["name"] for f in expected["images"]["ntfs_qf"]["files"]])
    # PDF：Linux 版は WeasyPrint、Windows 版は Qt で作る（どちらもブラウザは使わない）
    run("resq", "catalog", cid)
    pdf = work / "data" / "cases" / cid / "catalog" / "list.pdf"
    if not pdf.exists() or not pdf.read_bytes().startswith(b"%PDF"):
        raise SystemExit("FAILED: PDF が作られていません")
    print("PDF も作成できました:", pdf.stat().st_size, "bytes")
    run("resq", "events", cid)
    # デスクトップアプリ：画面を実際に組み立てて 受付→登録→復旧→一覧 を通す（画面のない環境でも動く）
    gui_out = work / "gui"
    run("resq-gui", "--selftest", str(fixtures), str(gui_out))
    res = json.loads((gui_out / "selftest.json").read_text(encoding="utf-8"))
    if not res.get("ok"):
        raise SystemExit(f"FAILED: resq-gui の自己診断: {res}")
    print("resq-gui 自己診断 OK:", res["names"], "PDF" if res["pdf"] else "HTML")
    shots = Path(os.environ.get("RESQ_SMOKE_SHOTS", ""))
    if shots.name:
        shots.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(gui_out / "resq-gui.png", shots / f"resq-gui-{os.name}.png")

    erase = bin_dir / f"resq-erase{suffix}"
    if erase.exists():
        run("resq-erase", "--version")
        mock = work / "mock"
        mock.mkdir()
        (mock / "lsblk.json").write_text(json.dumps({"blockdevices": [
            {"name": "sdb", "serial": "SMOKE-HDD-0001", "model": "TEST HDD", "size": 1000204886016, "tran": "sata",
             "rota": True, "rm": False, "type": "disk"}]}), encoding="utf-8")
        (mock / "hdparm_N.txt").write_text(" max sectors   = 1953525168/1953525168, HPA is disabled\n", encoding="utf-8")
        run("resq-erase", "register", "--serial", "SMOKE-HDD-0001", "--kind", "HDD", "--requester", "動作確認",
            "--origin", "法人", "--consent-doc", "No.1")
        out = run("resq-erase", "erase", "SMOKE-HDD-0001", "--mock-dir", str(mock))
        if "ドライラン" not in out:
            raise SystemExit("FAILED: ドライランになっていません")
        egui = work / "erase-gui"
        run("resq-erase-gui", "--selftest", str(egui))
        res = json.loads((egui / "selftest.json").read_text(encoding="utf-8"))
        if not res.get("ok"):
            raise SystemExit(f"FAILED: resq-erase-gui の自己診断: {res}")
        print("resq-erase-gui 自己診断 OK（ドライラン・実行ボタン無効・証明書）")
    shutil.rmtree(work, ignore_errors=True)
    print("SMOKE TEST OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
