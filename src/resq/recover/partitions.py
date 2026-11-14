"""S1 パーティション探索。

- mmls で現在のパーティション表を読む
- TestDisk の analyze/search（/cmd モード、書き込みコマンドは使わない）で消えたパーティションを探す
- 自前でブートセクタのシグネチャを走査（TestDisk の補完）
最後に fsstat で開けるものだけをボリュームとして採用する。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import audit
from ..errors import SafetyError

MMLS_LINE = re.compile(r"^\s*\d+:\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.*)$")


def parse_mmls(text: str) -> list[dict]:
    parts = []
    for line in text.splitlines():
        m = MMLS_LINE.match(line)
        if not m:
            continue
        slot, start, end, length, desc = m.groups()
        if slot.startswith("Meta") or slot.startswith("---"):
            continue
        parts.append({"start": int(start), "end": int(end), "length": int(length), "desc": desc.strip()})
    return parts


TD_GEOM = re.compile(r"CHS (\d+) (\d+) (\d+)")
TD_PART = re.compile(
    r"^\s+(?:\d+\s+[*PLEDp]\s+)?([A-Za-z][\w ,+.-]*?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)"
    r"(?:\s+\[(.*)\])?\s*$")


def parse_testdisk_log(text: str) -> list[dict]:
    """testdisk.log から探索で見つかったパーティションを LBA で返す。"""
    g = TD_GEOM.search(text)
    if not g:
        return []
    heads, spt = int(g.group(2)), int(g.group(3))
    found: dict[int, dict] = {}
    in_search = False
    for line in text.splitlines():
        if line.startswith("search_part()") or line.startswith("interface_write()"):
            in_search = True
            continue
        if not in_search:
            continue
        m = TD_PART.match(line)
        if not m:
            continue
        fs, c1, h1, s1, _c2, _h2, _s2, size, label = m.groups()
        lba = (int(c1) * heads + int(h1)) * spt + (int(s1) - 1)
        found.setdefault(lba, {"start": lba, "length": int(size), "fs": fs.strip(), "label": label})
    return sorted(found.values(), key=lambda p: p["start"])


def _boot_type(sector: bytes) -> str | None:
    if len(sector) < 512 or sector[510:512] != b"\x55\xaa":
        return None
    if sector[3:11] == b"NTFS    ":
        return "ntfs"
    if sector[3:11] == b"EXFAT   ":
        return "exfat"
    if sector[82:90] == b"FAT32   ":
        return "fat32"
    if sector[54:59] in (b"FAT12", b"FAT16"):
        return "fat16"
    return None


def scan_boot_sectors(image: Path, *, dense_mib: int = 16, align_sectors: int = 2048) -> list[dict]:
    """ブートセクタ候補を走査する。先頭 dense_mib MiB は全セクタ、以降は 1MiB 境界。"""
    size = image.stat().st_size
    nsec = size // 512
    dense = min(nsec, dense_mib * 2048)
    positions = list(range(0, dense)) + list(range(dense - dense % align_sectors, nsec, align_sectors))
    hits: dict[int, str] = {}
    with open(image, "rb") as fh:
        for lba in sorted(set(positions)):
            fh.seek(lba * 512)
            t = _boot_type(fh.read(512))
            if t:
                hits[lba] = t
    # FAT32 のバックアップブートセクタ（+6）を除く
    for lba in [k for k, v in hits.items() if v == "fat32"]:
        if hits.get(lba + 6) == "fat32":
            del hits[lba + 6]
    return [{"start": k, "fs": v} for k, v in sorted(hits.items())]


def run_testdisk(image: Path, stage_dir: Path, ctx) -> list[dict]:
    cmds = "analyze,search,quit"
    if "write" in cmds:  # 念のため：パーティション表への書き込みは絶対にしない
        raise SafetyError("TestDisk の write コマンドは使用禁止")
    log = stage_dir / "testdisk.log"
    if log.exists():
        log.unlink()
    # TestDisk はログ行を固定幅で切り詰めるため、長いパスだとジオメトリ（CHS）が欠ける。
    # ステージ内に短い名前のシンボリックリンクを作り、相対パスで渡す。
    link = stage_dir / "disk.img"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(Path(image).resolve())
    try:
        audit.run(["testdisk", "/log", "/cmd", link.name, cmds], op="recover.S1.testdisk", ctx=ctx,
                  cwd=stage_dir, check=False, timeout=3600)
    finally:
        link.unlink()
    return parse_testdisk_log(log.read_text(errors="replace")) if log.exists() else []


def find_volumes(image: Path, stage_dir: Path, ctx, *, use_testdisk: bool = True) -> list[dict]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    candidates: dict[int, set[str]] = {}

    def add(lba: int, src: str) -> None:
        candidates.setdefault(lba, set()).add(src)

    out = audit.run(["mmls", image], op="recover.S1.mmls", ctx=ctx, check=False)
    for p in parse_mmls(out.stdout) if out.returncode == 0 else []:
        add(p["start"], "mmls")
    add(0, "whole")
    if use_testdisk:
        for p in run_testdisk(image, stage_dir, ctx):
            add(p["start"], "testdisk")
    for p in scan_boot_sectors(image):
        add(p["start"], "bootscan")

    volumes = []
    for lba, srcs in sorted(candidates.items()):
        r = audit.run(["fsstat", "-t", "-o", str(lba), image], op="recover.S1.fsstat", ctx=ctx, check=False)
        if r.returncode == 0 and r.stdout.strip():
            volumes.append({"offset": lba, "fstype": r.stdout.strip(), "found_by": sorted(srcs)})
    (stage_dir / "partitions.json").write_text(json.dumps(volumes, ensure_ascii=False, indent=1))
    return volumes
