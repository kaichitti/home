"""暗号化ボリュームの解錠（P7：BitLocker / LUKS）。

顧客が提示した回復キーを画面で入力してもらい、イメージを読み取り専用で解錠する。
  - 回復キーは標準入力で cryptsetup に渡す（コマンドラインに載せない）
  - DB・ログ・ファイル・例外メッセージに出さない（audit の secrets で伏字）
  - 保存しない。呼び出し側は使用後に変数を破棄する

  cryptsetup open --type bitlk --readonly --key-file=- <イメージ> <名前>   → /dev/mapper/<名前>
解錠したデバイスは image.acquire() でさらにイメージ化（復号済みイメージ）してから復旧にかける。
パーティションの中に暗号化ボリュームがある場合は、先に extract_partition() でその範囲だけを
別のイメージファイルに切り出す（cryptsetup は BitLocker でオフセット指定ができないため）。
root が必要なため、実行は作業機で行う。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import audit, safety
from .cases import Case
from .db import now
from .errors import CommandError, ResqError
from .hashing import sha256_file
from .image import get_image

TYPES = {"bitlk": "BitLocker", "luks": "LUKS"}


def normalize_recovery_password(text: str) -> str:
    """BitLocker 回復パスワード（6 桁×8 組）を検証・整形する。

    各組は 11 の倍数かつ 720896 未満（BitLocker の仕様）。入力ミスをその場で検出できる。
    例外メッセージにはキーそのものを含めない。
    """
    digits = re.sub(r"[\s-]", "", text)
    if not digits.isdigit() or len(digits) != 48:
        raise ResqError("回復キーは 6 桁×8 組（48 桁）の数字です")
    groups = [digits[i:i + 6] for i in range(0, 48, 6)]
    bad = [i + 1 for i, g in enumerate(groups) if int(g) % 11 or int(g) >= 720896]
    if bad:
        raise ResqError(f"回復キーの {', '.join(map(str, bad))} 組目が正しくありません（入力ミスの可能性）")
    return "-".join(groups)


def mapper_name(case: Case, image_id: int) -> str:
    return f"resq-{case.id}-img{image_id}-dec"


def open_command(kind: str, image: Path, name: str) -> list[str]:
    if kind not in TYPES:
        raise ResqError(f"未対応の暗号化方式: {kind}")
    return ["cryptsetup", "open", "--type", kind, "--readonly", "--key-file=-", str(image), name]


def extract_partition(case: Case, image_id: int, offset_sectors: int, length_sectors: int) -> int:
    """イメージの一部（パーティション）を別のイメージファイルに切り出して登録する。"""
    row = get_image(case, image_id)
    src = Path(row["path"])
    dest = case.sub("images") / f"img{image_id:02d}-p{offset_sectors}.dd"
    length = length_sectors * 512
    safety.assert_writable_target(dest, case_dir=case.dir, source=src, required_bytes=length)
    with open(src, "rb") as fi, open(dest, "xb") as fo:
        fi.seek(offset_sectors * 512)
        left = length
        while left:
            chunk = fi.read(min(left, 4 << 20))
            if not chunk:
                break
            fo.write(chunk)
            left -= len(chunk)
    safety.make_file_readonly(dest)
    iid = case.db.insert("images", case_id=case.id, device_id=row["device_id"],
                         source=f"part:{image_id}@{offset_sectors}", path=str(dest), mapfile=None,
                         size=dest.stat().st_size, sha256=sha256_file(dest), unreadable_bytes=0, created_at=now())
    case.db.add_event(case.id, "unlock.extract_partition", f"img{image_id}@{offset_sectors}+{length_sectors} -> {iid}", 0)
    return iid


def unlock(case: Case, image_id: int, key: str, *, kind: str = "bitlk") -> str:
    """解錠して、読み取り専用のデバイスパスを返す。key はこの関数の外へ残さない。"""
    row = get_image(case, image_id)
    image = Path(row["path"])
    safety.assert_source_readonly(image, case.ctx)
    raw = key
    if kind == "bitlk" and re.fullmatch(r"[\d\s-]+", key.strip()):
        key = normalize_recovery_password(key)  # 数字だけなら回復パスワードとして検証・整形
    secrets = [raw, raw.strip(), key, key.replace("-", "")]
    name = mapper_name(case, image_id)
    try:
        audit.run(open_command(kind, image, name), op="unlock.open", ctx=case.ctx, input_text=key,
                  secrets=secrets)
    except CommandError as e:
        # audit が伏字にしたメッセージのみを使う。キーは含まれない
        raise ResqError(f"解錠できませんでした（回復キー違い、または未対応の形式）: {e}") from None
    dev = f"/dev/mapper/{name}"
    case.db.add_event(case.id, "unlock.opened", f"img{image_id} {TYPES[kind]} -> {dev}", 0)
    return dev


def close(case: Case, image_id: int) -> None:
    audit.run(["cryptsetup", "close", mapper_name(case, image_id)], op="unlock.close", ctx=case.ctx)


def available() -> bool:
    return shutil.which("cryptsetup") is not None
