"""取り込み → 雛形作成 → 複製 → 起動 → 確認 → リセット → 削除 の一連の流れを偽物の adb/docker で検証する。"""

import json
import tempfile
import unittest
from pathlib import Path

from droidfork.cli import main
from droidfork.redroid import base_volume_name, build_container_name, container_name, diff_volume_name

from tests.fakes import IMAGE_ID, IMAGE_REF, FakeHost, FakeWorld, err, make_app, out


class FlowTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.world = FakeWorld()
        self.host = FakeHost()
        self.app = make_app(self.home, self.world, self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv, answers=None):
        if answers is not None:
            self.app.ask = lambda prompt, a=list(answers): a.pop(0) if a else None
        self.app.console.out.seek(0)
        self.app.console.out.truncate()
        code = main(list(argv), app=self.app)
        return code, out(self.app)

    def captured(self, name="shop"):
        code, _ = self.run_cli("capture", "--name", name)
        self.assertEqual(code, 0, err(self.app))

    def built(self, name="shop"):
        self.captured(name)
        code, _ = self.run_cli("template", "build", name)
        self.assertEqual(code, 0, err(self.app))


class CaptureTest(FlowTestCase):
    def test_capture_reads_profile_and_pulls_apks(self):
        self.captured()
        data = json.loads((self.home / "templates/shop/template.json").read_text())
        self.assertEqual(data["state"], "captured")
        self.assertEqual(data["android_version"], "14.0.0")
        # Override の DPI を優先する
        self.assertEqual(data["display"], {"width": 1080, "height": 2340, "dpi": 420, "fps": 30})
        self.assertEqual((data["locale"], data["timezone"]), ("ja-JP", "Asia/Tokyo"))
        self.assertEqual(data["settings"], {"system": {"font_scale": "1.1", "time_12_24": "24"}})
        pkgs = {p["name"]: p for p in data["packages"]}
        self.assertEqual(set(pkgs), {"com.example.shop", "com.example.split", "com.example.armonly", "jp.co.sample.tool"})
        self.assertEqual(pkgs["com.example.split"]["files"], ["base.apk", "split_config.arm64_v8a.apk", "split_config.ja.apk"])
        self.assertEqual(pkgs["com.example.shop"]["version_name"], "1.2.3")
        self.assertTrue((self.home / "templates/shop/apks/com.example.split/split_config.ja.apk").exists())
        # 実機のシリアル番号は保存しない（企画書8章）
        self.assertNotIn(self.world.phone.serial, json.dumps(data))
        self.assertEqual(data["source"]["model"], "SM-S911C")

    def test_include_exclude(self):
        code, _ = self.run_cli("capture", "--name", "x", "--include", "com.example.*", "--exclude", "*.armonly")
        self.assertEqual(code, 0)
        data = json.loads((self.home / "templates/x/template.json").read_text())
        self.assertEqual(sorted(p["name"] for p in data["packages"]), ["com.example.shop", "com.example.split"])

    def test_default_name_from_model(self):
        self.run_cli("capture")
        self.run_cli("capture")
        self.assertTrue((self.home / "templates/sm-s911c/template.json").exists())
        self.assertTrue((self.home / "templates/sm-s911c-2/template.json").exists())

    def test_no_device(self):
        self.world.phone = None
        code, _ = self.run_cli("capture")
        self.assertEqual(code, 1)
        self.assertIn("実機が見つかりません", err(self.app))
        self.assertIn("USBデバッグ", err(self.app))
        templates = self.home / "templates"
        self.assertFalse(templates.exists() and any(templates.iterdir()), "半端な雛形を残さない")

    def test_unauthorized(self):
        self.world.phone.state = "unauthorized"
        code, _ = self.run_cli("capture")
        self.assertEqual(code, 1)
        self.assertIn("許可", err(self.app))

    def test_old_android_falls_back_with_note(self):
        self.world.phone.props.update({"ro.build.version.release": "7.1.2", "ro.build.version.sdk": "25"})
        self.captured()
        data = json.loads((self.home / "templates/shop/template.json").read_text())
        self.assertEqual(data["android_version"], "8.1.0")
        self.assertTrue(any("8.1" in n for n in data["notes"]))


class BuildTest(FlowTestCase):
    def test_build_creates_sealed_base(self):
        self.built()
        tpl = json.loads((self.home / "templates/shop/template.json").read_text())
        self.assertEqual(tpl["state"], "sealed")
        self.assertEqual((tpl["image"], tpl["image_id"]), (IMAGE_REF, IMAGE_ID))
        # ARM専用アプリだけ失敗として記録される
        self.assertEqual(tpl["install_results"]["com.example.shop"], "ok")
        self.assertIn("INSTALL_FAILED_NO_MATCHING_ABIS", tpl["install_results"]["com.example.armonly"])

        run = self.world.docker_calls("run")[0]
        self.assertIn("ro.secure=0", run)                    # 雛形作成時だけ root の adb
        self.assertIn(f"{base_volume_name('shop')}:/data", run)
        self.assertIn("androidboot.redroid_width=1080", run)
        self.assertIn("androidboot.use_memfd=true", run)      # /dev/ashmem が無いホスト
        self.assertTrue(any(a.startswith("127.0.0.1:") for a in run))
        # 分割APKはまとめて導入
        multi = [c for c in self.world.adb_calls() if "install-multiple" in c]
        self.assertEqual(len(multi), 1)
        self.assertEqual(len([a for a in multi[0] if a.endswith(".apk")]), 3)

        base = self.world.volumes[base_volume_name("shop")]["data"]
        self.assertEqual(base["prop/persist.sys.locale"], "ja-JP")
        self.assertEqual(base["prop/persist.sys.timezone"], "Asia/Tokyo")
        self.assertEqual(base["settings/system/font_scale"], "1.1")
        self.assertIn("pkg/com.example.split", base)
        # 封印: 端末固有の値が共有層に残っていない
        self.assertNotIn("settings/secure/android_id", base)
        self.assertNotIn("file:/data/system/users/0/settings_ssaid.xml", base)
        self.assertNotIn("file:/data/system/entropy.dat", base)
        # 作業用コンテナは片付けられている
        self.assertNotIn(build_container_name("shop"), self.world.containers)

    def test_build_failure_cleans_up_and_marks_failed(self):
        self.captured()
        self.world.crash_on_start.add(build_container_name("shop"))
        code, _ = self.run_cli("template", "build", "shop")
        self.assertEqual(code, 1)
        self.assertIn("コンテナが停止しました", err(self.app))
        self.assertIn("doctor", err(self.app))
        tpl = json.loads((self.home / "templates/shop/template.json").read_text())
        self.assertEqual(tpl["state"], "failed")
        self.assertNotIn(build_container_name("shop"), self.world.containers)
        # 失敗した雛形からは複製できない
        code, _ = self.run_cli("create", "shop", "-n", "1")
        self.assertEqual(code, 1)

    def test_cannot_rebuild_while_instances_exist(self):
        self.built()
        self.run_cli("create", "shop", "-n", "2")
        code, _ = self.run_cli("template", "build", "shop", "--force")
        self.assertEqual(code, 1)
        self.assertIn("作り直せません", err(self.app))

    def test_manual_template(self):
        apk = self.tmp / "tool.apk"
        apk.write_text("apk")
        split = self.tmp / "game"
        split.mkdir()
        (split / "base.apk").write_text("a")
        (split / "split_config.x86_64.apk").write_text("b")
        code, _ = self.run_cli("template", "new", "lab", "--android", "13", "--size", "720x1280",
                               "--locale", "ja-JP", "--apk", str(apk), "--apk", str(split))
        self.assertEqual(code, 0, err(self.app))
        data = json.loads((self.home / "templates/lab/template.json").read_text())
        self.assertEqual(data["android_version"], "13.0.0")
        self.assertEqual([p["name"] for p in data["packages"]], ["tool", "game"])
        self.assertEqual(data["packages"][1]["files"], ["base.apk", "split_config.x86_64.apk"])


class InstanceTest(FlowTestCase):
    def test_create_is_instant_and_unique(self):
        self.built()
        runs_before = len(self.world.docker_calls("run"))
        code, text = self.run_cli("create", "shop", "-n", "3", "--scale", "0.5")
        self.assertEqual(code, 0, err(self.app))
        self.assertEqual(len(self.world.docker_calls("run")), runs_before, "作成時は起動しない")
        insts = [json.loads(p.read_text()) for p in sorted((self.home / "instances").glob("*.json"))]
        self.assertEqual([i["id"] for i in insts], ["shop-01", "shop-02", "shop-03"])
        self.assertEqual(len({i["adb_port"] for i in insts}), 3)
        self.assertEqual(len({i["serialno"] for i in insts}), 3)
        self.assertEqual(len({i["mac"] for i in insts}), 3)
        self.assertEqual(insts[0]["display"], {"width": 540, "height": 1170, "dpi": 210, "fps": 30})
        for i in insts:
            self.assertEqual(self.world.volumes[diff_volume_name(i["id"])]["data"], {}, "差分層は空から始まる")
        self.assertIn("shop-03", text)
        # 続けて作ると番号が続く
        self.run_cli("create", "shop", "-n", "1")
        self.assertTrue((self.home / "instances/shop-04.json").exists())

    def test_port_in_use_is_skipped(self):
        self.built()
        self.host.busy_ports.add(15555)
        self.run_cli("create", "shop", "-n", "1")
        inst = json.loads((self.home / "instances/shop-01.json").read_text())
        self.assertEqual(inst["adb_port"], 15556)

    def test_start_uses_shared_base_and_private_diff(self):
        self.built()
        self.run_cli("create", "shop", "-n", "3")
        code, text = self.run_cli("start", "--all")
        self.assertEqual(code, 0, err(self.app))
        self.assertIn("起動完了", text)
        for n in (1, 2, 3):
            iid = f"shop-0{n}"
            c = self.world.containers[container_name(iid)]
            self.assertEqual(c.state, "running")
            self.assertEqual(c.image, IMAGE_ID, "雛形と同じイメージ（ID固定）")
            self.assertIn((base_volume_name("shop"), "/data-base", True), c.mounts)
            self.assertIn((diff_volume_name(iid), "/data-diff", False), c.mounts)
            self.assertEqual(c.bind, "127.0.0.1")
            self.assertNotIn("ro.secure=0", c.boot_args)
            self.assertIn("ro.product.model=DroidFork-Virtual", c.boot_args)
            self.assertIn(c.addr, self.world.connected, "adb に接続済み")
            # 雛形のアプリと設定がそのまま見える
            self.assertTrue(c.get("pkg/com.example.shop"))
            self.assertEqual(c.get("prop/persist.sys.locale"), "ja-JP")
        inst = json.loads((self.home / "instances/shop-01.json").read_text())
        self.assertIsNotNone(inst["last_boot_seconds"])

        code, text = self.run_cli("list")
        self.assertIn("起動中", text)
        self.assertIn("127.0.0.1:15557", text)

        code, text = self.run_cli("devices")
        self.assertIn("DroidFork（shop-02）", text)
        self.assertIn("実機（USB）", text)

    def test_ids_are_unique_after_seal(self):
        self.built()
        self.run_cli("create", "shop", "-n", "3")
        self.run_cli("start", "--all")
        code, text = self.run_cli("ids", "--json")
        self.assertEqual(code, 0, err(self.app))
        rows = json.loads(text)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["android_id"] for r in rows}), 3)
        self.assertEqual(len({r["serialno"] for r in rows}), 3)
        self.assertTrue(all(r["model"] == "DroidFork-Virtual" for r in rows))
        self.assertTrue(all(not r["duplicates"] for r in rows))

    def test_ids_detects_shared_android_id_when_seal_is_skipped(self):
        from unittest import mock
        self.captured()
        with mock.patch("droidfork.template.seal"):
            code, _ = self.run_cli("template", "build", "shop")
        self.assertEqual(code, 0)
        self.run_cli("create", "shop", "-n", "2")
        self.run_cli("start", "--all")
        code, text = self.run_cli("ids")
        self.assertEqual(code, 1)
        self.assertIn("重複: android_id", text)

    def test_seal_warns_when_android_id_remains(self):
        self.captured()
        self.world.seal_effective = False
        code, _ = self.run_cli("template", "build", "shop")
        self.assertEqual(code, 0)
        self.assertIn("Android ID が雛形の設定に残っている", err(self.app))

    def test_reset_discards_diff_but_keeps_identity(self):
        self.built()
        self.run_cli("create", "shop", "-n", "2")
        self.run_cli("start", "--all")
        c = self.world.containers[container_name("shop-01")]
        c.set("app-data/com.example.shop/login", "token")
        before = json.loads((self.home / "instances/shop-01.json").read_text())
        _, text = self.run_cli("ids", "shop-01", "--json")
        old_android_id = json.loads(text)[0]["android_id"]

        code, _ = self.run_cli("reset", "shop-01")  # 対話できないので確認で止まる
        self.assertEqual(code, 1)
        self.assertIn("--yes", err(self.app))
        code, text = self.run_cli("reset", "shop-01", answers=["y"])
        self.assertEqual(code, 0, err(self.app))

        c = self.world.containers[container_name("shop-01")]
        self.assertEqual(c.state, "running", "起動中だったものは起動し直す")
        self.assertIsNone(c.get("app-data/com.example.shop/login"))
        self.assertTrue(c.get("pkg/com.example.shop"), "雛形のアプリは残る")
        after = json.loads((self.home / "instances/shop-01.json").read_text())
        self.assertEqual((before["serialno"], before["mac"], before["adb_port"]),
                         (after["serialno"], after["mac"], after["adb_port"]))
        _, text = self.run_cli("ids", "shop-01", "--json")
        self.assertNotEqual(json.loads(text)[0]["android_id"], old_android_id)
        # もう1台は影響を受けない
        self.assertEqual(self.world.containers[container_name("shop-02")].state, "running")

    def test_stop_restart_and_crash(self):
        self.built()
        self.run_cli("create", "shop", "-n", "2")
        self.run_cli("start", "-t", "shop")
        code, text = self.run_cli("stop", "shop-02")
        self.assertEqual(code, 0)
        self.assertNotIn(container_name("shop-02"), self.world.containers)
        self.assertIn(container_name("shop-01"), self.world.containers)
        # 差分は停止しても残る
        self.assertIn(diff_volume_name("shop-02"), self.world.volumes)

        self.world.crash_on_start.add(container_name("shop-02"))
        code, text = self.run_cli("start", "shop-02")
        self.assertEqual(code, 1)
        self.assertIn("失敗", text)
        _, text = self.run_cli("list")
        self.assertIn("異常終了", text)

    def test_port_conflict_message(self):
        self.built()
        self.run_cli("create", "shop", "-n", "1")
        # 管理外のコンテナが同じポートを使っている
        self.world.local_images["other"] = ("sha256:other", 1)
        self.world.docker(["run", "-d", "--privileged", "--name", "other", "-p", "127.0.0.1:15555:5555",
                           "-v", "x:/data", "other", "a=b"])
        code, _ = self.run_cli("start", "shop-01")
        self.assertEqual(code, 1)
        self.assertIn("ポート 15555", err(self.app))

    def test_rm_removes_containers_volumes_and_records(self):
        self.built()
        self.run_cli("create", "shop", "-n", "2")
        self.run_cli("start", "--all")
        code, _ = self.run_cli("rm", "--all", "--yes")
        self.assertEqual(code, 0, err(self.app))
        self.assertEqual(list((self.home / "instances").glob("*.json")), [])
        self.assertFalse(any(n.startswith("droidfork-diff-") for n in self.world.volumes))
        self.assertEqual(self.world.containers, {})
        self.assertEqual(self.world.connected, set())
        # 雛形は残る
        self.assertIn(base_volume_name("shop"), self.world.volumes)

    def test_template_rm(self):
        self.built()
        self.run_cli("create", "shop", "-n", "1")
        code, _ = self.run_cli("template", "rm", "shop", "-y")
        self.assertEqual(code, 1)
        self.assertIn("--force", err(self.app))
        code, _ = self.run_cli("template", "rm", "shop", "-y", "--force")
        self.assertEqual(code, 0, err(self.app))
        self.assertFalse((self.home / "templates/shop").exists())
        self.assertEqual(self.world.volumes, {})

    def test_bulk_install_and_screen(self):
        self.built()
        self.run_cli("create", "shop", "-n", "3")
        self.run_cli("start", "shop-01", "shop-02")
        apk_dir = self.tmp / "newapp"
        apk_dir.mkdir()
        (apk_dir / "base.apk").write_text("a")
        (apk_dir / "split_config.ja.apk").write_text("b")
        code, text = self.run_cli("install", str(apk_dir))
        self.assertEqual(code, 0, err(self.app))
        self.assertEqual(text.count("成功"), 2, "起動中の2台だけ")
        self.assertTrue(self.world.containers[container_name("shop-02")].get("pkg/newapp"))

        code, _ = self.run_cli("screen", "--all", "--scrcpy-args", "--max-size 800")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.world.spawned), 2)
        self.assertEqual(self.world.spawned[0][:3], ["scrcpy", "-s", "127.0.0.1:15555"])
        self.assertEqual(self.world.spawned[0][-2:], ["--max-size", "800"])

    def test_up_one_shot(self):
        code, text = self.run_cli("up", "-n", "2")
        self.assertEqual(code, 0, err(self.app))
        self.assertEqual(sorted(n for n in self.world.containers), [container_name("sm-s911c-01"), container_name("sm-s911c-02")])
        self.assertIn("adb devices", text)
        listed = [line for line in text.splitlines() if line.startswith("sm-s911c-0") and "起動中" in line]
        self.assertEqual(len(listed), 2)
        self.assertTrue(all(line.endswith("秒") for line in listed), "一覧に起動時間が出る")
        # 既存の雛形を指定すると取り込み・作成はやり直さない
        builds = len(self.world.docker_calls("run"))
        code, _ = self.run_cli("up", "-n", "1", "-t", "sm-s911c")
        self.assertEqual(code, 0, err(self.app))
        self.assertEqual(len(self.world.docker_calls("run")), builds + 1)

    def test_resolve_image_after_prune(self):
        self.built()
        self.run_cli("create", "shop", "-n", "1")
        self.world.local_images.clear()  # docker image prune された
        code, _ = self.run_cli("start", "shop-01")
        self.assertEqual(code, 0, err(self.app))
        # タグの中身が変わっていたら止める
        self.run_cli("stop", "shop-01")
        self.world.local_images.clear()
        self.world.registry[IMAGE_REF] = ("sha256:" + "b" * 64, 1)
        code, _ = self.run_cli("start", "shop-01")
        self.assertEqual(code, 1)
        self.assertIn("イメージ", err(self.app))


class MiscCommandTest(FlowTestCase):
    def test_restart_connect_no_wait_and_config(self):
        self.built()
        self.run_cli("create", "shop", "-n", "2")
        code, text = self.run_cli("start", "--all", "--no-wait")
        self.assertEqual(code, 0, err(self.app))
        self.assertIn("起動処理中", text)
        self.world.connected.clear()
        code, text = self.run_cli("connect")
        self.assertEqual(code, 0)
        self.assertEqual(text.count("OK"), 2)
        first = self.world.containers[container_name("shop-01")]
        code, text = self.run_cli("restart", "shop-01")
        self.assertEqual(code, 0, err(self.app))
        self.assertIsNot(self.world.containers[container_name("shop-01")], first)
        self.assertIn("起動完了", text)
        code, text = self.run_cli("config")
        self.assertEqual(json.loads(text.split("\n", 1)[1])["adb_bind"], "127.0.0.1")

    def test_requires_target(self):
        self.built()
        self.run_cli("create", "shop", "-n", "1")
        code, _ = self.run_cli("start")
        self.assertEqual(code, 1)
        self.assertIn("--all", err(self.app))
        code, _ = self.run_cli("start", "nope-01")
        self.assertEqual(code, 1)
        self.assertIn("見つかりません", err(self.app))


class ReportTest(FlowTestCase):
    def test_stats(self):
        self.built()
        self.run_cli("create", "shop", "-n", "3")
        self.run_cli("start", "shop-01", "shop-02")
        code, text = self.run_cli("stats")
        self.assertEqual(code, 0, err(self.app))
        self.assertIn("雛形の共有層", text)
        self.assertIn("1台あたりディスク増分", text)
        self.assertIn("丸ごとコピーした場合", text)
        code, text = self.run_cli("stats", "--json")
        data = json.loads(text)
        s = data["summary"]
        self.assertEqual((s["instances"], s["running"]), (3, 2))
        self.assertAlmostEqual(s["avg_mem"], 812.5 * 1024**2, delta=1)
        self.assertLess(s["actual_data_total"], s["full_copy_data_total"])
        self.assertEqual(s["more_instances_estimate"], int(12000000 * 1024 // (812.5 * 1024**2)))

    def test_doctor(self):
        code, text = self.run_cli("doctor")
        self.assertEqual(code, 0, text)
        self.assertIn("binder", text)
        self.assertIn("memfd", text)
        self.host.files["/proc/filesystems"] = "nodev\toverlay\n"
        self.host.files["/proc/version"] = "Linux version 5.15.153.1-microsoft-standard-WSL2"
        code, text = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertIn("WSL2", text)
        self.assertIn("カスタムカーネル", text)
        self.world.docker_up = False
        code, text = self.run_cli("doctor")
        self.assertIn("デーモンに接続できません", text)

    def test_doctor_warns_public_adb(self):
        (self.home).mkdir(parents=True, exist_ok=True)
        (self.home / "config.json").write_text('{"adb_bind": "0.0.0.0"}')
        self.app = make_app(self.home, self.world, self.host)
        code, text = self.run_cli("doctor")
        self.assertIn("外部から接続できます", text)

    def test_template_show_and_list(self):
        self.built()
        code, text = self.run_cli("template", "list")
        self.assertIn("作成済み", text)
        code, text = self.run_cli("template", "show", "shop")
        self.assertEqual(code, 0)
        self.assertIn("INSTALL_FAILED_NO_MATCHING_ABIS", text)
        self.assertIn("ARM翻訳", text)

    def test_logs_and_docker_down(self):
        self.built()
        self.run_cli("create", "shop", "-n", "1")
        code, _ = self.run_cli("logs", "shop-01", "-f")
        self.assertEqual(self.world.passthrough_calls[-1], ["docker", "logs", "--tail", "100", "-f", "droidfork-shop-01"])
        self.world.docker_up = False
        code, text = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("不明", text)
        code, _ = self.run_cli("start", "--all")
        self.assertEqual(code, 1)
        self.assertIn("Docker デーモン", err(self.app))


if __name__ == "__main__":
    unittest.main()
