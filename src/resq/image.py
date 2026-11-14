"""イメージ化：原本 → イメージファイル（企画書 §3.3-3, P2 / §3.8 S0）。

GNU ddrescue を必ず mapfile 付きで呼ぶ。同じ案件・同じ原本で未完了のイメージがあれば
同じ mapfile で再開する（中断・再開・再読込）。

  パス1: ddrescue -n   （スクレイピングなしで読める所を先に全部読む）
  パス2: ddrescue -r N （読めなかった領域だけを N 回再試行）

TODO(S0): ファイル管理領域（MFT 等）を優先して先に読む（-m ドメイン mapfile）。作業機での検証後に実装。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import IO

from . import audit, diagnose, safety
from .cases import Case
from .db import now
from .errors import SafetyError
from .hashing import sha256_file
from .intake import require_consent

FINISHED = "+"
UNTRIED = "?"


@dataclass
class MapStatus:
    size: int
    finished: int
    untried: int
    bad: int          # '-' 不良セクタ
    pending: int      # '*' '/' トリミング・スクレイピング未了

    @property
    def complete(self) -> bool:
        return self.untried == 0 and self.pending == 0

    @property
    def unreadable(self) -> int:
        return self.bad + self.pending


def parse_mapfile(text: str) -> MapStatus:
    """ddrescue mapfile を解析する。

    書式: '#' コメント行 → 現在位置行（pos status [pass]）→ ブロック行（pos size status）
    """
    lines = [ln.split() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return MapStatus(0, 0, 0, 0, 0)
    blocks = [ln for ln in lines[1:] if len(ln) >= 3]
    acc = {"+": 0, "?": 0, "-": 0, "*": 0, "/": 0}
    end = 0
    for pos, size, st in (b[:3] for b in blocks):
        p, s = int(pos, 0), int(size, 0)
        acc[st] = acc.get(st, 0) + s
        end = max(end, p + s)
    return MapStatus(size=end, finished=acc["+"], untried=acc["?"], bad=acc["-"],
                     pending=acc["*"] + acc["/"])


def _check_diagnosis(case: Case, accept_risk: bool) -> None:
    d = diagnose.latest(case)
    if d is None:
        raise SafetyError("診断が未実施です。先に `resq diagnose` を実行してください。")
    if d["verdict"] in (diagnose.REFER, diagnose.REJECT):
        raise SafetyError(f"診断判定が『{d['verdict']}』のためイメージ化しません: {'; '.join(d['reasons'])}")
    if d.get("requires_confirmation") and not accept_risk:
        raise SafetyError("SMART に危険兆候があります。内容を顧客に説明し、続行するなら --accept-risk を付けてください。"
                          f"（{'; '.join(d['warnings'])}）")


def acquire(case: Case, source: str, *, device_id: int | None = None, accept_risk: bool = False,
            retry_passes: int = 3, sector_size: int = 512, max_bytes: int | None = None,
            stream: IO[str] | None = None) -> int:
    """原本をイメージ化し、images.id を返す。

    max_bytes はテスト・分割取得用（その位置で中断したのと同じ状態になる）。
    """
    require_consent(case)
    _check_diagnosis(case, accept_risk)
    ctx = case.ctx
    is_dev = safety.is_device(source)
    safety.assert_source_readonly(source, ctx)
    size = safety.source_size(source, ctx)

    row = case.db.one("SELECT * FROM images WHERE case_id=? AND source=? AND sha256 IS NULL "
                      "ORDER BY id DESC LIMIT 1", case.id, source)
    if row:
        image_id = row["id"]
        img, mapf = Path(row["path"]), Path(row["mapfile"])
        case.db.add_event(case.id, "image.resume", str(img), 0)
    else:
        n = (case.db.one("SELECT COUNT(*) AS c FROM images WHERE case_id=?", case.id)["c"] or 0) + 1
        img = case.sub("images") / f"img{n:02d}.dd"
        mapf = img.with_suffix(".map")
        image_id = case.db.insert("images", case_id=case.id, device_id=device_id, source=source,
                                  path=str(img), mapfile=str(mapf), size=size, created_at=now())

    have = img.stat().st_size if img.exists() else 0
    safety.assert_writable_target(img, case_dir=case.dir, source=source, required_bytes=max(size - have, 0))
    safety.assert_writable_target(mapf, case_dir=case.dir, source=source)

    common = ["-b", str(sector_size)]
    if is_dev:
        common.append("-d")  # 直接アクセス（キャッシュを介さない）。デバイスのときのみ
    # 出力先はデバイスでないので -f（強制上書き）は決して付けない
    first = ["ddrescue", "-n", *common]
    if max_bytes is not None:
        first += ["-s", str(max_bytes)]
    audit.run([*first, source, img, mapf], op="image.pass1", ctx=ctx, allow_device=is_dev, stream=stream)

    status = parse_mapfile(mapf.read_text())
    if max_bytes is None and status.unreadable > 0 and retry_passes > 0:
        audit.run(["ddrescue", *common, "-r", str(retry_passes), source, img, mapf], op="image.retry",
                  ctx=ctx, allow_device=is_dev, stream=stream)
        status = parse_mapfile(mapf.read_text())

    complete = status.untried == 0 and status.size >= size
    if complete:
        digest = sha256_file(img)
        safety.make_file_readonly(img)
        case.db.execute("UPDATE images SET sha256=?, unreadable_bytes=? WHERE id=?",
                        digest, status.unreadable, image_id)
        case.db.add_event(case.id, "image.done",
                          f"id={image_id} sha256={digest} unreadable={status.unreadable}", 0)
        case.advance("イメージ取得済")
    else:
        case.db.execute("UPDATE images SET unreadable_bytes=? WHERE id=?", status.unreadable, image_id)
        case.db.add_event(case.id, "image.partial",
                          f"id={image_id} finished={status.finished} untried={status.untried}", 0)
    return image_id


def register_existing(case: Case, image_path: Path, *, device_id: int | None = None) -> int:
    """持ち込み済み・他機で取得済みのイメージを案件に登録する（読み取り専用であること）。"""
    safety.assert_source_readonly(image_path)
    p = image_path.resolve()
    digest = sha256_file(p)
    iid = case.db.insert("images", case_id=case.id, device_id=device_id, source=f"file:{p}", path=str(p),
                         mapfile=None, size=p.stat().st_size, sha256=digest, unreadable_bytes=0,
                         created_at=now())
    case.db.add_event(case.id, "image.register", f"id={iid} {p} sha256={digest}", 0)
    return iid


def get_image(case: Case, image_id: int | None = None):
    if image_id is None:
        row = case.db.one("SELECT * FROM images WHERE case_id=? AND sha256 IS NOT NULL ORDER BY id DESC LIMIT 1",
                          case.id)
    else:
        row = case.db.one("SELECT * FROM images WHERE case_id=? AND id=?", case.id, image_id)
    if row is None:
        raise SafetyError("完了済みのイメージがありません（イメージ化が未完了の可能性）")
    if not row["sha256"]:
        raise SafetyError(f"イメージ {row['id']} は未完了です。`resq image` で再開してください。")
    return row
