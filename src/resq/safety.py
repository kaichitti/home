"""安全装置。全処理が必ず通る（企画書 §3.7）。

- 原本は読み取り専用であることを確認できなければ止める
- 出力先が実デバイス・原本と同じ物理ディスク・案件ディレクトリ外なら拒否
- 出力先の空き容量が必要量×1.1 未満なら拒否
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from . import audit
from .errors import SafetyError

SPACE_FACTOR = 1.1


def is_device(path: str | os.PathLike) -> bool:
    p = str(path)
    if p.startswith("/dev/"):
        return True
    try:
        mode = os.stat(p).st_mode
    except OSError:
        return False
    return stat.S_ISBLK(mode) or stat.S_ISCHR(mode)


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _existing_parent(p: Path) -> Path:
    while not p.exists():
        if p.parent == p:
            break
        p = p.parent
    return p


def _disk_of_devnum(major: int, minor: int) -> str | None:
    """major:minor から物理ディスク名（sda / nvme0n1 等）を求める。"""
    sys_path = Path(f"/sys/dev/block/{major}:{minor}")
    try:
        real = sys_path.resolve(strict=True)
    except OSError:
        return None
    # パーティションなら親ディレクトリがディスク
    if (real / "partition").exists():
        return real.parent.name
    return real.name


def physical_disk(path: str | os.PathLike) -> str | None:
    """パス（デバイスまたは通常ファイル）が載っている物理ディスク名。不明なら None。"""
    p = str(path)
    try:
        st = os.stat(p)
    except OSError:
        return None
    if stat.S_ISBLK(st.st_mode):
        return _disk_of_devnum(os.major(st.st_rdev), os.minor(st.st_rdev))
    return _disk_of_devnum(os.major(st.st_dev), os.minor(st.st_dev))


def assert_writable_target(target: str | os.PathLike, *, case_dir: Path,
                           source: str | os.PathLike | None = None,
                           required_bytes: int | None = None) -> Path:
    """書き込み先の検査。問題なければ解決済みのパスを返す。"""
    raw = str(target)
    if raw.startswith("/dev/") or is_device(raw):
        raise SafetyError(f"出力先にデバイスは指定できません: {raw}")
    t = Path(raw).resolve()
    case_root = case_dir.resolve()
    if not _within(t, case_root):
        raise SafetyError(f"案件ディレクトリ外への書き込みは禁止です: {t}（許可: {case_root}）")
    if source is not None:
        src = str(source)
        if not is_device(src):
            if Path(src).resolve() == t:
                raise SafetyError("出力先が原本（入力イメージ）と同じファイルです")
        else:
            sd = physical_disk(src)
            td = physical_disk(_existing_parent(t))
            if sd is None:
                raise SafetyError(f"原本の物理ディスクを特定できません: {src}")
            if td is None or sd == td:
                raise SafetyError(f"出力先が原本と同じ物理ディスク（{sd}）上にあるか、判定できません")
    if required_bytes is not None:
        free = shutil.disk_usage(_existing_parent(t)).free
        need = int(required_bytes * SPACE_FACTOR)
        if free < need:
            raise SafetyError(
                f"出力先の空き容量不足: 空き {free:,} B < 必要 {need:,} B（原本×{SPACE_FACTOR}）")
    return t


def source_size(source: str | os.PathLike, ctx: audit.AuditContext | None = None) -> int:
    src = str(source)
    if is_device(src):
        out = audit.run(["blockdev", "--getsize64", src], op="safety.size", ctx=ctx, allow_device=True)
        return int(out.stdout.strip())
    return Path(src).stat().st_size


def assert_source_readonly(source: str | os.PathLike, ctx: audit.AuditContext | None = None) -> None:
    """原本が読み取り専用であることを確認する。確認できなければ止める。

    ブロックデバイス: カーネルの読み取り専用フラグ（blockdev --getro が 1）を要求する。
    ハードウェアのライトブロッカーと併用する前提で、ソフト側でも二重に確認する。
    通常ファイル（イメージ）: 書き込み権限が落ちていること（chmod a-w）を要求する。
    """
    src = str(source)
    if is_device(src):
        out = audit.run(["blockdev", "--getro", src], op="safety.getro", ctx=ctx, allow_device=True)
        if out.stdout.strip() != "1":
            raise SafetyError(
                f"原本 {src} が読み取り専用になっていません。作業機で `blockdev --setro {src}` を実行し、"
                "ライトブロッカー経由で接続してください。")
        return
    p = Path(src)
    if not p.is_file():
        raise SafetyError(f"原本が見つかりません: {src}")
    if p.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise SafetyError(f"原本イメージに書き込み権限が残っています。`chmod a-w {src}` で読み取り専用にしてください。")


def make_file_readonly(path: Path) -> None:
    """取得済みイメージを読み取り専用にする（以降の処理での誤書き込み防止）。"""
    mode = path.stat().st_mode
    path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def safe_join(base: Path, *parts: str) -> Path:
    """外部由来のファイル名（復旧結果のパス等）を案件ディレクトリ内に安全に連結する。"""
    cleaned = []
    for part in parts:
        for seg in str(part).replace("\\", "/").split("/"):
            seg = seg.strip().replace("\0", "")
            if seg in ("", ".", ".."):
                continue
            cleaned.append(seg[:200])
    p = base.joinpath(*cleaned) if cleaned else base
    if not _within(p.resolve(), base.resolve()):
        raise SafetyError(f"不正なパス: {parts}")
    return p
