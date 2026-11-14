"""管理画面（droidfork ui）の API を、偽の adb/docker の上で動かして確かめる。"""

import json
import threading
import unittest
import urllib.error
import urllib.request

from droidfork.redroid import container_name
from droidfork.ui import make_server, wait_jobs

from tests.test_flow import FlowTestCase


class UiTest(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.app.with_console, "127.0.0.1", 0, token="test-token")
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.state.stop()
        self.server.server_close()
        super().tearDown()

    def request(self, path, data=None, *, token="test-token", headers=None, raw=None, method=None):
        hdrs = dict(headers or {})
        if token is not None:
            hdrs["X-DroidFork-Token"] = token
        body = raw
        if data is not None:
            body = json.dumps(data).encode()
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, res.headers, res.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def api(self, path, data=None, **kw):
        status, _, body = self.request(path, data, **kw)
        return status, json.loads(body)

    def job(self, action, /, **params):
        status, data = self.api("/api/jobs", {"action": action, "params": params})
        self.assertEqual(status, 202, data)
        wait_jobs(self.server.state)
        status, data = self.api(f"/api/jobs/{data['job']['id']}")
        self.assertEqual(status, 200)
        return data

    def test_page_and_security(self):
        status, headers, body = self.request("/", token=None)
        self.assertEqual(status, 200)
        self.assertIn("DroidFork", body.decode())
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        status, data = self.api("/api/state", token=None)
        self.assertEqual(status, 401)
        status, data = self.api("/api/state", token="wrong")
        self.assertEqual(status, 401)
        status, data = self.api("/api/state", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 403, "DNS リバインディング対策")
        status, data = self.api("/api/jobs", raw=b'{"action":"stats"}', headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 400, "JSON 以外は受け付けない")
        status, data = self.api("/api/jobs", {"action": "rm -rf"})
        self.assertEqual(status, 400)

    def test_state_and_lifecycle(self):
        self.built()
        status, data = self.api("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(data["templates"][0]["name"], "shop")
        self.assertEqual(data["templates"][0]["failed"], 1)
        self.assertEqual([d["serial"] for d in data["devices"]], ["R5CT10ABCDE"])
        self.assertTrue(data["host"]["docker"])

        result = self.job("create", template="shop", count="2", scale="0.5", memory="2g", start=True)
        self.assertEqual(result["job"]["status"], "done", result)
        self.assertTrue(all(v["ok"] for v in result["result"].values()))
        self.assertTrue(any("2 台を作成" in line for line in result["log"]))
        _, data = self.api("/api/state")
        self.assertEqual([i["state"] for i in data["instances"]], ["running", "running"])
        self.assertEqual(data["instances"][0]["limits"], "2g")

        ids = self.job("ids")["result"]
        self.assertEqual(len({r["android_id"] for r in ids}), 2)

        self.assertEqual(self.job("snapshot_create", id="shop-01", note="ui")["job"]["status"], "done")
        _, data = self.api("/api/state")
        self.assertEqual(data["snapshots"][0]["note"], "ui")

        self.assertEqual(self.job("schedule_add", at="09:00", action="start", days="weekdays", template="shop")["job"]["status"], "done")
        _, data = self.api("/api/state")
        self.assertEqual(data["schedules"][0]["days_label"], "平日")

        stats = self.job("stats")["result"]
        self.assertEqual(stats["summary"]["running"], 2)

        self.assertEqual(self.job("stop", ids=["shop-02"])["job"]["status"], "done")
        self.assertNotIn(container_name("shop-02"), self.world.containers)
        self.assertEqual(self.job("rm", ids=["shop-01", "shop-02"])["job"]["status"], "done")
        _, data = self.api("/api/state")
        self.assertEqual(data["instances"], [])

    def test_upload_and_install(self):
        self.built()
        self.run_cli("create", "shop", "-n", "2")
        self.run_cli("start", "--all")
        status, up1 = self.api("/api/upload?name=base.apk", raw=b"apk-base", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 200, up1)
        _, up2 = self.api("/api/upload?name=split_config.ja.apk", raw=b"apk-split", headers={"Content-Type": "application/octet-stream"})
        result = self.job("install", files=[up1["path"], up2["path"]], split=True)
        self.assertEqual(result["job"]["status"], "done", result)
        self.assertEqual(len(result["result"]), 2)
        installs = [c for c in self.world.adb_calls() if "install-multiple" in c and "split-" in " ".join(c)]
        self.assertEqual(len(installs), 2, "分割APKとして全台にまとめて導入")

        status, data = self.api("/api/upload?name=evil.sh", raw=b"x", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 400)
        outside = self.tmp / "outside.apk"
        outside.write_text("x")
        result = self.job("install", files=[str(outside)])
        self.assertEqual(result["job"]["status"], "failed")
        self.assertIn("アップロードした", result["job"]["error"])

    def test_failed_job_reports_error_and_hint(self):
        result = self.job("create", template="nope", count=1)
        self.assertEqual(result["job"]["status"], "failed")
        self.assertIn("見つかりません", result["job"]["error"])
        self.assertIn("template list", result["job"]["hint"])

    def test_capture_and_build_from_ui(self):
        result = self.job("capture", name="ui-tpl", include=["com.example.shop"])
        self.assertEqual(result["job"]["status"], "done", result)
        self.assertEqual(result["result"], "ui-tpl")
        result = self.job("template_build", name="ui-tpl")
        self.assertEqual(result["job"]["status"], "done", result)
        _, data = self.api("/api/state")
        self.assertEqual(data["templates"][0]["state"], "sealed")


if __name__ == "__main__":
    unittest.main()
