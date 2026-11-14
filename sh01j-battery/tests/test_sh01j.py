import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sh01j_battery as t
import sh01j_deep as d


def batterystats(awake="0h 30m 0s 0ms", discharged_off=4, none_pct=1.0, app_mah=5.0,
                 app_wl="0h 1m 0s 0ms", cell=20.0, phone=3.0, kernel=""):
    """Android 5.1 の dumpsys batterystats を模したテキスト(画面OFF 10時間)"""
    return """Statistics since last charge:
  System starts: 0, currently on battery: true
  Time on battery: 11h 0m 0s 0ms (100.0%%) realtime, 1h 30m 0s 0ms (13.6%%) uptime
  Time on battery screen off: 10h 0m 0s 0ms (90.9%%) realtime, %s (5.0%%) uptime
  Screen on: 1h 0m 0s 0ms (9.1%%) 20x, Interactive: 1h 0m 0s 0ms (9.1%%)
  Total partial wakelock time: 1h 0m 0s 0ms
  Phone signal levels:
    none 1h 0m 0s 0ms (%.1f%%) 5x
    good 9h 0m 0s 0ms (90.0%%) 10x
  Signal scanning time: 0m 10s 0ms
  Radio types:
    lte 11h 0m 0s 0ms (100.0%%) 1x
  Mobile radio active time: 20m 0s 0ms (3.0%%) 40x
  Device battery use since last full charge
    Amount discharged (lower bound): 20
    Amount discharged (upper bound): 21
    Amount discharged while screen on: 10
    Amount discharged while screen off: %d

  Estimated power use (mAh):
    Capacity: 1700, Computed drain: 300, actual drain: 300-320
    Uid u0a87: %.1f
    Cell standby: %.1f
    Screen: 40.0
    Uid 1001: %.1f
    Idle: 10.0
    Uid 1000: 8.0

  All kernel wake locks:
  Kernel Wake lock PowerManagerService.WakeLocks: 0h 20m 0s 0ms (300 times) realtime
%s
  1001:
    Wake lock RILJ: 5m 0s 0ms partial (100 times) realtime
  u0a87:
    Wake lock SyncLoop: %s partial (999 times) realtime
    Wake lock *alarm*: 1m 0s 0ms partial (10 times) realtime
""" % (awake, none_pct, discharged_off, app_mah, cell, phone, kernel, app_wl)


PACKAGES = """Packages:
  Package [com.example.oldservice] (1a2b3c):
    userId=10087 gids=[3003]
  Package [com.android.phone] (4d5e6f):
    userId=1001 gids=[3002]
"""
ALARM_QUIET = "  Top Alarms:\n    +1s0ms running, 3 wakeups, 5 alarms: 1000:android\n"
ALARM_BUSY = ("  Top Alarms:\n    +2m0s running, 1200 wakeups, 1200 alarms: u0a87:com.example.oldservice\n"
              "      *walarm*:com.example.oldservice.RETRY\n")


def radio_log(n_setup=2, n_ims_fail=0, cause="MISSING_UNKNOWN_APN"):
    lines = ["11-14 00:00:00.000 D/RILJ    ( 1234): [0001]> RADIO_POWER on"]
    for i in range(n_setup):
        lines.append("11-14 %02d:%02d:00.000 D/RILJ    ( 1234): [%04d]> SETUP_DATA_CALL 14 0 spmode.ne.jp"
                     % (i * 10 // 60 % 10, i * 10 % 60, i))
        if n_ims_fail:
            lines.append("11-14 %02d:%02d:01.000 D/DCT     ( 1234): onDataSetupComplete: error DcFailCause=%s fail"
                         % (i * 10 // 60 % 10, i * 10 % 60, cause))
    for i in range(n_ims_fail):
        lines.append("11-14 05:%02d:00.000 E/ImsService( 2222): IMS registration failed: 403 Forbidden" % (i % 60))
    lines.append("11-14 10:00:00.000 D/RILJ    ( 1234): [9999]< SIGNAL_STRENGTH")
    return "\n".join(lines)


def events_log(loops=0):
    lines = ["11-14 00:00:00.000 I/am_proc_start( 800): [0,100,1000,system,service,x]"]
    for i in range(loops):
        lines.append("11-14 %02d:%02d:00.000 I/am_proc_start( 800): [0,%d,10087,com.example.oldservice,service,"
                     "com.example.oldservice/.SyncService]" % (i // 6 % 10, i * 10 % 60, 2000 + i))
        lines.append("11-14 %02d:%02d:05.000 I/am_crash( 800): [%d,0,com.example.oldservice,948806,"
                     "javax.net.ssl.SSLHandshakeException,Trust anchor not found,x.java,1]"
                     % (i // 6 % 10, i * 10 % 60, 2000 + i))
    lines.append("11-14 10:00:00.000 I/am_proc_start( 800): [0,101,1000,system,service,x]")
    return "\n".join(lines)


BATTERY = "Current Battery Service state:\n  status: 3\n  health: 2\n  level: 80\n  scale: 100\n  voltage: 3900\n  temperature: 300\n"
REGISTRY = "  mServiceState=0 0 voice home data home NTT DOCOMO  RilVoiceRadioTechnology=14(LTE) RilDataRadioTechnology=14(LTE)\n"


def raw(bs=None, alarm=ALARM_QUIET, radio=None, events=None, apn="Row: 0 _id=1, name=sp-mode, apn=spmode.ne.jp, type=default"):
    return {"batterystats": bs or batterystats(), "alarm": alarm, "package": PACKAGES,
            "radio_log": radio or radio_log(), "events_log": events or events_log(),
            "apn": apn, "telephony": REGISTRY, "battery": BATTERY}


def state(raw_data=None, **settings):
    s = {"preferred_network_mode": "11", "preferred_network_mode1": "11",
         "volte_vt_enabled": "1", "wifi_scan_always_enabled": "0"}
    s.update(settings)
    r = raw_data or raw()
    shell = {"dumpsys batterystats": r["batterystats"], "dumpsys battery": r["battery"],
             "dumpsys telephony.registry": r["telephony"], "dumpsys alarm": r["alarm"],
             "dumpsys package packages": r["package"], "logcat -b radio -d -v time": r["radio_log"],
             "logcat -b events -d -v time": r["events_log"],
             "content query --uri content://telephony/carriers/preferapn": r["apn"]}
    return {"props": {"ro.product.model": "SH-01J", "ro.build.version.release": "5.1"},
            "settings": s, "shell": shell}


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
        with open(self.state_path, "w") as f:
            json.dump(st, f)

    def read(self):
        with open(self.state_path) as f:
            return json.load(f)

    def run_cmd(self, *args):
        buf = io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            with redirect_stdout(buf):
                rc = t.main(list(args) + ["--adb", self.adb_path])
        finally:
            os.chdir(cwd)
        return rc, buf.getvalue()


class TestParse(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(t.parse_duration_ms("1h 2m 3s 4ms"), 3723004)

    def test_batterystats_basic(self):
        r = t.parse_batterystats(batterystats(none_pct=20.0))
        self.assertEqual(r["on_battery_ms"], 11 * 3600000)
        self.assertEqual(r["no_signal_pct"], 20.0)
        self.assertEqual(r["wakelocks"][0][0], "RILJ")

    def test_detail_stats(self):
        st = d.parse_detail_stats(batterystats(awake="4h 30m 0s 0ms", app_wl="4h 0m 0s 0ms"))
        self.assertEqual(st["screen_off_ms"], 10 * 3600000)
        self.assertEqual(st["screen_off_awake_ms"], 4.5 * 3600000)
        self.assertEqual(st["discharged_screen_off"], 4)
        self.assertEqual(st["uid_power"]["u0a87"], 5.0)
        self.assertEqual(st["Cell standby"], 20.0)
        self.assertEqual(st["uid_wakelocks"]["u0a87"][0], ("SyncLoop", 4 * 3600000))
        self.assertEqual(st["kernel_wakelocks"][0][0], "PowerManagerService.WakeLocks")

    def test_uid(self):
        self.assertEqual(d.uid_to_int("u0a87"), 10087)
        self.assertEqual(d.uid_to_int("1001"), 1001)
        self.assertEqual(d.parse_packages(PACKAGES)[10087], ["com.example.oldservice"])

    def test_alarms(self):
        self.assertEqual(d.parse_alarms(ALARM_BUSY)["com.example.oldservice"], 1200)

    def test_service_state(self):
        r = t.parse_service_state(REGISTRY)
        self.assertEqual(r["voice_state"], 0)
        self.assertEqual(r["data_rat"], "LTE")

    def test_mask(self):
        m = t.mask_private("imsi=440101234567890 tel=09012345678 level: 80 a@b.jp")
        self.assertNotIn("440101234567890", m)
        self.assertNotIn("09012345678", m)
        self.assertNotIn("a@b.jp", m)
        self.assertIn("level: 80", m)


class TestAnalyze(unittest.TestCase):
    def top(self, r):
        causes, facts = d.analyze(r)
        self.assertTrue(causes, "原因が出ない")
        return causes[0], causes

    def test_healthy(self):
        causes, facts = d.analyze(raw())
        self.assertEqual(causes, [])

    def test_app_cause(self):
        bs = batterystats(awake="4h 30m 0s 0ms", app_wl="4h 0m 0s 0ms", app_mah=150.0, discharged_off=30)
        c, _ = self.top(raw(bs=bs, alarm=ALARM_BUSY, events=events_log(loops=60)))
        self.assertEqual(c.kind, "app")
        self.assertEqual(c.packages, ["com.example.oldservice"])
        self.assertTrue(any("アラーム" in e for e in c.evidence))
        self.assertTrue(any("起動を" in e for e in c.evidence))

    def test_protected_app_not_disabled(self):
        self.assertTrue(d.is_protected("com.android.phone"))
        self.assertTrue(d.is_protected("jp.co.sharp.android.launcher"))
        self.assertFalse(d.is_protected("com.example.oldservice"))

    def test_network_cause(self):
        bs = batterystats(awake="3h 0m 0s 0ms", phone=80.0, discharged_off=25,
                          kernel="  Kernel Wake lock radio-interface: 2h 0m 0s 0ms (5000 times) realtime")
        c, _ = self.top(raw(bs=bs, radio=radio_log(n_setup=300, n_ims_fail=40),
                            apn="Row: 0 apn=mopera.net, type=default"))
        self.assertEqual(c.kind, "network")
        self.assertTrue(any("IMS" in e for e in c.evidence))
        self.assertTrue(any("mopera" in e for e in c.evidence))

    def test_signal_cause(self):
        c, _ = self.top(raw(bs=batterystats(none_pct=35.0, cell=200.0, discharged_off=15)))
        self.assertEqual(c.kind, "signal")

    def test_battery_cause(self):
        c, _ = self.top(raw(bs=batterystats(awake="0h 30m 0s 0ms", discharged_off=18)))
        self.assertEqual(c.kind, "battery")


class TestCli(Base):
    def test_diagnose_settings_problems(self):
        self.write(state(preferred_network_mode="9", preferred_network_mode1="9",
                         volte_vt_enabled="0", wifi_scan_always_enabled="1"))
        rc, out = self.run_cmd("diagnose")
        self.assertEqual(rc, 0)
        self.assertIn("3G(FOMA) が含まれています", out)
        self.assertIn("VoLTE が OFF", out)
        self.assertIn("修正できる設定が 3 件", out)

    def test_diagnose_lte_only_but_app_drain(self):
        bs = batterystats(awake="4h 30m 0s 0ms", app_wl="4h 0m 0s 0ms", app_mah=150.0, discharged_off=30)
        self.write(state(raw(bs=bs, alarm=ALARM_BUSY)))
        rc, out = self.run_cmd("diagnose")
        self.assertIn("LTE のみです", out)
        self.assertIn("深掘り分析", out)
        self.assertIn("com.example.oldservice", out)

    def test_fix_disables_app_and_restore(self):
        bs = batterystats(awake="4h 30m 0s 0ms", app_wl="4h 0m 0s 0ms", app_mah=150.0, discharged_off=30)
        self.write(state(raw(bs=bs, alarm=ALARM_BUSY)))
        rc, out = self.run_cmd("fix", "-y")
        s = self.read()
        self.assertEqual(s["disabled"], ["com.example.oldservice"])
        self.assertIn("am force-stop com.example.oldservice", s["log"])
        rc, out = self.run_cmd("restore", "-y")
        self.assertEqual(self.read()["disabled"], [])

    def test_fix_settings_backup_keeps_original(self):
        self.write(state(preferred_network_mode="9", preferred_network_mode1="9", volte_vt_enabled="0"))
        self.run_cmd("fix", "-y")
        s = self.read()
        self.assertEqual(s["settings"]["preferred_network_mode"], "11")
        self.assertEqual(s["settings"]["volte_vt_enabled"], "1")
        self.assertTrue(s.get("rebooted"))
        self.run_cmd("fix", "-y")  # 2回目でも元の値は上書きされない
        self.run_cmd("restore", "-y")
        s = self.read()
        self.assertEqual(s["settings"]["preferred_network_mode"], "9")
        self.assertEqual(s["settings"]["volte_vt_enabled"], "0")

    def test_fix_network_reregisters_volte(self):
        bs = batterystats(awake="3h 0m 0s 0ms", phone=80.0, discharged_off=25)
        self.write(state(raw(bs=bs, radio=radio_log(n_setup=300, n_ims_fail=40))))
        self.run_cmd("fix", "-y")
        s = self.read()
        self.assertIn("settings put global volte_vt_enabled 0", s["log"])
        self.assertEqual(s["settings"]["volte_vt_enabled"], "1")
        self.assertTrue(s.get("rebooted"))

    def test_fix_nothing(self):
        self.write(state())
        rc, out = self.run_cmd("fix", "-y")
        self.assertIn("変更した項目はありません", out)
        self.assertFalse(self.read().get("rebooted"))

    def test_collect(self):
        st = state()
        st["shell"]["dumpsys telephony.registry"] += "mImsi=440101234567890\n"
        self.write(st)
        rc, out = self.run_cmd("collect")
        self.assertEqual(rc, 0)
        import glob, zipfile
        z = zipfile.ZipFile(glob.glob(os.path.join(self.tmp, "sh01j_report_*.zip"))[0])
        self.assertIn("batterystats.txt", z.namelist())
        self.assertNotIn(b"440101234567890", z.read("telephony.txt"))

    def test_reset_stats(self):
        self.write(state())
        self.run_cmd("reset-stats")
        self.assertTrue(self.read().get("reset"))

    def test_no_adb(self):
        self.assertEqual(t.main(["diagnose", "--adb", "/nonexistent/adb"]), 2)


if __name__ == "__main__":
    unittest.main()
