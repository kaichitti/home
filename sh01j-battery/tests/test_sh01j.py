import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sh01j_battery as t

BATTERYSTATS = """Statistics since last charge:
  System starts: 0, currently on battery: true
  Time on battery: 10h 0m 0s 0ms (100.0%) realtime, 9h 0m 0s 0ms (90.0%) uptime
  Signal scanning time: 1h 0m 0s 0ms
  Phone signal levels:
    none 2h 0m 0s 0ms (20.0%) 5x
    poor 3h 0m 0s 0ms (30.0%) 10x
  Mobile radio active time: 30m 0s 0ms (5.0%) 40x
  Radio types:
    none 1h 0m 0s 0ms (10.0%) 1x
    umts 2h 0m 0s 0ms (20.0%) 3x
    lte 7h 0m 0s 0ms (70.0%) 4x
  Wake lock RILJ: 1h 0m 0s 0ms realtime (100 times)
"""
BATTERY = "Current Battery Service state:\n  status: 3\n  health: 2\n  level: 80\n  scale: 100\n  voltage: 3900\n  temperature: 300\n"
REGISTRY = "  mServiceState=0 0 voice home data home NTT DOCOMO  RilVoiceRadioTechnology=14(LTE) RilDataRadioTechnology=14(LTE)\n"


def state(**settings):
    s = {"preferred_network_mode": "9", "preferred_network_mode1": "9",
         "volte_vt_enabled": "0", "wifi_scan_always_enabled": "1"}
    s.update(settings)
    return {"props": {"ro.product.model": "SH-01J", "ro.build.version.release": "5.1"},
            "settings": s,
            "dumpsys": {"batterystats": BATTERYSTATS, "battery": BATTERY, "telephony.registry": REGISTRY}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmp, "state.json")
        self.adb_path = os.path.join(self.tmp, "adb")
        with open(self.adb_path, "w") as f:
            f.write("#!/bin/sh\nexec %s %s \"$@\"\n" % (sys.executable, os.path.join(HERE, "fake_adb.py")))
        os.chmod(self.adb_path, 0o755)
        os.environ["FAKE_ADB_STATE"] = self.state_path
        t.BACKUP_FILE = os.path.join(self.tmp, "backup.json")

    def write(self, st):
        json.dump(st, open(self.state_path, "w"))

    def read(self):
        return json.load(open(self.state_path))

    def run_cmd(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = t.main(list(args) + ["--adb", self.adb_path])
        return rc, buf.getvalue()


class TestParse(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(t.parse_duration_ms("1h 2m 3s 4ms"), 3723004)

    def test_batterystats(self):
        r = t.parse_batterystats(BATTERYSTATS)
        self.assertEqual(r["on_battery_ms"], 36000000)
        self.assertEqual(r["scanning_ms"], 3600000)
        self.assertEqual(r["no_signal_pct"], 20.0)
        self.assertEqual(r["radio_types"]["umts"], 20.0)
        self.assertEqual(r["wakelocks"][0][0], "RILJ")

    def test_service_state(self):
        r = t.parse_service_state(REGISTRY)
        self.assertEqual(r["voice_state"], 0)
        self.assertEqual(r["data_rat"], "LTE")


class TestCli(Base):
    def test_diagnose_finds_problems(self):
        self.write(state())
        rc, out = self.run_cmd("diagnose")
        self.assertEqual(rc, 0)
        self.assertIn("3G(FOMA) が含まれています", out)
        self.assertIn("VoLTE が OFF", out)
        self.assertIn("修正できる項目が 3 件", out)

    def test_diagnose_clean(self):
        self.write(state(preferred_network_mode="11", preferred_network_mode1="11",
                         volte_vt_enabled="1", wifi_scan_always_enabled="0"))
        rc, out = self.run_cmd("diagnose")
        self.assertIn("LTE のみです", out)
        self.assertIn("見つかりませんでした", out)

    def test_fix_and_restore(self):
        self.write(state())
        rc, out = self.run_cmd("fix", "-y")
        s = self.read()
        self.assertEqual(s["settings"]["preferred_network_mode"], "11")
        self.assertEqual(s["settings"]["preferred_network_mode1"], "11")
        self.assertEqual(s["settings"]["volte_vt_enabled"], "1")
        self.assertEqual(s["settings"]["wifi_scan_always_enabled"], "0")
        self.assertTrue(s.get("rebooted"))
        rc, out = self.run_cmd("restore", "-y")
        s = self.read()
        self.assertEqual(s["settings"]["preferred_network_mode"], "9")
        self.assertEqual(s["settings"]["volte_vt_enabled"], "0")

    def test_reset_stats(self):
        self.write(state())
        self.run_cmd("reset-stats")
        self.assertTrue(self.read().get("reset"))

    def test_no_adb(self):
        rc = t.main(["diagnose", "--adb", "/nonexistent/adb"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
