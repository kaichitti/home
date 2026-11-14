import json
import tempfile
import unittest
from pathlib import Path

from droidfork.adb import (
    install_outcome, parse_devices, parse_getprop, parse_package_info, parse_package_list,
    parse_pm_paths, parse_resolution, parse_wm,
)
from droidfork.config import load_config
from droidfork.identity import MAC_RE, SERIAL_RE, device_props, new_mac, new_serial
from droidfork.images import choose_version, image_ref, parse_version_arg
from droidfork.redroid import (
    BootOptions, Display, Mount, RunSpec, adb_address, boot_args, docker_run_args,
)
from droidfork.util import CommandResult, DroidForkError, format_bytes, format_table, parse_size, slugify


class AdbParserTest(unittest.TestCase):
    def test_devices(self):
        text = (
            "List of devices attached\n"
            "R5CT10ABCDE            device usb:1-1 product:dm1q model:SM_S911C device:dm1q transport_id:1\n"
            "127.0.0.1:15555        device product:redroid_x86_64 model:DroidFork_Virtual transport_id:3\n"
            "emulator-5554          offline transport_id:2\n"
            "0123456789ABCDEF       no permissions (user in plugdev group; are your udev rules wrong?); "
            "see [http://developer.android.com/tools/device.html] usb:1-2 transport_id:4\n"
            "XYZ unauthorized usb:1-3 transport_id:5\n"
        )
        devices = parse_devices(text)
        self.assertEqual([d.serial for d in devices],
                         ["R5CT10ABCDE", "127.0.0.1:15555", "emulator-5554", "0123456789ABCDEF", "XYZ"])
        phone, inst, emu, noperm, unauth = devices
        self.assertTrue(phone.is_usb)
        self.assertEqual(phone.model, "SM S911C")
        self.assertTrue(inst.is_local_tcp)
        self.assertTrue(emu.is_emulator)
        self.assertEqual(noperm.state, "no permissions")
        self.assertEqual(unauth.state, "unauthorized")

    def test_getprop_and_wm(self):
        props = parse_getprop("[ro.build.version.sdk]: [34]\n[persist.sys.locale]: [ja-JP]\n[empty]: []\n")
        self.assertEqual(props, {"ro.build.version.sdk": "34", "persist.sys.locale": "ja-JP", "empty": ""})
        self.assertEqual(parse_wm("Physical size: 1080x2400\nOverride size: 720x1600\n"), ("1080x2400", "720x1600"))
        self.assertEqual(parse_wm("Physical density: 420\n"), ("420", None))
        self.assertEqual(parse_resolution("1080x2400"), (1080, 2400))
        self.assertIsNone(parse_resolution("bad"))

    def test_packages(self):
        self.assertEqual(parse_package_list("package:b.app\npackage:/data/app/x/base.apk=a.app\n"), ["a.app", "b.app"])
        self.assertEqual(parse_pm_paths("package:/data/app/a/base.apk\npackage:/data/app/a/split_config.ja.apk\n"),
                         ["/data/app/a/base.apk", "/data/app/a/split_config.ja.apk"])
        info = parse_package_info("    versionCode=42 minSdk=26 targetSdk=34\n    versionName=1.2.3\n")
        self.assertEqual(info, {"version_name": "1.2.3", "version_code": "42", "min_sdk": 26, "target_sdk": 34})

    def test_install_outcome(self):
        ok = CommandResult(["adb"], 0, "Performing Streamed Install\nSuccess\n")
        self.assertEqual(install_outcome(ok), (True, "Success"))
        ng = CommandResult(["adb"], 1, "", "adb: failed to install a.apk: Failure [INSTALL_FAILED_OLDER_SDK: x]\n")
        self.assertEqual(install_outcome(ng), (False, "INSTALL_FAILED_OLDER_SDK: x"))
        # 古い adb は失敗しても終了コード 0 を返す
        old = CommandResult(["adb"], 0, "Failure [INSTALL_FAILED_INVALID_APK]\n")
        self.assertFalse(install_outcome(old)[0])


class ImageTest(unittest.TestCase):
    def test_exact_versions(self):
        self.assertEqual(choose_version(34, "14"), choose_version(34, "14"))
        self.assertEqual(choose_version(34, "14").version, "14.0.0")
        self.assertTrue(choose_version(34, "14").exact)
        self.assertEqual(choose_version(27, "8.1.0").version, "8.1.0")
        self.assertEqual(choose_version(28, "9").version, "9.0.0")

    def test_out_of_range(self):
        old = choose_version(25, "7.1.2")
        self.assertEqual(old.version, "8.1.0")
        self.assertFalse(old.exact)
        self.assertIn("8.1", old.note)
        new = choose_version(37, "17")
        self.assertEqual(new.version, "16.0.0")
        self.assertIn("16", new.note)
        self.assertEqual(choose_version(32, "12").version, "12.0.0")
        self.assertEqual(choose_version(None, "13").version, "13.0.0")
        self.assertEqual(choose_version(None, "7.0").version, "8.1.0")

    def test_parse_version_arg(self):
        self.assertEqual(parse_version_arg("14"), "14.0.0")
        self.assertEqual(parse_version_arg("8.1"), "8.1.0")
        with self.assertRaises(DroidForkError):
            parse_version_arg("7")

    def test_image_ref(self):
        self.assertEqual(image_ref("redroid/redroid", "14.0.0"), ("redroid/redroid:14.0.0-latest", None))
        self.assertEqual(image_ref("redroid/redroid", "14.0.0", "_64only")[0], "redroid/redroid:14.0.0_64only-latest")
        ref, note = image_ref("redroid/redroid", "11.0.0", "_64only")
        self.assertEqual(ref, "redroid/redroid:11.0.0-latest")
        self.assertIsNotNone(note)


class IdentityTest(unittest.TestCase):
    def test_serial_and_mac(self):
        serials = {new_serial(i) for i in range(200)}
        self.assertEqual(len(serials), 200)
        for s in serials:
            self.assertRegex(s, SERIAL_RE)
        macs = set()
        for _ in range(200):
            macs.add(new_mac(macs))
        self.assertEqual(len(macs), 200)
        for m in macs:
            self.assertRegex(m, MAC_RE)
            first = int(m.split(":")[0], 16)
            self.assertTrue(first & 0x02, "ローカル管理ビット")
            self.assertFalse(first & 0x01, "ユニキャスト")

    def test_device_props(self):
        props = device_props("DroidFork", "DroidFork-Virtual")
        self.assertEqual(props["ro.product.model"], "DroidFork-Virtual")


class RedroidTest(unittest.TestCase):
    def test_scaled_display(self):
        d = Display(1080, 2340, 420, 30)
        half = d.scaled(0.5)
        self.assertEqual((half.width, half.height, half.dpi), (540, 1170, 210))
        odd = Display(1081, 2341, 420).scaled(0.5)
        self.assertEqual(odd.width % 2, 0)
        self.assertEqual(odd.height % 2, 0)
        self.assertIs(d.scaled(1), d)

    def test_boot_args(self):
        opts = BootOptions(display=Display(720, 1280, 320, 15), use_memfd=True, overlay=True,
                           serialno="DF0001ABCDEF", props=device_props("DroidFork", "DroidFork-Virtual"),
                           dns=["1.1.1.1", "8.8.8.8"])
        args = boot_args(opts)
        for expected in ("androidboot.redroid_width=720", "androidboot.redroid_height=1280",
                         "androidboot.redroid_dpi=320", "androidboot.redroid_fps=15",
                         "androidboot.redroid_gpu_mode=guest", "androidboot.use_memfd=true",
                         "androidboot.use_redroid_overlayfs=1", "androidboot.serialno=DF0001ABCDEF",
                         "androidboot.redroid_net_ndns=2", "androidboot.redroid_net_dns2=8.8.8.8",
                         "ro.product.model=DroidFork-Virtual"):
            self.assertIn(expected, args)
        self.assertNotIn("ro.secure=0", args)
        for a in args:
            self.assertNotRegex(a, r"\s")
        with self.assertRaises(ValueError):
            boot_args(BootOptions(display=Display(1, 1, 1), props={"ro.product.model": "has space"}))

    def test_docker_run_args(self):
        spec = RunSpec(name="droidfork-a-01", image="sha256:x", labels={"droidfork.managed": "1"},
                       bind_host="127.0.0.1", host_port=15555,
                       mounts=[Mount("droidfork-base-a", "/data-base", True), Mount("droidfork-diff-a-01", "/data-diff")],
                       boot_args=["androidboot.use_redroid_overlayfs=1"], mac="02:44:46:00:00:01")
        args = docker_run_args(spec)
        self.assertEqual(args[:3], ["run", "-d", "--privileged"])
        self.assertIn("127.0.0.1:15555:5555", args)
        self.assertIn("droidfork-base-a:/data-base:ro", args)
        self.assertIn("droidfork-diff-a-01:/data-diff", args)
        self.assertEqual(args[args.index("sha256:x") + 1:], ["androidboot.use_redroid_overlayfs=1"])

    def test_adb_address(self):
        self.assertEqual(adb_address("127.0.0.1", 15555), "127.0.0.1:15555")
        self.assertEqual(adb_address("0.0.0.0", 15555), "127.0.0.1:15555")
        self.assertEqual(adb_address("192.168.1.10", 15555), "192.168.1.10:15555")


class UtilTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(parse_size("1.5GB"), 1_500_000_000)
        self.assertEqual(parse_size("812.5MiB"), int(812.5 * 1024**2))
        self.assertEqual(parse_size("0B"), 0)
        self.assertEqual(parse_size("12kB"), 12_000)
        self.assertIsNone(parse_size("N/A"))
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1536 * 1024**2), "1.5 GiB")
        self.assertEqual(format_bytes(None), "不明")

    def test_table_handles_wide_chars(self):
        table = format_table(["ID", "状態"], [["a-01", "起動中"], ["a-02", "停止"]])
        lines = table.splitlines()
        self.assertEqual(lines[1], "a-01  起動中")
        self.assertEqual(lines[2], "a-02  停止")

    def test_slugify(self):
        self.assertEqual(slugify("Pixel 7a"), "pixel-7a")
        self.assertEqual(slugify("SM-S911C"), "sm-s911c")
        self.assertEqual(slugify("端末"), "device")


class ConfigTest(unittest.TestCase):
    def test_defaults_and_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(home=tmp, env={})
            self.assertEqual(cfg.adb_bind, "127.0.0.1")
            self.assertEqual(cfg.adb_port_base, 15555)
            Path(tmp, "config.json").write_text(json.dumps({"fps": 15, "use_memfd": True, "dns": ["1.1.1.1"]}))
            cfg = load_config(home=tmp, env={"DROIDFORK_ADB": "/opt/adb"})
            self.assertEqual((cfg.fps, cfg.use_memfd, cfg.dns, cfg.adb), (15, "true", ["1.1.1.1"], "/opt/adb"))

    def test_rejects_bad_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ({"nope": 1}, {"fps": "30"}, {"gpu_mode": "vulkan"}, {"model": "Droid Fork"}):
                Path(tmp, "config.json").write_text(json.dumps(bad))
                with self.assertRaises(DroidForkError, msg=str(bad)):
                    load_config(home=tmp, env={})

    def test_default_home(self):
        cfg = load_config(env={"HOME": "/home/u"})
        self.assertEqual(cfg.home, Path("/home/u/.local/share/droidfork"))
        cfg = load_config(env={"DROIDFORK_HOME": "/srv/df"})
        self.assertEqual(cfg.home, Path("/srv/df"))


if __name__ == "__main__":
    unittest.main()
