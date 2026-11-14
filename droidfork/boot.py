"""コンテナ内の Android の起動完了を待つ処理。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .util import DroidForkError, indent

if TYPE_CHECKING:
    from .app import App


@dataclass
class BootTarget:
    key: str
    addr: str          # adb のアドレス（127.0.0.1:ポート）
    container: str
    started_at: float  # docker run した時刻（app.clock）


def _crashed_error(app: "App", target: BootTarget, status: str | None) -> DroidForkError:
    logs = app.docker.logs_tail(target.container, 20)
    message = f"{target.key}: コンテナが停止しました（状態: {status or 'なし'}）。"
    if logs:
        message += "\n直近のログ:\n" + indent(logs, "  | ")
    return DroidForkError(
        message,
        hint="カーネルの binder / overlayfs 対応を `droidfork doctor` で確認してください。"
             f"詳しいログは docker logs {target.container} で見られます。",
    )


def wait_for_boot_many(app: "App", targets: list[BootTarget], timeout: float) -> dict[str, "float | DroidForkError"]:
    """全台の起動完了（sys.boot_completed=1）をまとめて待つ。結果は起動秒数かエラー。"""
    results: dict[str, float | DroidForkError] = {}
    pending = {t.key: t for t in targets}
    deadline = app.clock() + timeout
    while pending:
        for key, target in list(pending.items()):
            status = app.docker.container_status(target.container)
            if status != "running":
                results[key] = _crashed_error(app, target, status)
                del pending[key]
                continue
            if app.adb.connect(target.addr):
                out = app.adb.shell(target.addr, "getprop sys.boot_completed", check=False, timeout=15)
                if out.strip() == "1":
                    results[key] = round(app.clock() - target.started_at, 1)
                    del pending[key]
        if not pending:
            break
        if app.clock() >= deadline:
            for key, target in pending.items():
                results[key] = DroidForkError(
                    f"{key}: {timeout:g} 秒以内に起動が完了しませんでした。",
                    hint=f"docker logs {target.container} で状況を確認してください。"
                         "台数が多いときは --timeout で待ち時間を延ばせます。",
                )
            break
        app.sleep(app.poll_interval)
    return results


def wait_for_boot(app: "App", target: BootTarget, timeout: float) -> float:
    result = wait_for_boot_many(app, [target], timeout)[target.key]
    if isinstance(result, DroidForkError):
        raise result
    return result


def ensure_root_shell(app: "App", addr: str, timeout: float = 90) -> None:
    """雛形作成用に root の adb シェルを確保する（ro.secure=0 で起動済みなら何もしない）。"""
    if app.adb.shell(addr, "id -u", check=False, timeout=15).strip() == "0":
        return
    app.adb.root(addr)  # adbd が root で再起動し、TCP 接続が切れる
    deadline = app.clock() + timeout
    while app.clock() < deadline:
        app.sleep(app.poll_interval)
        if app.adb.connect(addr) and app.adb.shell(addr, "id -u", check=False, timeout=15).strip() == "0":
            return
    raise DroidForkError(
        "雛形の作成には root の adb シェルが必要ですが、取得できませんでした。",
        hint="userdebug ビルドの Redroid イメージを使ってください（公式イメージは対応しています）。",
    )
