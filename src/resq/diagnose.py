"""診断：認識・健康状態・暗号化を調べ、受付判定を返す（企画書 §1.1, P1）。

判定:
  自社      自社で対応できる
  条件付き  条件が揃えば対応可（例: BitLocker の回復キー）
  取次      提携ラボへ取次（異音・認識しない・SMART 危険など）。通電を続けない
  不可      受けない／技術的に原則戻らない
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import audit, safety
from .recover.partitions import parse_mmls

IN_HOUSE, CONDITIONAL, REFER, REJECT = "自社", "条件付き", "取次", "不可"
_ORDER = {IN_HOUSE: 0, CONDITIONAL: 1, REFER: 2, REJECT: 3}

# 症状キーワード → (判定, 理由)
SYMPTOM_RULES: dict[str, tuple[str, str]] = {
    "異音": (REFER, "異音あり。通電を止め、電源を入れずに提携ラボへ取次"),
    "不回転": (REFER, "モーター不回転。クリーンルーム作業が必要なため取次"),
    "認識しない": (REFER, "媒体が認識されない。専用機材が必要なため取次"),
    "SSD削除": (REJECT, "内蔵 SSD の削除データは TRIM 後は原則戻らない"),
    "スマホ削除": (REJECT, "スマホの削除データは暗号化により戻らない。『最近削除した項目』とクラウドを案内"),
    "スマホ初期化": (REJECT, "初期化後のスマホは暗号鍵ごと消えるため戻らない"),
    "水没": (REFER, "基板故障・水没で起動しない端末は取次"),
    "パスコード不明": (REJECT, "ロック解除・回避は請け負わない"),
}

# ATA SMART 属性
ATTR_REALLOC, ATTR_PENDING, ATTR_UNCORR, ATTR_REPORTED_UNCORR = 5, 197, 198, 187

ENCRYPTION_SIGNATURES = (
    # (名前, オフセット, シグネチャ, 判定, 理由)
    ("BitLocker", 3, b"-FVE-FS-", CONDITIONAL, "BitLocker 暗号化を検出。顧客の回復キーが必要（なければ不可）"),
    ("LUKS", 0, b"LUKS\xba\xbe", CONDITIONAL, "LUKS 暗号化を検出。パスフレーズ／鍵が必要"),
    ("APFS", 32, b"NXSB", CONDITIONAL, "APFS を検出。FileVault 有効なら回復キーが必要（要確認）"),
)


@dataclass
class Diagnosis:
    source: str
    verdict: str = IN_HOUSE
    level: str = "論理"           # 論理 / 軽度物理 / 重度物理
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_confirmation: bool = False  # イメージ化前に明示的な確認が必要
    smart: dict[str, Any] = field(default_factory=dict)
    partitions: list[dict] = field(default_factory=list)
    filesystems: list[dict] = field(default_factory=list)
    encryption: list[dict] = field(default_factory=list)
    size: int | None = None

    def raise_to(self, verdict: str, reason: str) -> None:
        if _ORDER[verdict] > _ORDER[self.verdict]:
            self.verdict = verdict
        self.reasons.append(f"[{verdict}] {reason}")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- SMART
def evaluate_smart(data: dict, diag: Diagnosis) -> None:
    """smartctl -j -a の JSON を評価する。"""
    summary: dict[str, Any] = {}
    passed = (data.get("smart_status") or {}).get("passed")
    summary["passed"] = passed
    attrs = {a.get("id"): a for a in (data.get("ata_smart_attributes") or {}).get("table", [])}

    def raw(i: int) -> int:
        a = attrs.get(i)
        return int(((a or {}).get("raw") or {}).get("value") or 0)

    realloc, pending, uncorr = raw(ATTR_REALLOC), raw(ATTR_PENDING), raw(ATTR_UNCORR)
    summary.update(reallocated=realloc, pending=pending, offline_uncorrectable=uncorr,
                   reported_uncorrectable=raw(ATTR_REPORTED_UNCORR))
    nvme = data.get("nvme_smart_health_information_log")
    if nvme:
        summary.update(nvme_critical_warning=nvme.get("critical_warning", 0),
                       nvme_media_errors=nvme.get("media_errors", 0),
                       nvme_percentage_used=nvme.get("percentage_used", 0))
    diag.smart = summary

    if passed is False:
        diag.level = "重度物理"
        diag.raise_to(REFER, "SMART 総合判定が FAILED。通電を続けると悪化するおそれがあるため取次")
        return
    if nvme and nvme.get("critical_warning", 0):
        diag.level = "重度物理"
        diag.raise_to(REFER, f"NVMe critical_warning={nvme['critical_warning']}。取次")
        return
    degraded = realloc > 0 or pending > 0 or uncorr > 0 or (nvme and nvme.get("media_errors", 0) > 0)
    if degraded:
        diag.level = "軽度物理"
        diag.requires_confirmation = True
        diag.warnings.append(
            f"不良セクタの兆候（代替処理済 {realloc} / 保留 {pending} / 回復不能 {uncorr}）。"
            "イメージ化を最優先し、作業中に保留セクタが増え続けたら即中断")
        diag.raise_to(IN_HOUSE, "軽度物理障害として自社でイメージ化（ddrescue）から実施")
    else:
        diag.raise_to(IN_HOUSE, "SMART 異常なし")


def load_smart(source: str, smart_json: Path | None, ctx: audit.AuditContext | None) -> dict | None:
    if smart_json is not None:
        return json.loads(Path(smart_json).read_text())
    if not safety.is_device(source):
        return None  # イメージファイルには SMART がない
    # smartctl の終了コードはビットマスク（ディスク状態の警告でも非 0）なので rc はここで判定しない
    out = audit.run(["smartctl", "-j", "-a", source], op="diagnose.smart", ctx=ctx,
                    allow_device=True, check=False)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------- 構造・暗号化
def read_at(source: str, offset: int, length: int) -> bytes:
    with open(source, "rb", buffering=0) as fh:  # 読み取り専用で開く
        fh.seek(offset)
        return fh.read(length)


def detect_encryption(source: str, offsets_bytes: list[int]) -> list[dict]:
    found = []
    for off in sorted(set(offsets_bytes)):
        try:
            head = read_at(source, off, 4096)
        except OSError:
            continue
        for name, sig_off, sig, verdict, reason in ENCRYPTION_SIGNATURES:
            if head[sig_off:sig_off + len(sig)] == sig:
                found.append({"type": name, "offset": off, "verdict": verdict, "reason": reason})
    return found


def probe_structure(source: str, diag: Diagnosis, ctx: audit.AuditContext | None) -> list[int]:
    allow = safety.is_device(source)
    out = audit.run(["mmls", source], op="diagnose.mmls", ctx=ctx, allow_device=allow, check=False)
    diag.partitions = parse_mmls(out.stdout) if out.returncode == 0 else []
    offsets = [0] + [p["start"] for p in diag.partitions]
    for off in sorted(set(offsets)):
        r = audit.run(["fsstat", "-t", "-o", str(off), source], op="diagnose.fsstat", ctx=ctx,
                      allow_device=allow, check=False)
        if r.returncode == 0 and r.stdout.strip():
            diag.filesystems.append({"offset_sectors": off, "type": r.stdout.strip()})
    if allow:
        audit.run(["lsblk", "-J", "-b", "-o", "NAME,SIZE,MODEL,SERIAL,TRAN,ROTA,RO", source],
                  op="diagnose.lsblk", ctx=ctx, allow_device=True, check=False)
        audit.run(["blkid", "-p", source], op="diagnose.blkid", ctx=ctx, allow_device=True, check=False)
    return [o * 512 for o in offsets]


def diagnose(source: str, *, symptoms: list[str] = (), smart_json: Path | None = None,
             ctx: audit.AuditContext | None = None) -> Diagnosis:
    diag = Diagnosis(source=source)
    for s in symptoms:
        for key, (verdict, reason) in SYMPTOM_RULES.items():
            if key in s:
                if verdict == REFER:
                    diag.level = "重度物理"
                diag.raise_to(verdict, reason)
    if diag.verdict in (REFER, REJECT) and any(k in " ".join(symptoms) for k in ("異音", "不回転")):
        # 異音機は通電しない：媒体へのアクセス自体を行わない
        diag.warnings.append("媒体にアクセスせずに診断を終了（通電・読み込みを行わない）")
        return diag

    smart = load_smart(source, smart_json, ctx)
    if smart is not None:
        evaluate_smart(smart, diag)
    if diag.verdict == REFER and diag.level == "重度物理":
        diag.warnings.append("SMART 危険のため構造の読み取りを省略")
        return diag

    if Path(source).exists():
        try:
            diag.size = safety.source_size(source, ctx)
        except Exception:  # noqa: BLE001 - サイズ不明でも診断は続ける
            diag.size = None
        offsets = probe_structure(source, diag, ctx)
        diag.encryption = detect_encryption(source, offsets)
        for e in diag.encryption:
            diag.raise_to(e["verdict"], e["reason"])
        if not diag.filesystems and not diag.encryption:
            diag.warnings.append("既知のファイルシステムを検出できず（フォーマット・パーティション破損の可能性）。"
                                 "S1 パーティション探索と S5 カービングで調査")
    if not diag.reasons:
        diag.raise_to(IN_HOUSE, "自社対応範囲")
    return diag


def save(diag: Diagnosis, case, device_id: int | None = None) -> int:
    from .db import now

    did = case.db.insert("diagnoses", case_id=case.id, device_id=device_id, created_at=now(),
                         verdict=diag.verdict, report=json.dumps(diag.to_dict(), ensure_ascii=False))
    case.advance("診断済")
    return did


def latest(case) -> dict | None:
    row = case.db.one("SELECT report FROM diagnoses WHERE case_id=? ORDER BY id DESC LIMIT 1", case.id)
    return json.loads(row["report"]) if row else None
