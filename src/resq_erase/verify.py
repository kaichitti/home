"""E3 検証（企画書 §8.6）。

1 台ごとの検証（verification）:
  1. 消去命令の完了ステータス（「送った」ではなく「ドライブが完了と返した」）
  2. 読み戻し検査：上書き方式は全域が期待パターンか、Sanitize / 暗号消去は全域またはサンプリングで
     「構造のあるデータが残っていない」（一様な値、または高エントロピー）か
  3. 復旧試行：resq の復旧手法 S1・S2・S5 を読み取り専用で当て、回収 0 件を確認する
手順の妥当性確認（validation）:
  月 1 回、テスト用ジャンクドライブに既知データ → 消去 → 復旧試行で 0 件、を型番ごとに記録する。
"""
from __future__ import annotations

import json
import math
import random
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from resq import validate as V
from resq.audit import AuditContext
from resq.recover import partitions, photorec, tsk

from .ledger import Ledger, now

BLOCK = 4096
ENTROPY_MIN = 7.2   # 4KiB ブロックのビット/バイト。暗号化・乱数由来ならほぼ 8.0


# ---------------------------------------------------------------- 完了ステータス
def nvme_sanitize_status(log: dict) -> str:
    sstat = int(log.get("sstat", 0)) & 0x7
    return {0: "never", 1: "completed", 2: "in_progress", 3: "failed", 4: "completed"}.get(sstat, "unknown")


def hdparm_sanitize_status(text: str) -> str:
    """hdparm --sanitize-status の出力（hdparm 9.65 のメッセージに合わせる）。"""
    t = text.lower()
    if "sanitize operation in process" in t:
        return "in_progress"
    if "sanitize operation failed" in t or "completed unsuccessfully" in t:
        return "failed"
    if "completed without error" in t:
        return "completed"
    return "unknown"   # SD0 Idle のみ・SD1 Frozen などは完了を示さない


# ---------------------------------------------------------------- 読み戻し
def _entropy(b: bytes) -> float:
    n = len(b)
    return -sum(c / n * math.log2(c / n) for c in Counter(b).values())


def _block_ok(b: bytes, expected: bytes | None) -> bool:
    if not b:
        return True
    if expected is not None:
        return b == (expected * (len(b) // len(expected) + 1))[: len(b)]
    if b.count(b[0]) == len(b):          # 一様（ゼロ・0xFF 等）
        return True
    return _entropy(b) >= ENTROPY_MIN    # 暗号消去後のランダムに見えるデータ


def readback(target: str | Path, size: int, *, expected: bytes | None, scope: str = "sample",
             samples: int = 512, seed: str = "") -> dict:
    """target を読み取り専用で読み、残存データの兆候がないか調べる。"""
    bad: list[int] = []
    checked = 0
    with open(target, "rb", buffering=0) as fh:
        if scope == "full":
            off = 0
            while off < size:
                fh.seek(off)
                chunk = fh.read(min(4 << 20, size - off))
                if not chunk:
                    break
                for i in range(0, len(chunk), BLOCK):
                    if not _block_ok(chunk[i:i + BLOCK], expected):
                        bad.append(off + i)
                checked += len(chunk)
                off += len(chunk)
        else:
            nblocks = max(1, size // BLOCK)
            rng = random.Random(seed or str(size))
            picks = set(range(min(256, nblocks)))                     # 先頭 1MiB（管理情報が集まる）
            picks |= set(range(max(0, nblocks - 256), nblocks))       # 末尾 1MiB
            picks |= {rng.randrange(nblocks) for _ in range(samples)}
            for b in sorted(picks):
                fh.seek(b * BLOCK)
                data = fh.read(BLOCK)
                checked += len(data)
                if not _block_ok(data, expected):
                    bad.append(b * BLOCK)
    return {"scope": scope, "checked_bytes": checked, "ok": not bad, "bad_count": len(bad),
            "bad_offsets": bad[:10]}


# ---------------------------------------------------------------- 復旧試行
@dataclass
class _WorkCase:
    """resq.recover の関数が要求する最小限の『案件』（作業ディレクトリと監査ログ）。"""
    dir: Path
    ctx: AuditContext = field(default=None)  # type: ignore[assignment]


def recovery_attempt(target: str | Path, *, allow_device: bool = False, use_photorec: bool = True,
                     work_dir: Path | None = None) -> dict:
    """S1・S2・S5 を読み取り専用で当て、開ける（＝復旧扱いになる）ファイルの数を数える。"""
    tmp = None
    if work_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="resq-erase-verify-")
        work_dir = Path(tmp.name)
    try:
        wc = _WorkCase(dir=work_dir.resolve(), ctx=AuditContext(log_path=work_dir / "audit.jsonl"))
        target_p = Path(target)
        vols = partitions.find_volumes(target_p, work_dir / "S1", wc.ctx, use_testdisk=True,
                                       allow_device=allow_device)
        cands = tsk.extract(wc, target_p, vols, work_dir / "S2", op="verify.S2", allow_device=allow_device)
        if use_photorec:
            cands += photorec.run(wc, None, target_p, work_dir / "S5", allow_device=allow_device).candidates
        found = []
        for c in cands:
            f = wc.dir / c.stored
            if not f.is_file():
                continue
            r = V.validate(f, Path(c.orig_path).name if c.orig_path else None)
            if r.status not in V.NOT_RECOVERED:
                found.append({"path": c.orig_path or Path(c.stored).name, "status": r.status, "method": c.method})
        return {"recovered": len(found), "files": found[:20],
                "volumes": [f"{v['fstype']}@{v['offset']}" for v in vols]}
    finally:
        if tmp is not None:
            tmp.cleanup()


# ---------------------------------------------------------------- 1 台ごとの検証
def verify(ledger: Ledger, media_id: int, target: str | Path, size: int, *, expected: bytes | None,
           scope: str = "sample", completion: str | None = None, run_id: int | None = None,
           allow_device: bool = False, use_photorec: bool = True) -> dict:
    media = ledger.one("SELECT * FROM media WHERE id=?", media_id)
    rb = readback(target, size, expected=expected, scope=scope, seed=media["serial"])
    rec = recovery_attempt(target, allow_device=allow_device, use_photorec=use_photorec)
    completion_ok = completion in (None, "completed", "commands-ok")
    passed = bool(completion_ok and rb["ok"] and rec["recovered"] == 0)
    vid = ledger.insert("verifications", media_id=media_id, run_id=run_id, created_at=now(), completion=completion,
                        readback_scope=scope, readback_ok=int(rb["ok"]), recovered=rec["recovered"],
                        passed=int(passed), detail=json.dumps({"readback": rb, "recovery": rec}, ensure_ascii=False))
    ledger.execute("UPDATE media SET status=? WHERE id=?", "消去済" if passed else "検証不合格", media_id)
    ledger.event("verify", f"passed={passed} readback={rb['ok']} recovered={rec['recovered']}", media_id=media_id,
                 rc=0 if passed else 1)
    return {"id": vid, "passed": passed, "readback": rb, "recovery": rec, "completion": completion}


# ---------------------------------------------------------------- 月次の妥当性確認
def record_validation(ledger: Ledger, *, model: str, kind: str, method: str, planted_files: int,
                      recovered: int, operator: str = "") -> int:
    vid = ledger.insert("validations", performed_at=now(), model=model, kind=kind, method=method,
                        planted_files=planted_files, recovered=recovered, passed=int(recovered == 0),
                        operator=operator)
    ledger.event("validation", f"{model} {method} planted={planted_files} recovered={recovered}")
    return vid


def validation_table(ledger: Ledger) -> list[dict]:
    """型番×方式ごとの実績表（『この型番はこの方式で合格』）。"""
    rows = ledger.all("""SELECT model, kind, method, COUNT(*) AS runs, SUM(passed) AS passes,
                                MAX(performed_at) AS last FROM validations GROUP BY model, kind, method
                         ORDER BY model, method""")
    return [dict(r, all_passed=r["runs"] == r["passes"]) for r in rows]
