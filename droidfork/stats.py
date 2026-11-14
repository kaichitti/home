"""PoC の実測（企画書6章・9章「1台あたりの増分を実測」）。

- ディスク: 共有層（雛形）とイメージは全台で1つ。各インスタンスの差分層の実サイズが1台あたりの増分。
- メモリ: 起動中コンテナの使用量（docker stats）。
- 比較: 雛形を台数ぶん丸ごとコピーした場合のディスク量。
"""

from __future__ import annotations

import os
from statistics import mean
from typing import TYPE_CHECKING

from .hostcheck import ksm_status, meminfo
from .instances import container_states
from .redroid import base_volume_name, container_name, diff_volume_name
from .util import format_bytes, format_table, now_iso

if TYPE_CHECKING:
    from .app import App


def _page_size() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError, AttributeError):
        return 4096


def collect_stats(app: "App") -> dict:
    app.docker.ensure_daemon()
    templates = app.store.list_templates()
    instances = app.store.list_instances()
    sizes = app.docker.volume_sizes()
    states = container_states(app)
    running_names = [container_name(i.id) for i in instances if states.get(container_name(i.id)) == "running"]
    usage = app.docker.stats(running_names)

    images: dict[str, dict] = {}
    for t in templates:
        if t.image_id and t.image_id not in images:
            images[t.image_id] = {"ref": t.image, "id": t.image_id, "size": app.docker.image_size(t.image_id)}

    template_rows = [
        {"name": t.name, "state": t.state, "volume": base_volume_name(t.name),
         "base_size": sizes.get(base_volume_name(t.name))}
        for t in templates
    ]
    base_by_template = {r["name"]: r["base_size"] for r in template_rows}

    instance_rows = []
    for inst in instances:
        name = container_name(inst.id)
        u = usage.get(name, {})
        instance_rows.append({
            "id": inst.id,
            "template": inst.template,
            "running": states.get(name) == "running",
            "diff_size": sizes.get(diff_volume_name(inst.id)),
            "mem": u.get("mem"),
            "cpu": u.get("cpu"),
            "boot_seconds": inst.last_boot_seconds,
        })

    diffs = [r["diff_size"] for r in instance_rows if r["diff_size"] is not None]
    mems = [r["mem"] for r in instance_rows if r["mem"] is not None]
    boots = [r["boot_seconds"] for r in instance_rows if r["boot_seconds"]]
    used_templates = {i.template for i in instances}
    shared = sum(base_by_template.get(t) or 0 for t in used_templates)
    copy_total = sum(base_by_template.get(i.template) or 0 for i in instances) + sum(diffs)
    actual_total = shared + sum(diffs)

    mem = meminfo(app.host)
    avg_mem = mean(mems) if mems else None
    available = mem.get("MemAvailable")
    ksm = ksm_status(app.host)

    summary = {
        "instances": len(instances),
        "running": len(running_names),
        "avg_diff_size": mean(diffs) if diffs else None,
        "max_diff_size": max(diffs) if diffs else None,
        "avg_mem": avg_mem,
        "avg_boot_seconds": round(mean(boots), 1) if boots else None,
        "shared_data_size": shared,
        "actual_data_total": actual_total,
        "full_copy_data_total": copy_total,
        "host_mem_total": mem.get("MemTotal"),
        "host_mem_available": available,
        "more_instances_estimate": int(available // avg_mem) if avg_mem and available else None,
        "ksm": None if ksm is None else {**ksm, "saved_bytes": ksm["pages_sharing"] * _page_size()},
    }
    return {
        "measured_at": now_iso(),
        "images": list(images.values()),
        "templates": template_rows,
        "instances": instance_rows,
        "summary": summary,
    }


def render_stats(data: dict) -> str:
    s = data["summary"]
    out = [f"計測日時: {data['measured_at']}", "", "■ 全台で共有（1つだけ）"]
    shared_rows = [["イメージ", i["ref"] or i["id"][:19], format_bytes(i["size"])] for i in data["images"]]
    shared_rows += [["雛形の共有層", t["name"], format_bytes(t["base_size"])] for t in data["templates"]]
    out.append(format_table(["種類", "名前", "サイズ"], shared_rows) if shared_rows else "（まだありません）")

    out += ["", "■ インスタンスごと（差分のみ）"]
    if data["instances"]:
        out.append(format_table(
            ["ID", "状態", "ディスク増分", "メモリ", "CPU", "前回起動"],
            [[r["id"], "起動中" if r["running"] else "停止", format_bytes(r["diff_size"]),
              format_bytes(r["mem"]) if r["running"] else "-", r["cpu"] or "-",
              f"{r['boot_seconds']:.0f}秒" if r["boot_seconds"] else "-"]
             for r in data["instances"]],
        ))
    else:
        out.append("（まだありません）")

    out += ["", "■ まとめ"]
    lines = [
        ["台数", f"{s['instances']} 台（起動中 {s['running']} 台）"],
        ["1台あたりディスク増分", f"平均 {format_bytes(s['avg_diff_size'])} / 最大 {format_bytes(s['max_diff_size'])}"],
        ["1台あたりメモリ", f"平均 {format_bytes(s['avg_mem'])}（起動中のみ）"],
        ["起動時間", f"平均 {s['avg_boot_seconds']:.0f} 秒" if s["avg_boot_seconds"] else "不明"],
    ]
    if s["instances"]:
        ratio = s["actual_data_total"] / s["full_copy_data_total"] * 100 if s["full_copy_data_total"] else None
        lines.append(["データ領域の合計",
                      f"{format_bytes(s['actual_data_total'])}（雛形を丸ごとコピーした場合 "
                      f"{format_bytes(s['full_copy_data_total'])}"
                      + (f"、{ratio:.0f}%）" if ratio is not None else "）")])
    if s["host_mem_total"]:
        line = f"合計 {format_bytes(s['host_mem_total'])} / 空き {format_bytes(s['host_mem_available'])}"
        if s["more_instances_estimate"] is not None:
            line += f" → あと約 {s['more_instances_estimate']} 台起動できる見込み"
        lines.append(["ホストのメモリ", line])
    if s["ksm"] is not None:
        state = "有効" if s["ksm"]["run"] == 1 else "無効"
        lines.append(["KSM（同一ページ統合）", f"{state}、統合による節約 {format_bytes(s['ksm']['saved_bytes'])}"])
    out.append(format_table(["項目", "値"], lines))
    return "\n".join(out)
