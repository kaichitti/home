"""スケジュール起動（企画書5章 v2）。

予定（何時に・どの曜日に・どの台を・起動/停止/再起動/リセット）を schedules.json に保存し、
`droidfork schedule run-due` が「前回の確認から今までの間に来た予定」を実行する。
run-due は systemd のユーザータイマー（1分ごと）か、`--loop` で常駐させて呼ぶ。
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from .util import DroidForkError, now_iso, read_json, write_json

if TYPE_CHECKING:
    from .app import App
    from .store import Instance

ACTIONS = {"start": "起動", "stop": "停止", "restart": "再起動", "reset": "リセット"}
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]
DAY_ALIASES = {
    "daily": list(range(7)), "everyday": list(range(7)), "毎日": list(range(7)),
    "weekdays": list(range(5)), "平日": list(range(5)),
    "weekends": [5, 6], "土日": [5, 6],
}
CATCH_UP = timedelta(minutes=15)  # PCがスリープしていた等で遅れた予定は、15分以内なら実行する

UNIT_NAME = "droidfork-scheduler"


@dataclass
class Schedule:
    id: str
    action: str
    at: str                      # "HH:MM"（ホストのローカル時刻）
    days: list[int]              # 0=月 … 6=日
    template: str | None = None
    ids: list[str] = field(default_factory=list)
    all: bool = False
    enabled: bool = True
    created_at: str = ""
    last_run: str | None = None
    last_result: str | None = None

    def target_label(self) -> str:
        if self.all:
            return "すべて"
        if self.template:
            return f"テンプレート {self.template}"
        return ", ".join(self.ids)

    def days_label(self) -> str:
        if sorted(self.days) == list(range(7)):
            return "毎日"
        if sorted(self.days) == list(range(5)):
            return "平日"
        return "・".join(DAY_LABELS[d] for d in sorted(self.days))

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def parse_time(text: str) -> str:
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", text.strip())
    if not m:
        raise DroidForkError(f"時刻「{text}」を読めません。", hint="09:00 のように24時間表記で指定してください。")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def parse_days(text: str) -> list[int]:
    t = text.strip().lower()
    if t in DAY_ALIASES:
        return DAY_ALIASES[t]
    days: set[int] = set()
    for part in t.split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            if a in DAY_NAMES and b in DAY_NAMES:
                i, j = DAY_NAMES.index(a), DAY_NAMES.index(b)
                days.update(range(i, j + 1) if i <= j else [*range(i, 7), *range(0, j + 1)])
                continue
        elif part in DAY_NAMES:
            days.add(DAY_NAMES.index(part))
            continue
        raise DroidForkError(f"曜日「{text}」を読めません。",
                             hint="daily / weekdays / weekends / mon-fri / mon,wed,fri のように指定してください。")
    return sorted(days)


# ---- 保存 ----

def _load(app: "App") -> tuple[list[Schedule], dict]:
    path = app.cfg.schedules_path
    if not path.exists():
        return [], {}
    data = read_json(path)
    return [Schedule.from_dict(s) for s in data.get("schedules", [])], data.get("state", {})


def _save(app: "App", schedules: list[Schedule], state: dict) -> None:
    write_json(app.cfg.schedules_path, {"schedules": [asdict(s) for s in schedules], "state": state})


def list_schedules(app: "App") -> list[Schedule]:
    return _load(app)[0]


def add_schedule(
    app: "App",
    *,
    action: str,
    at: str,
    days: str = "daily",
    template: str | None = None,
    ids: list[str] | None = None,
    all_: bool = False,
) -> Schedule:
    if action not in ACTIONS:
        raise DroidForkError(f"動作「{action}」は使えません。", hint="start / stop / restart / reset のいずれかです。")
    ids = list(dict.fromkeys(ids or []))
    if sum(bool(x) for x in (template, ids, all_)) != 1:
        raise DroidForkError("対象を1つ指定してください。", hint="ID を並べるか、--template（-t）または --all を付けてください。")
    if template:
        app.store.load_template(template)
    for i in ids:
        app.store.load_instance(i)
    with app.store.lock():
        schedules, state = _load(app)
        numbers = [int(s.id[1:]) for s in schedules if re.match(r"^s\d+$", s.id)]
        schedule = Schedule(
            id=f"s{max(numbers, default=0) + 1}", action=action, at=parse_time(at), days=parse_days(days),
            template=template, ids=ids, all=all_, created_at=now_iso(),
        )
        schedules.append(schedule)
        _save(app, schedules, state)
    return schedule


def remove_schedule(app: "App", schedule_id: str) -> None:
    with app.store.lock():
        schedules, state = _load(app)
        remaining = [s for s in schedules if s.id != schedule_id]
        if len(remaining) == len(schedules):
            raise DroidForkError(f"予定「{schedule_id}」が見つかりません。", hint="`droidfork schedule list` で確認できます。")
        _save(app, remaining, state)


def set_enabled(app: "App", schedule_id: str, enabled: bool) -> None:
    with app.store.lock():
        schedules, state = _load(app)
        for s in schedules:
            if s.id == schedule_id:
                s.enabled = enabled
                _save(app, schedules, state)
                return
    raise DroidForkError(f"予定「{schedule_id}」が見つかりません。")


# ---- 実行 ----

def _dates(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def due_events(schedules: list[Schedule], last: datetime, now: datetime) -> list[tuple[Schedule, datetime]]:
    """last より後、now 以前に来た予定を時刻順に返す。"""
    events = []
    for s in schedules:
        if not s.enabled:
            continue
        hh, mm = (int(x) for x in s.at.split(":"))
        for d in _dates(last.date(), now.date()):
            when = datetime.combine(d, time(hh, mm))
            if when.weekday() in s.days and last < when <= now:
                events.append((s, when))
    return sorted(events, key=lambda e: e[1])


def _targets(app: "App", s: Schedule) -> list["Instance"]:
    if s.all:
        return app.store.list_instances()
    if s.template:
        return app.store.list_instances(template=s.template)
    found = []
    for i in s.ids:
        if app.store.instance_file(i).exists():
            found.append(app.store.load_instance(i))
    return found


def _execute(app: "App", s: Schedule) -> str:
    from .instances import reset_instances, start_instances, stop_instances

    targets = _targets(app, s)
    if not targets:
        return "対象の台がありません"
    if s.action == "start":
        results = start_instances(app, targets, wait=False)
    elif s.action == "stop":
        stop_instances(app, targets)
        results = {}
    elif s.action == "restart":
        stop_instances(app, targets)
        results = start_instances(app, targets, wait=False)
    else:
        results = reset_instances(app, targets, restart=True)
    failed = [k for k, v in results.items() if isinstance(v, DroidForkError)]
    return f"{len(targets)} 台を{ACTIONS[s.action]}" + (f"（失敗 {len(failed)} 台: {', '.join(failed)}）" if failed else "")


def run_due(app: "App", now: datetime | None = None) -> list[tuple[Schedule, str]]:
    now = now or datetime.now()
    with app.store.lock():
        schedules, state = _load(app)
        last_text = state.get("last_tick")
        last = datetime.fromisoformat(last_text) if last_text else now - timedelta(minutes=1)
        last = max(last, now - CATCH_UP)
        events = due_events(schedules, last, now)
        state["last_tick"] = now.isoformat(timespec="seconds")
        _save(app, schedules, state)
    done = []
    for s, when in events:
        try:
            result = _execute(app, s)
        except DroidForkError as exc:
            result = f"失敗: {str(exc).splitlines()[0]}"
        app.console.info(f"{when:%m/%d %H:%M} {s.id}（{ACTIONS[s.action]}・{s.target_label()}）: {result}")
        done.append((s, result))
    if done:
        with app.store.lock():
            schedules, state = _load(app)
            by_id = {s.id: r for s, r in done}
            for s in schedules:
                if s.id in by_id:
                    s.last_run, s.last_result = now_iso(), by_id[s.id]
            _save(app, schedules, state)
    return done


# ---- 常駐の設定（systemd のユーザータイマー） ----

def _user_unit_dir(env: dict | None = None) -> Path:
    env = env if env is not None else os.environ
    base = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config")
    return Path(base) / "systemd" / "user"


def unit_files(app: "App") -> dict[str, str]:
    command = [sys.executable, "-m", "droidfork", "--home", str(app.cfg.home), "-q", "schedule", "run-due"]
    service = (
        "[Unit]\n"
        "Description=DroidFork のスケジュール実行\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={shlex.join(command)}\n"
    )
    timer = (
        "[Unit]\n"
        "Description=DroidFork のスケジュール確認（1分ごと）\n"
        "\n"
        "[Timer]\n"
        "OnCalendar=*-*-* *:*:00\n"
        "AccuracySec=5s\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return {f"{UNIT_NAME}.service": service, f"{UNIT_NAME}.timer": timer}


def install_timer(app: "App", unit_dir: Path | None = None) -> Path:
    """1分ごとに run-due を呼ぶユーザータイマーを登録する。"""
    if app.runner.which("systemctl") is None:
        line = f"* * * * * {sys.executable} -m droidfork --home {app.cfg.home} -q schedule run-due"
        raise DroidForkError(
            "systemd が使えない環境です。",
            hint=f"crontab -e で次の1行を追加するか、`droidfork schedule run-due --loop` を常駐させてください:\n  {line}",
        )
    unit_dir = unit_dir or _user_unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, content in unit_files(app).items():
        (unit_dir / name).write_text(content, encoding="utf-8")
    app.runner.run(["systemctl", "--user", "daemon-reload"], timeout=60)
    app.runner.run(["systemctl", "--user", "enable", "--now", f"{UNIT_NAME}.timer"], timeout=60)
    return unit_dir


def uninstall_timer(app: "App", unit_dir: Path | None = None) -> None:
    unit_dir = unit_dir or _user_unit_dir()
    if app.runner.which("systemctl") is not None:
        app.runner.run(["systemctl", "--user", "disable", "--now", f"{UNIT_NAME}.timer"], check=False, timeout=60)
    for name in unit_files(app):
        (unit_dir / name).unlink(missing_ok=True)
    if app.runner.which("systemctl") is not None:
        app.runner.run(["systemctl", "--user", "daemon-reload"], check=False, timeout=60)


def linger_hint() -> str | None:
    user = os.environ.get("USER")
    if user and shutil.which("loginctl"):
        return f"ログインしていないときも動かすには: sudo loginctl enable-linger {user}"
    return None
