"""ブラウザで使う管理画面（droidfork ui）。企画書5章 v1 の GUI にあたる。

- 標準ライブラリの HTTP サーバーで、1枚の HTML（ui.html）と JSON の API を出す。
- 時間のかかる操作（取り込み・雛形作成・起動など）は「ジョブ」として1本のワーカーで順番に実行し、
  進行状況のログを画面に流す。CLI と同じ関数を呼ぶので、できることは CLI と同じ。
- 安全のため、既定は 127.0.0.1 でだけ待ち受け、API にはトークンが必要。
  別のサイトから操作されないよう Host ヘッダーも確かめる（DNS リバインディング対策）。
"""

from __future__ import annotations

import hmac
import io
import json
import queue
import re
import secrets
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import parse_qs, urlparse

from . import __version__
from .capture import add_apks, capture, clone_template
from .hostcheck import is_wsl, run_checks
from .instances import (
    STATE_LABELS, bulk_install, collect_ids, container_states, create_instances, instance_addr,
    open_screens, remove_instances, reset_instances, set_limits, start_instances, stop_instances,
)
from .redroid import adb_address, container_name
from .schedule import ACTIONS as SCHEDULE_ACTIONS
from .schedule import add_schedule, list_schedules, remove_schedule, set_enabled
from .snapshots import create_snapshot, remove_snapshots, restore_snapshot
from .stats import collect_stats
from .store import TEMPLATE_STATE_LABELS
from .template import build_template, remove_template
from .usb import attach as usb_attach
from .usb import list_devices as usb_list
from .util import Console, DroidForkError, now_iso

if TYPE_CHECKING:
    from .app import App

MAX_UPLOAD = 4 * 1024**3
MAX_JSON = 1024**2
KEEP_JOBS = 50
SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9._-]")


# ---- ジョブ ----

class _LogStream(io.TextIOBase):
    """Console の出力をジョブのログ（行のリスト）へ流す。"""

    def __init__(self, job: "Job") -> None:
        self.job = job
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            with self.job.lock:
                self.job.log.append(line)
        return len(text)


@dataclass
class Job:
    id: str
    action: str
    title: str
    params: dict
    status: str = "queued"          # queued / running / done / failed
    created_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    log: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    hint: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def summary(self) -> dict:
        return {"id": self.id, "action": self.action, "title": self.title, "status": self.status,
                "created_at": self.created_at, "finished_at": self.finished_at,
                "error": self.error, "hint": self.hint, "lines": len(self.log)}


def _ids(params: dict) -> list[str]:
    ids = params.get("ids") or []
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise DroidForkError("ids は文字列の配列で指定してください。")
    return ids


def _instances(app: "App", params: dict):
    ids = _ids(params)
    if not ids:
        raise DroidForkError("対象のインスタンスを選んでください。")
    return [app.store.load_instance(i) for i in ids]


def _num(params: dict, key: str, kind: type, default=None):
    value = params.get(key, default)
    if value in (None, ""):
        return default
    try:
        return kind(value)
    except (TypeError, ValueError):
        raise DroidForkError(f"{key} の値が正しくありません: {value!r}") from None


def _start_results(results: dict) -> dict:
    out = {}
    for key, value in results.items():
        if isinstance(value, DroidForkError):
            out[key] = {"ok": False, "text": str(value), "hint": value.hint}
        elif isinstance(value, float):
            out[key] = {"ok": True, "text": f"起動完了（{value:.0f}秒）"}
        else:
            out[key] = {"ok": True, "text": str(value)}
    failed = [k for k, v in out.items() if not v["ok"]]
    if failed:
        raise DroidForkError(f"{len(failed)} 台が失敗しました: " + "; ".join(out[k]["text"] for k in failed))
    return out


def _act_up(app: "App", p: dict):
    name = p.get("template") or None
    if name and app.store.template_exists(name):
        tpl = app.store.load_template(name)
    else:
        tpl = capture(app, serial=p.get("serial") or None, name=name,
                      include=p.get("include") or (), exclude=p.get("exclude") or ())
    if not tpl.sealed:
        tpl = build_template(app, tpl.name, force=tpl.state == "failed")
    created = _act_create(app, {**p, "template": tpl.name, "start": True})
    return created


def _act_create(app: "App", p: dict):
    created = create_instances(
        app, str(p.get("template") or ""), _num(p, "count", int, 1),
        scale=_num(p, "scale", float, 1.0), fps=_num(p, "fps", int),
        cpus=_num(p, "cpus", float), memory=p.get("memory") or None,
    )
    app.console.step(f"{len(created)} 台を作成しました")
    if p.get("start"):
        return _start_results(start_instances(app, created))
    return [i.id for i in created]


def _act_restart(app: "App", p: dict):
    targets = _instances(app, p)
    stop_instances(app, targets)
    return _start_results(start_instances(app, targets))


def _act_install(app: "App", p: dict):
    files = [Path(f) for f in p.get("files") or []]
    uploads = app.cfg.uploads_dir.resolve()
    for f in files:
        if uploads not in f.resolve().parents:
            raise DroidForkError("アップロードしたファイルだけを導入できます。")
    if not files:
        raise DroidForkError("APKを選んでください。")
    paths: list[Path] = files
    if p.get("split") and len(files) > 1:
        group = files[0].parent / f"split-{secrets.token_hex(4)}"
        group.mkdir()
        for f in files:
            f.rename(group / f.name.split("-", 1)[-1])
        paths = [group]
    targets = _instances(app, p) if p.get("ids") else app.store.list_instances()
    rows = bulk_install(app, targets, paths)
    failed = [r for r in rows if not r[2]]
    for inst_id, label, ok, message in rows:
        app.console.info(f"{inst_id}: {label} {'成功' if ok else '失敗 ' + message}")
    if failed:
        raise DroidForkError(f"{len(failed)} 件の導入に失敗しました。")
    return [{"id": r[0], "apk": r[1], "ok": r[2], "message": r[3]} for r in rows]


def _act_template_add_apk(app: "App", p: dict):
    files = [Path(f) for f in p.get("files") or []]
    entries = add_apks(app, str(p.get("name")), files)
    return [e.name for e in entries]


ActionFn = Callable[["App", dict], Any]

ACTIONS: dict[str, tuple[str, ActionFn]] = {
    "up": ("実機から取り込んで起動", _act_up),
    "capture": ("実機から取り込み", lambda app, p: capture(
        app, serial=p.get("serial") or None, name=p.get("name") or None,
        include=p.get("include") or (), exclude=p.get("exclude") or (), android=p.get("android") or None).name),
    "template_build": ("雛形を作成", lambda app, p: build_template(app, str(p.get("name")), force=bool(p.get("force"))).name),
    "template_clone": ("テンプレートを複製", lambda app, p: clone_template(app, str(p.get("source")), str(p.get("name"))).name),
    "template_rm": ("テンプレートを削除", lambda app, p: remove_template(app, str(p.get("name")), force=bool(p.get("force")))),
    "template_add_apk": ("テンプレートにAPKを追加", _act_template_add_apk),
    "create": ("台を作成", _act_create),
    "start": ("起動", lambda app, p: _start_results(start_instances(app, _instances(app, p)))),
    "stop": ("停止", lambda app, p: stop_instances(app, _instances(app, p))),
    "restart": ("再起動", _act_restart),
    "reset": ("リセット", lambda app, p: _start_results(reset_instances(app, _instances(app, p)))),
    "rm": ("削除", lambda app, p: remove_instances(app, _instances(app, p))),
    "limit": ("上限を変更", lambda app, p: set_limits(
        app, _instances(app, p), cpus=_num(p, "cpus", float), memory=p.get("memory") or None,
        clear_cpus=bool(p.get("clear_cpus")), clear_memory=bool(p.get("clear_memory")))),
    "install": ("APKを一括導入", _act_install),
    "screen": ("画面を開く", lambda app, p: open_screens(app, _instances(app, p))),
    "ids": ("識別子を確認", lambda app, p: collect_ids(app, _instances(app, p) if p.get("ids") else app.store.list_instances())),
    "snapshot_create": ("スナップショットを保存", lambda app, p: create_snapshot(
        app, app.store.load_instance(str(p.get("id"))), p.get("name") or None, p.get("note") or None).name),
    "snapshot_restore": ("スナップショットから戻す", lambda app, p: _start_results(restore_snapshot(
        app, app.store.load_snapshot(str(p.get("name"))),
        _instances(app, p) if p.get("ids") else [app.store.load_instance(app.store.load_snapshot(str(p.get("name"))).source)]))),
    "snapshot_rm": ("スナップショットを削除", lambda app, p: remove_snapshots(
        app, [app.store.load_snapshot(str(n)) for n in p.get("names") or []])),
    "schedule_add": ("予定を追加", lambda app, p: asdict(add_schedule(
        app, action=str(p.get("action")), at=str(p.get("at")), days=str(p.get("days") or "daily"),
        template=p.get("template") or None, ids=_ids(p), all_=bool(p.get("all"))))),
    "schedule_rm": ("予定を削除", lambda app, p: remove_schedule(app, str(p.get("id")))),
    "schedule_toggle": ("予定を切り替え", lambda app, p: set_enabled(app, str(p.get("id")), bool(p.get("enabled")))),
    "usb_attach": ("実機をWSLへ接続", lambda app, p: usb_attach(app, str(p.get("busid"))).name),
    "stats": ("実測", lambda app, p: collect_stats(app)),
    "doctor": ("環境チェック", lambda app, p: [asdict(c) for c in run_checks(app)]),
}


class UiState:
    def __init__(self, app_factory: Callable[[Console], "App"], token: str) -> None:
        self.app_factory = app_factory
        self.token = token
        self.jobs: dict[str, Job] = {}
        self.jobs_lock = threading.Lock()
        self.queue: "queue.Queue[Job]" = queue.Queue()
        self.read_app = app_factory(Console(out=io.StringIO(), err=io.StringIO(), quiet=True))
        self.worker = threading.Thread(target=self._work, name="droidfork-ui-worker", daemon=True)
        self.worker.start()

    # ジョブ
    def submit(self, action: str, params: dict) -> Job:
        if action not in ACTIONS:
            raise DroidForkError(f"不明な操作です: {action}")
        job = Job(id=secrets.token_hex(6), action=action, title=ACTIONS[action][0], params=params)
        with self.jobs_lock:
            self.jobs[job.id] = job
            while len(self.jobs) > KEEP_JOBS:
                oldest = next(iter(self.jobs))
                if self.jobs[oldest].status in ("queued", "running"):
                    break
                del self.jobs[oldest]
        self.queue.put(job)
        return job

    def _work(self) -> None:
        while True:
            job = self.queue.get()
            if job is None:  # type: ignore[comparison-overlap]
                return
            self.run_job(job)

    def run_job(self, job: Job) -> None:
        stream = _LogStream(job)
        console = Console(out=stream, err=stream)
        job.status = "running"
        try:
            app = self.app_factory(console)
            job.result = _jsonable(ACTIONS[job.action][1](app, job.params))
            job.status = "done"
        except DroidForkError as exc:
            job.status, job.error, job.hint = "failed", str(exc), exc.hint
        except Exception as exc:  # 予期しない失敗も画面に出す
            job.status, job.error = "failed", f"予期しないエラー: {exc}"
            job.log.extend(traceback.format_exc().splitlines())
        finally:
            job.finished_at = now_iso()
            if stream._buf:
                job.log.append(stream._buf)

    def stop(self) -> None:
        self.queue.put(None)  # type: ignore[arg-type]

    # 状態
    def snapshot_state(self) -> dict:
        app = self.read_app
        templates = app.store.list_templates()
        instances = app.store.list_instances()
        try:
            states: dict[str, str] | None = container_states(app)
            docker_ok = True
        except DroidForkError:
            states, docker_ok = None, False
        try:
            devices = app.adb.devices()
            adb_ok = True
        except DroidForkError:
            devices, adb_ok = [], False
        adb_states = {d.serial: d.state for d in devices}
        managed = {adb_address(app.cfg.adb_bind, i.adb_port) for i in instances}
        counts: dict[str, int] = {}
        rows = []
        for inst in instances:
            counts[inst.template] = counts.get(inst.template, 0) + 1
            state = None if states is None else states.get(container_name(inst.id))
            addr = instance_addr(app, inst)
            rows.append({
                "id": inst.id, "template": inst.template,
                "state": state if states is not None else "unknown",
                "state_label": "不明" if states is None else STATE_LABELS.get(state, state or "停止"),
                "addr": addr, "adb_state": adb_states.get(addr) if state == "running" else None,
                "serialno": inst.serialno, "display": inst.display.label(), "limits": inst.limits_label(),
                "cpus": inst.cpus, "memory": inst.memory, "last_boot_seconds": inst.last_boot_seconds,
            })
        wsl = is_wsl(app.host)
        usb = []
        if wsl:
            try:
                usb = [asdict(d) | {"state_label": d.state_label, "looks_android": d.looks_android} for d in usb_list(app)]
            except DroidForkError:
                usb = []
        with self.jobs_lock:
            jobs = [j.summary() for j in reversed(self.jobs.values())]
        return {
            "version": __version__,
            "host": {"wsl": wsl, "docker": docker_ok, "adb": adb_ok},
            "templates": [{
                "name": t.name, "state": t.state, "state_label": TEMPLATE_STATE_LABELS.get(t.state, t.state),
                "android": t.android_version, "display": t.display.label(), "packages": len(t.packages),
                "failed": sum(1 for v in t.install_results.values() if v != "ok"),
                "instances": counts.get(t.name, 0), "source": t.source.get("model") or ("手動" if t.source.get("manual") else "-"),
                "locale": t.locale, "timezone": t.timezone, "notes": t.notes,
            } for t in templates],
            "instances": rows,
            "devices": [{"serial": d.serial, "state": d.state, "model": d.model}
                        for d in devices if d.serial not in managed and not d.is_emulator and not d.is_local_tcp],
            "usb": usb,
            "snapshots": [asdict(s) for s in app.store.list_snapshots()],
            "schedules": [asdict(s) | {"days_label": s.days_label(), "target_label": s.target_label(),
                                       "action_label": SCHEDULE_ACTIONS.get(s.action, s.action)}
                          for s in list_schedules(app)],
            "jobs": jobs[:20],
        }

    def save_upload(self, name: str, stream: io.BufferedIOBase, length: int) -> dict:
        if length <= 0 or length > MAX_UPLOAD:
            raise DroidForkError("ファイルの大きさが正しくありません（最大 4GB）。")
        safe = SAFE_FILE_RE.sub("_", Path(name).name) or "upload.apk"
        if not safe.lower().endswith(".apk"):
            raise DroidForkError("APK ファイル（.apk）を選んでください。")
        root = self.read_app.cfg.uploads_dir
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{secrets.token_hex(4)}-{safe}"
        remaining = length
        with open(path, "wb") as f:
            while remaining > 0:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
        if remaining:
            path.unlink(missing_ok=True)
            raise DroidForkError("アップロードが途中で切れました。")
        return {"path": str(path), "name": safe, "size": length}


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))


# ---- HTTP ----

def load_page() -> str:
    return resources.files("droidfork").joinpath("ui.html").read_text(encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    server: "UiServer"
    server_version = "DroidFork"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # 標準エラーへのアクセスログを出さない
        return

    # 共通
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str, hint: str | None = None) -> None:
        self._json(status, {"ok": False, "error": message, "hint": hint})

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in self.server.allowed_hosts or self.server.any_host

    def _token_ok(self) -> bool:
        given = self.headers.get("X-DroidFork-Token") or ""
        return hmac.compare_digest(given.encode(), self.server.state.token.encode())

    def _guard(self, api: bool) -> bool:
        if not self._host_ok():
            self._error(HTTPStatus.FORBIDDEN, "このアドレスからは使えません。")
            return False
        if api and not self._token_ok():
            self._error(HTTPStatus.UNAUTHORIZED, "トークンが正しくありません。",
                        "droidfork ui を起動したときに表示された URL から開き直してください。")
            return False
        return True

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_JSON:
            raise DroidForkError("リクエストが大きすぎます。")
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise DroidForkError("Content-Type は application/json にしてください。")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise DroidForkError("JSON オブジェクトを送ってください。")
        return data

    # GET
    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            if self._guard(api=False):
                csp = ("default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                       "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'")
                self._send(HTTPStatus.OK, load_page().encode("utf-8"), "text/html; charset=utf-8",
                           {"Content-Security-Policy": csp})
            return
        if url.path == "/favicon.ico":
            self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
            return
        if not self._guard(api=True):
            return
        state = self.server.state
        try:
            if url.path == "/api/state":
                self._json(HTTPStatus.OK, {"ok": True, **state.snapshot_state()})
            elif url.path == "/api/jobs":
                with state.jobs_lock:
                    jobs = [j.summary() for j in reversed(state.jobs.values())]
                self._json(HTTPStatus.OK, {"ok": True, "jobs": jobs})
            elif url.path.startswith("/api/jobs/"):
                job = state.jobs.get(url.path.rsplit("/", 1)[-1])
                if job is None:
                    self._error(HTTPStatus.NOT_FOUND, "ジョブが見つかりません。")
                    return
                since = int((parse_qs(url.query).get("since") or ["0"])[0])
                with job.lock:
                    lines = job.log[since:]
                self._json(HTTPStatus.OK, {"ok": True, "job": job.summary(), "log": lines, "next": since + len(lines),
                                           "result": job.result if job.status == "done" else None})
            else:
                self._error(HTTPStatus.NOT_FOUND, "見つかりません。")
        except DroidForkError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), exc.hint)

    # POST
    def do_POST(self) -> None:
        url = urlparse(self.path)
        if not self._guard(api=True):
            return
        state = self.server.state
        try:
            if url.path == "/api/jobs":
                data = self._read_json()
                params = data.get("params") or {}
                if not isinstance(params, dict):
                    raise DroidForkError("params はオブジェクトで指定してください。")
                job = state.submit(str(data.get("action")), params)
                self._json(HTTPStatus.ACCEPTED, {"ok": True, "job": job.summary()})
            elif url.path == "/api/upload":
                name = (parse_qs(url.query).get("name") or ["upload.apk"])[0]
                length = int(self.headers.get("Content-Length") or 0)
                self._json(HTTPStatus.OK, {"ok": True, **state.save_upload(name, self.rfile, length)})
            else:
                self._error(HTTPStatus.NOT_FOUND, "見つかりません。")
        except DroidForkError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc), exc.hint)
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, f"リクエストを読めません: {exc}")


class UiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int, state: UiState) -> None:
        super().__init__((host, port), Handler)
        self.state = state
        actual_port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{actual_port}", f"localhost:{actual_port}", f"[::1]:{actual_port}"}
        # 明示的に外へ公開したとき（0.0.0.0 など）は、どのホスト名でも受け付ける（トークンは必須のまま）
        self.any_host = host not in ("127.0.0.1", "localhost", "::1")
        if not self.any_host:
            self.allowed_hosts.add(f"{host}:{actual_port}")

    @property
    def port(self) -> int:
        return int(self.server_address[1])


def make_server(app_factory: Callable[[Console], "App"], host: str = "127.0.0.1", port: int = 8765,
                token: str | None = None) -> UiServer:
    state = UiState(app_factory, token or secrets.token_urlsafe(18))
    return UiServer(host, port, state)


def serve(server: UiServer, console: Console) -> None:
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        console.step("管理画面を終了します")
    finally:
        server.state.stop()
        server.server_close()


def wait_jobs(state: UiState, timeout: float = 10.0) -> None:
    """テスト用: キューのジョブが終わるまで待つ。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with state.jobs_lock:
            busy = any(j.status in ("queued", "running") for j in state.jobs.values())
        if not busy:
            return
        time.sleep(0.02)
    raise TimeoutError("ジョブが終わりませんでした")
