"""v2 の機能（上限・スナップショット・テンプレートの複数管理・スケジュール・WSLのUSB）のテスト。"""

import json
import unittest
from datetime import datetime, timedelta

from droidfork.redroid import container_name, diff_volume_name
from droidfork.schedule import Schedule, due_events, parse_days, parse_time, run_due, unit_files
from droidfork.snapshots import snapshot_volume_name
from droidfork.usb import parse_usbipd_list
from droidfork.util import DroidForkError

from tests.fakes import SSAID_FILE, err
from tests.test_flow import FlowTestCase


class LimitTest(FlowTestCase):
    def test_create_with_limits_and_change_live(self):
        self.built()
        code, text = self.run_cli("create", "shop", "-n", "2", "--cpus", "1.5", "--memory", "2G")
        self.assertEqual(code, 0, err(self.app))
        self.assertIn("1.5CPU/2g", text)
        self.run_cli("start", "--all")
        c = self.world.containers[container_name("shop-01")]
        self.assertEqual((c.cpus, c.memory), ("1.5", "2g"))

        code, text = self.run_cli("limit", "shop-01", "--cpus", "2", "--memory", "3g")
        self.assertEqual(code, 0, err(self.app))
        self.assertIn("反映しました", text)
        self.assertEqual((c.cpus, c.memory), ("2", "3g"))
        inst = json.loads((self.home / "instances/shop-01.json").read_text())
        self.assertEqual((inst["cpus"], inst["memory"]), (2.0, "3g"))

        code, text = self.run_cli("limit", "shop-02", "--no-memory")
        self.assertIn("次回の起動から反映", text)
        self.assertIsNone(json.loads((self.home / "instances/shop-02.json").read_text())["memory"])

        code, text = self.run_cli("limit")
        self.assertIn("shop-01  2", text)

    def test_bad_limits(self):
        self.built()
        for args in (["--memory", "lots"], ["--cpus", "0"]):
            code, _ = self.run_cli("create", "shop", "-n", "1", *args)
            self.assertEqual(code, 1, args)
        code, _ = self.run_cli("create", "shop", "-n", "1", "--memory", "256m")
        self.assertEqual(code, 0)
        self.assertIn("小さすぎ", err(self.app))


class SnapshotTest(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.built()
        self.run_cli("create", "shop", "-n", "2")
        self.run_cli("start", "--all")
        c = self.world.containers[container_name("shop-01")]
        c.set("app-data/login", "token-1")

    def android_id(self, iid):
        _, text = self.run_cli("ids", iid, "--json")
        return json.loads(text)[0]["android_id"]

    def test_create_and_restore_same_instance(self):
        before_id = self.android_id("shop-01")
        code, text = self.run_cli("snapshot", "create", "shop-01", "--name", "logged-in", "--note", "ログイン済み")
        self.assertEqual(code, 0, err(self.app))
        self.assertIn(snapshot_volume_name("logged-in"), self.world.volumes)
        self.assertEqual(self.world.containers[container_name("shop-01")].state, "running", "保存後に起動し直す")

        self.run_cli("reset", "shop-01", "-y")
        self.assertIsNone(self.world.containers[container_name("shop-01")].get("app-data/login"))

        code, _ = self.run_cli("snapshot", "restore", "logged-in", "-y")
        self.assertEqual(code, 0, err(self.app))
        c = self.world.containers[container_name("shop-01")]
        self.assertEqual(c.get("app-data/login"), "token-1")
        self.assertEqual(self.android_id("shop-01"), before_id, "同じ台に戻すと Android ID も元どおり")

        code, text = self.run_cli("snapshot", "list")
        self.assertIn("logged-in", text)
        self.assertIn("ログイン済み", text)

    def test_restore_to_other_instance_regenerates_android_id(self):
        self.run_cli("snapshot", "create", "shop-01", "--name", "s1")
        code, text = self.run_cli("snapshot", "restore", "s1", "shop-02", "-y")
        self.assertEqual(code, 0, err(self.app))
        c2 = self.world.containers[container_name("shop-02")]
        self.assertEqual(c2.get("app-data/login"), "token-1", "アプリのデータは引き継ぐ")
        code, text = self.run_cli("ids")
        self.assertEqual(code, 0, text)
        self.assertNotIn("重複", text)
        diff2 = self.world.volumes[diff_volume_name("shop-02")]["data"]
        self.assertNotEqual(diff2.get(SSAID_FILE), self.world.volumes[diff_volume_name("shop-01")]["data"].get(SSAID_FILE))

    def test_restore_rejects_other_template(self):
        self.run_cli("snapshot", "create", "shop-01", "--name", "s1")
        self.run_cli("template", "clone", "shop", "other")
        self.run_cli("template", "build", "other")
        self.run_cli("create", "other", "-n", "1")
        code, _ = self.run_cli("snapshot", "restore", "s1", "other-01", "-y")
        self.assertEqual(code, 1)
        self.assertIn("同じテンプレート", err(self.app))

    def test_rm_and_template_rm(self):
        self.run_cli("snapshot", "create", "shop-01", "--name", "s1")
        code, _ = self.run_cli("template", "rm", "shop", "-y")
        self.assertEqual(code, 1)
        self.assertIn("スナップショットが 1 個", err(self.app))
        code, _ = self.run_cli("snapshot", "rm", "s1", "-y")
        self.assertEqual(code, 0)
        self.assertNotIn(snapshot_volume_name("s1"), self.world.volumes)
        self.run_cli("snapshot", "create", "shop-02", "--name", "s2")
        code, _ = self.run_cli("template", "rm", "shop", "-y", "--force")
        self.assertEqual(code, 0, err(self.app))
        self.assertEqual(self.world.volumes, {})
        self.assertFalse(any((self.home / "snapshots").glob("*.json")))


class TemplateManagementTest(FlowTestCase):
    def test_clone_add_and_remove_apk(self):
        self.built()
        code, _ = self.run_cli("template", "clone", "shop", "shop-v2")
        self.assertEqual(code, 0, err(self.app))
        data = json.loads((self.home / "templates/shop-v2/template.json").read_text())
        self.assertEqual(data["state"], "captured")
        self.assertEqual(len(data["packages"]), 4)
        self.assertTrue((self.home / "templates/shop-v2/apks/com.example.split/base.apk").exists())

        apk = self.tmp / "extra.apk"
        apk.write_text("x")
        code, _ = self.run_cli("template", "add-apk", "shop-v2", str(apk))
        self.assertEqual(code, 0, err(self.app))
        code, _ = self.run_cli("template", "rm-apk", "shop-v2", "com.example.armonly")
        self.assertEqual(code, 0, err(self.app))
        code, _ = self.run_cli("template", "build", "shop-v2")
        self.assertEqual(code, 0, err(self.app))
        data = json.loads((self.home / "templates/shop-v2/template.json").read_text())
        self.assertEqual(data["install_results"].get("extra"), "ok")
        self.assertNotIn("com.example.armonly", data["install_results"])
        self.assertTrue(all(v == "ok" for v in data["install_results"].values()))

    def test_cannot_edit_template_in_use(self):
        self.built()
        self.run_cli("create", "shop", "-n", "1")
        apk = self.tmp / "extra.apk"
        apk.write_text("x")
        code, _ = self.run_cli("template", "add-apk", "shop", str(apk))
        self.assertEqual(code, 1)
        self.assertIn("template clone", err(self.app))

    def test_edit_sealed_template_without_instances_requires_rebuild(self):
        self.built()
        apk = self.tmp / "extra.apk"
        apk.write_text("x")
        self.run_cli("template", "add-apk", "shop", str(apk))
        code, _ = self.run_cli("create", "shop", "-n", "1")
        self.assertEqual(code, 1)
        self.assertIn("template build", err(self.app))


class ScheduleParseTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_time("9:05"), "09:05")
        with self.assertRaises(DroidForkError):
            parse_time("25:00")
        self.assertEqual(parse_days("weekdays"), [0, 1, 2, 3, 4])
        self.assertEqual(parse_days("mon-fri"), [0, 1, 2, 3, 4])
        self.assertEqual(parse_days("fri-mon"), [0, 4, 5, 6])
        self.assertEqual(parse_days("mon,wed,sun"), [0, 2, 6])
        self.assertEqual(parse_days("平日"), [0, 1, 2, 3, 4])
        with self.assertRaises(DroidForkError):
            parse_days("someday")

    def test_due_events(self):
        s = Schedule(id="s1", action="start", at="09:00", days=[0, 1, 2, 3, 4], all=True)
        monday = datetime(2026, 11, 16, 9, 0, 30)  # 月曜
        self.assertEqual(len(due_events([s], monday - timedelta(minutes=1), monday)), 1)
        self.assertEqual(due_events([s], monday, monday + timedelta(minutes=1)), [], "同じ予定を2回実行しない")
        saturday = datetime(2026, 11, 21, 9, 0, 30)
        self.assertEqual(due_events([s], saturday - timedelta(minutes=1), saturday), [], "土曜は対象外")
        s.enabled = False
        self.assertEqual(due_events([s], monday - timedelta(minutes=1), monday), [])


class ScheduleTest(FlowTestCase):
    def test_add_run_and_install(self):
        self.built()
        self.run_cli("create", "shop", "-n", "2")
        code, text = self.run_cli("schedule", "add", "--at", "09:00", "--action", "start", "--days", "weekdays", "-t", "shop")
        self.assertEqual(code, 0, err(self.app))
        self.assertIn("schedule install", text)
        self.run_cli("schedule", "add", "--at", "18:30", "--action", "stop", "--all")
        code, text = self.run_cli("schedule", "list")
        self.assertIn("平日", text)
        self.assertIn("テンプレート shop", text)

        monday_morning = datetime(2026, 11, 16, 9, 0, 20)
        run_due(self.app, now=monday_morning - timedelta(minutes=2))  # 前回の確認
        run_due(self.app, now=monday_morning)
        self.assertEqual(self.world.containers[container_name("shop-01")].state, "running")
        self.assertEqual(self.world.containers[container_name("shop-02")].state, "running")
        run_due(self.app, now=monday_morning + timedelta(minutes=1))  # もう一度は実行しない
        self.assertEqual(len([c for c in self.world.docker_calls("run") if "droidfork-shop-01" in c]), 1)

        # PCがスリープしていて 18:30 の停止から20分遅れて確認した → 実行しない
        run_due(self.app, now=datetime(2026, 11, 16, 18, 50, 0))
        self.assertEqual(self.world.containers[container_name("shop-01")].state, "running",
                         "15分より前に過ぎた予定は実行しない")

        _, text = self.run_cli("schedule", "list")
        self.assertIn("2 台を起動", text)

        self.run_cli("schedule", "disable", "s1")
        self.run_cli("schedule", "rm", "s2")
        _, text = self.run_cli("schedule", "list")
        self.assertIn("無効", text)
        self.assertNotIn("s2", text)

        self.world.binaries.add("systemctl")
        import droidfork.schedule as sched
        unit_dir = self.tmp / "units"
        orig = sched._user_unit_dir
        sched._user_unit_dir = lambda env=None: unit_dir
        try:
            code, text = self.run_cli("schedule", "install")
        finally:
            sched._user_unit_dir = orig
        self.assertEqual(code, 0, err(self.app))
        self.assertTrue((unit_dir / "droidfork-scheduler.timer").exists())
        self.assertIn(["systemctl", "--user", "enable", "--now", "droidfork-scheduler.timer"], self.world.calls)

    def test_stop_event_runs(self):
        self.built()
        self.run_cli("create", "shop", "-n", "1")
        self.run_cli("start", "--all")
        self.run_cli("schedule", "add", "--at", "18:30", "--action", "stop", "shop-01")
        evening = datetime(2026, 11, 16, 18, 30, 5)
        run_due(self.app, now=evening - timedelta(minutes=1))
        run_due(self.app, now=evening)
        self.assertNotIn(container_name("shop-01"), self.world.containers)

    def test_unit_files(self):
        units = unit_files(self.app)
        self.assertIn("schedule run-due", units["droidfork-scheduler.service"])
        self.assertIn(str(self.home), units["droidfork-scheduler.service"])
        self.assertIn("OnCalendar=*-*-* *:*:00", units["droidfork-scheduler.timer"])

    def test_add_validation(self):
        self.built()
        code, _ = self.run_cli("schedule", "add", "--at", "09:00", "--action", "start")
        self.assertEqual(code, 1)
        code, _ = self.run_cli("schedule", "add", "--at", "09:00", "--action", "start", "nope-01")
        self.assertEqual(code, 1)

    def test_no_systemd(self):
        code, _ = self.run_cli("schedule", "install")
        self.assertEqual(code, 1)
        self.assertIn("crontab", err(self.app))


class UsbTest(FlowTestCase):
    def test_parse(self):
        text = ("Connected:\n"
                "BUSID  VID:PID    DEVICE                                                        STATE\n"
                "1-4    18d1:4ee7  Pixel 7a                                                      Not shared\n"
                "2-1    04e8:6860  SAMSUNG Mobile USB Modem, SAMSUNG Android ADB Interface       Attached\n"
                "\nPersisted:\nGUID                                  DEVICE\n")
        devices = parse_usbipd_list(text)
        self.assertEqual([d.busid for d in devices], ["1-4", "2-1"])
        self.assertTrue(devices[1].looks_android)
        self.assertEqual(devices[1].state_label, "WSLに接続中")

    def test_only_on_wsl(self):
        code, _ = self.run_cli("usb", "list")
        self.assertEqual(code, 1)
        self.assertIn("WSL2", err(self.app))

    def test_attach_binds_with_uac_first(self):
        self.host.files["/proc/version"] = "Linux version 6.6.87.2-microsoft-standard-WSL2"
        self.world.binaries.update({"usbipd.exe", "powershell.exe"})
        code, text = self.run_cli("usb", "list")
        self.assertEqual(code, 0, err(self.app))
        self.assertIn("Pixel 7a", text)
        self.assertIn("未共有", text)
        code, text = self.run_cli("usb", "attach", "1-4")
        self.assertEqual(code, 0, err(self.app))
        self.assertTrue(any(c[0] == "powershell.exe" for c in self.world.calls), "初回は権限確認を出して共有")
        self.assertEqual(self.world.usb_devices[0][3], "Attached - Ubuntu")
        code, text = self.run_cli("doctor")
        self.assertIn("usbipd-win", text)


if __name__ == "__main__":
    unittest.main()
