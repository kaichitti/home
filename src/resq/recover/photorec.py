"""S5 カービング（PhotoRec）。

管理情報が消えても、中身のシグネチャから回収する（名前なし）。
イメージ全体（partition_none）を対象にし、各ファイルのイメージ内位置を
report.xml（DFXML）から取り出して記録する（P10 の名前付け直しで使う）。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .. import audit
from .manifest import Candidate, Manifest

PHOTOREC_CMD = "partition_none,options,keep_corrupted_file_no,fileopt,everything,enable,search"


def parse_report(xml_path: Path) -> dict[str, int]:
    """report.xml → {ファイル名: 先頭の img_offset}"""
    out: dict[str, int] = {}
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return out
    for fo in root.iter():
        if not fo.tag.endswith("fileobject"):
            continue
        name = None
        offset = None
        for ch in fo:
            if ch.tag.endswith("filename"):
                name = Path(ch.text or "").name
            elif ch.tag.endswith("byte_runs"):
                for br in ch:
                    if "img_offset" in br.attrib:
                        offset = int(br.attrib["img_offset"])
                        break
        if name and offset is not None:
            out[name] = offset
    return out


def run(case, image_id: int, image: Path, stage_dir: Path) -> Manifest:
    stage_dir.mkdir(parents=True, exist_ok=True)
    recup = stage_dir / "recup"
    audit.run(["photorec", "/log", "/d", recup, "/cmd", image, PHOTOREC_CMD], op="recover.S5.photorec",
              ctx=case.ctx, cwd=stage_dir, check=False)
    man = Manifest(stage="S5", image_id=image_id, method="PhotoRec")
    for d in sorted(stage_dir.glob("recup.*")):
        if not d.is_dir():
            continue
        offsets = parse_report(d / "report.xml")
        for f in sorted(d.iterdir()):
            if not f.is_file() or f.name == "report.xml":
                continue
            man.candidates.append(Candidate(stored=str(f.relative_to(case.dir)), method="PhotoRec",
                                            img_offset=offsets.get(f.name)))
    man.write(stage_dir)
    return man
