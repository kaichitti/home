"""スナップショット（企画書5章 v2）。

インスタンスの差分層（Docker ボリューム）を、そのまま別のボリュームへ写して保存する。
差分層は overlayfs の上層なので、削除の印（ホワイトアウト）や拡張属性を含む。
これを壊さないよう、特権コンテナの中で `cp -a`（所有者・権限・拡張属性・特殊ファイルを保持）で写す。

戻すとき:
- 同じインスタンスへ: そのまま戻す（ログイン状態なども含めて元どおり）
- 同じテンプレートの別のインスタンスへ: アプリのデータは引き継ぐが、Android ID の元になる
  設定ファイルは消して、その台の初回起動で作り直させる（企画書8章：識別子を複製しない）
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Sequence

from .instances import container_states, start_instances, stop_instances
from .redroid import LABEL_MANAGED, LABEL_ROLE, LABEL_TEMPLATE, container_name, diff_volume_name
from .store import Instance, Snapshot
from .util import DroidForkError, now_iso, validate_name

if TYPE_CHECKING:
    from .app import App

# 別のインスタンスへ戻すときに消すファイル（差分層の中での位置は問わない）
IDENTITY_FILES = (
    "*/system/users/0/settings_ssaid.xml",   # アプリから見える Android ID の鍵
    "*/system/users/0/settings_secure.xml*",  # android_id を含む設定（消すと雛形の内容に戻る）
)


def snapshot_volume_name(name: str) -> str:
    return f"droidfork-snap-{name}"


def _ensure_helper(app: "App") -> str:
    image = app.cfg.helper_image
    if app.docker.image_id(image) is None:
        app.console.step(f"複製用のイメージ {image} を取得します")
        app.docker.pull(image)
    return image


def copy_volume(app: "App", src: str, dst: str, *, strip_identity: bool = False) -> None:
    """ボリュームの中身を、拡張属性や overlayfs の削除の印ごと写す。"""
    image = _ensure_helper(app)
    script = "cp -a /src/. /dst/"
    if strip_identity:
        for pattern in IDENTITY_FILES:
            script += f" && find /dst -path '{pattern}' -delete"
    app.docker.cmd(
        "run", "--rm", "--privileged", "--network", "none",
        "-v", f"{src}:/src:ro", "-v", f"{dst}:/dst",
        image, "sh", "-c", script,
        timeout=3600,
    )


def _labels(template: str, role: str) -> dict[str, str]:
    return {LABEL_MANAGED: "1", LABEL_ROLE: role, LABEL_TEMPLATE: template}


def create_snapshot(app: "App", inst: Instance, name: str | None = None, note: str | None = None) -> Snapshot:
    name = name or f"{inst.id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    validate_name(name, "スナップショット名")
    if app.store.snapshot_exists(name):
        raise DroidForkError(f"スナップショット「{name}」はすでにあります。")
    app.docker.ensure_daemon()
    was_running = container_states(app).get(container_name(inst.id)) == "running"
    if was_running:
        app.console.step(f"{inst.id} を一時停止して保存します")
        stop_instances(app, [inst])
    volume = snapshot_volume_name(name)
    snapshot = Snapshot(name=name, template=inst.template, source=inst.id, created_at=now_iso(), note=note)
    try:
        app.docker.volume_rm(volume)
        app.docker.volume_create(volume, _labels(inst.template, "snapshot"))
        copy_volume(app, diff_volume_name(inst.id), volume)
        app.store.save_snapshot(snapshot)
    except BaseException:
        app.docker.volume_rm(volume)
        raise
    finally:
        if was_running:
            start_instances(app, [inst], wait=False)
    return snapshot


def restore_snapshot(app: "App", snapshot: Snapshot, targets: Sequence[Instance]) -> dict[str, object]:
    for inst in targets:
        if inst.template != snapshot.template:
            raise DroidForkError(
                f"{inst.id} はテンプレート「{inst.template}」の台なので、"
                f"「{snapshot.template}」のスナップショットは戻せません。",
                hint="スナップショットは、同じテンプレートから作った台にだけ戻せます。",
            )
    app.docker.ensure_daemon()
    volume = snapshot_volume_name(snapshot.name)
    if not app.docker.volume_exists(volume):
        raise DroidForkError(f"スナップショットのボリューム {volume} が見つかりません。")
    states = container_states(app)
    was_running = [i for i in targets if states.get(container_name(i.id)) == "running"]
    stop_instances(app, targets)
    for inst in targets:
        diff = diff_volume_name(inst.id)
        app.docker.volume_rm(diff)
        app.docker.volume_create(diff, {**_labels(inst.template, "diff"), "droidfork.instance": inst.id})
        other = inst.id != snapshot.source
        copy_volume(app, volume, diff, strip_identity=other)
        app.console.info(f"{inst.id}: 戻しました" + ("（Android ID は次の起動で作り直します）" if other else ""))
        inst.last_boot_seconds = None
        app.store.save_instance(inst)
    if was_running:
        return start_instances(app, was_running)
    return {}


def remove_snapshots(app: "App", snapshots: Sequence[Snapshot]) -> None:
    for snapshot in snapshots:
        app.docker.volume_rm(snapshot_volume_name(snapshot.name))
        app.store.remove_snapshot_file(snapshot.name)
