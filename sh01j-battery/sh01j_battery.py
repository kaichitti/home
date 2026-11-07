#!/usr/bin/env python3
"""SH-01J (AQUOS ケータイ) 電池持ち診断・修正ツール

FOMA(3G) 停波後に電池持ちが悪くなる主な原因を ADB 経由で調べ、修正します。

  python3 sh01j_battery.py diagnose        # 診断のみ(端末は変更しない)
  python3 sh01j_battery.py fix             # 推奨設定を適用(確認あり、元の値を保存)
  python3 sh01j_battery.py restore         # fix 前の設定に戻す
  python3 sh01j_battery.py reset-stats     # 電池統計をリセット(修正後の効果測定用)

必要なもの: PC に adb (Android SDK Platform-Tools)、端末で USB デバッグ有効。
外部ライブラリは不要です(Python 3.7 以上)。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

# 優先ネットワークタイプ(Android RILConstants)
NETWORK_MODES = {
    0: "WCDMA優先(3G/GSM)",
    1: "GSMのみ",
    2: "WCDMAのみ(3G)",
    3: "GSM/WCDMA自動",
    8: "LTE/CDMA/EvDo",
    9: "LTE/GSM/WCDMA",
    10: "LTE/CDMA/EvDo/GSM/WCDMA",
    11: "LTEのみ",
    12: "LTE/WCDMA",
}
LTE_ONLY = 11
MODES_WITH_3G = {0, 2, 3, 9, 10, 12}

VOLTE_KEYS = ["volte_vt_enabled", "enhanced_4g_mode_enabled"]
BACKUP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sh01j_backup.json")

OK, WARN, BAD, INFO = "OK", "注意", "問題", "情報"


class AdbError(Exception):
    pass


class Adb:
    def __init__(self, adb_path="adb", serial=None):
        self.adb_path = adb_path
        self.serial = serial

    def _run(self, args, timeout=60):
        cmd = [self.adb_path] + (["-s", self.serial] if self.serial else []) + args
        try:
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout, universal_newlines=True,
                               encoding="utf-8", errors="replace")
        except FileNotFoundError:
            raise AdbError("adb が見つかりません。Platform-Tools を入れて PATH を通すか --adb で場所を指定してください。")
        except subprocess.TimeoutExpired:
            raise AdbError("adb が応答しません: " + " ".join(args))
        if p.returncode != 0:
            raise AdbError((p.stderr or p.stdout).strip() or "adb エラー")
        return p.stdout

    def shell(self, command, timeout=60):
        return self._run(["shell", command], timeout=timeout).replace("\r\n", "\n")

    def devices(self):
        out = self._run(["devices"])
        devs = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                devs.append((parts[0], parts[1]))
        return devs

    def prop(self, name):
        return self.shell("getprop " + name).strip()

    def get_setting(self, ns, key):
        v = self.shell("settings get %s %s" % (ns, key)).strip()
        return None if v in ("", "null") else v

    def put_setting(self, ns, key, value):
        self.shell("settings put %s %s %s" % (ns, key, value))


# ---------------------------------------------------------------- 解析
def parse_duration_ms(text):
    """'1h 2m 3s 400ms' や '5m 3s' を ms に変換"""
    total = 0
    for num, unit in re.findall(r"(\d+)(d|h|ms|m|s)\b", text):
        n = int(num)
        total += {"d": 86400000, "h": 3600000, "m": 60000, "s": 1000, "ms": 1}[unit] * n
    return total


def fmt_ms(ms):
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return ("%d時間%d分" % (h, m)) if h else ("%d分%d秒" % (m, s))


def parse_battery(dumpsys):
    info = {}
    for key in ("level", "scale", "health", "temperature", "voltage", "status"):
        m = re.search(r"^\s*%s:\s*(-?\d+)" % key, dumpsys, re.M)
        if m:
            info[key] = int(m.group(1))
    return info


def parse_batterystats(text):
    """Android 5.x 〜 の dumpsys batterystats から電波関連の時間を抽出"""
    r = {}
    m = re.search(r"Time on battery:\s*([^(]+)\(", text)
    if m:
        r["on_battery_ms"] = parse_duration_ms(m.group(1))
    m = re.search(r"Signal scanning time:\s*([^(\n]+)", text)
    if m:
        r["scanning_ms"] = parse_duration_ms(m.group(1))
    m = re.search(r"Mobile radio active time:\s*([^(\n]+)", text)
    if m:
        r["radio_active_ms"] = parse_duration_ms(m.group(1))
    # Phone signal levels: none 1h 2m (10%) poor ... / Signal levels: ...
    m = re.search(r"(?:Phone )?[Ss]ignal levels:\s*\n?((?:.*\(\s*[\d.]+%\).*\n?)+)", text)
    if m:
        lv = re.search(r"none\s+([^(]+)\(\s*([\d.]+)%\)", m.group(1))
        if lv:
            r["no_signal_ms"] = parse_duration_ms(lv.group(1))
            r["no_signal_pct"] = float(lv.group(2))
    # Radio types: none / umts / lte など
    m = re.search(r"Radio types:\s*\n?((?:.*\(\s*[\d.]+%\).*\n?)+)", text)
    if m:
        types = {}
        for name, dur, pct in re.findall(r"([a-z0-9_]+)\s+([0-9hms ]+?)\s*\(\s*([\d.]+)%\)", m.group(1)):
            types[name] = float(pct)
        r["radio_types"] = types
    # 上位のウェイクロック
    wl = []
    for name, dur in re.findall(r"Wake lock\s+(\S+(?:\s\S+)*?):\s*([0-9dhms ]+)\s*(?:realtime|\()", text):
        wl.append((name, parse_duration_ms(dur)))
    kwl = []
    for name, dur in re.findall(r"Kernel Wake lock\s+(\S+):\s*([0-9dhms ]+)\s*(?:realtime|\()", text):
        kwl.append((name, parse_duration_ms(dur)))
    r["wakelocks"] = sorted(wl, key=lambda x: -x[1])[:5]
    r["kernel_wakelocks"] = sorted(kwl, key=lambda x: -x[1])[:5]
    return r


def parse_service_state(text):
    r = {}
    m = re.search(r"mServiceState=(.*)", text)
    if m:
        s = m.group(1)
        r["raw"] = s.strip()
        for pat, key in ((r"RilDataRadioTechnology=\d+\((\w+)\)", "data_rat"),
                         (r"RilVoiceRadioTechnology=\d+\((\w+)\)", "voice_rat")):
            mm = re.search(pat, s)
            if mm:
                r[key] = mm.group(1)
        tokens = s.split()
        if tokens and tokens[0].isdigit():
            r["voice_state"] = int(tokens[0])  # 0=圏内 1=圏外 2=緊急のみ 3=電源OFF
        if len(tokens) > 1 and tokens[1].isdigit():
            r["data_state"] = int(tokens[1])
        if "IWLAN" in s or "LTE" in s:
            r["has_lte"] = True
    return r


# ---------------------------------------------------------------- 診断
class Finding:
    def __init__(self, level, title, detail="", fix=None):
        self.level, self.title, self.detail, self.fix = level, title, detail, fix


def get_network_mode(adb):
    for key in ("preferred_network_mode1", "preferred_network_mode"):
        v = adb.get_setting("global", key)
        if v is not None:
            try:
                return key, int(v.split(",")[0])
            except ValueError:
                pass
    return None, None


def get_volte(adb):
    for key in VOLTE_KEYS:
        v = adb.get_setting("global", key)
        if v is not None:
            return key, v.strip()
    return None, None


def diagnose(adb):
    findings = []
    model = adb.prop("ro.product.model")
    android = adb.prop("ro.build.version.release")
    build = adb.prop("ro.build.display.id")
    print("端末: %s / Android %s / ビルド %s" % (model or "?", android or "?", build or "?"))
    if model and "SH-01J" not in model.upper():
        findings.append(Finding(WARN, "SH-01J 以外の端末です (%s)" % model,
                                "診断は可能ですが、修正内容が合わない可能性があります。"))

    # 1. 優先ネットワークタイプ
    key, mode = get_network_mode(adb)
    if mode is None:
        findings.append(Finding(WARN, "優先ネットワークタイプを読み取れませんでした"))
    elif mode in MODES_WITH_3G:
        findings.append(Finding(
            BAD, "ネットワーク設定に 3G(FOMA) が含まれています: %s" % NETWORK_MODES.get(mode, mode),
            "FOMA 停波後は 3G 電波が存在しないため、LTE が弱い場所で端末が 3G を探し続け、"
            "電池を大きく消費します。これが最も疑わしい原因です。",
            fix=("network_mode", key, mode)))
    elif mode == LTE_ONLY:
        findings.append(Finding(OK, "ネットワーク設定は LTE のみです"))
    else:
        findings.append(Finding(WARN, "ネットワーク設定: %s" % NETWORK_MODES.get(mode, mode)))

    # 2. VoLTE
    vkey, volte = get_volte(adb)
    if volte is None:
        findings.append(Finding(WARN, "VoLTE 設定を読み取れませんでした",
                                "端末の 設定 で VoLTE が ON になっているか確認してください。"))
    elif volte == "0":
        findings.append(Finding(
            BAD, "VoLTE が OFF です",
            "停波後は VoLTE なしでは通話できず、着発信のたびに存在しない 3G へ切り替えようとします。",
            fix=("volte", vkey, volte)))
    else:
        findings.append(Finding(OK, "VoLTE は ON です"))

    # 3. 現在の電波状態
    try:
        st = parse_service_state(adb.shell("dumpsys telephony.registry"))
        if st.get("voice_state") in (1, 2):
            findings.append(Finding(WARN, "現在 圏外/緊急通報のみ の状態です",
                                    "圏外では電波を探し続けるため電池が減ります。電波の弱い場所では機内モードも有効です。"))
        if st.get("data_rat"):
            findings.append(Finding(INFO, "現在の通信方式: %s" % st["data_rat"]))
    except AdbError:
        pass

    # 4. 電池統計
    try:
        bs = parse_batterystats(adb.shell("dumpsys batterystats", timeout=120))
    except AdbError:
        bs = {}
    total = bs.get("on_battery_ms", 0)
    if total:
        findings.append(Finding(INFO, "前回フル充電後の電池駆動時間: %s" % fmt_ms(total)))
        scan = bs.get("scanning_ms", 0)
        if scan:
            pct = scan * 100.0 / total
            lvl = BAD if pct >= 5 else WARN if pct >= 1 else OK
            findings.append(Finding(lvl, "電波サーチ時間: %s (%.1f%%)" % (fmt_ms(scan), pct),
                                    "電波を探している時間です。長いほど電池を消費します。" if lvl != OK else ""))
        if "no_signal_pct" in bs:
            p = bs["no_signal_pct"]
            lvl = BAD if p >= 10 else WARN if p >= 3 else OK
            findings.append(Finding(lvl, "圏外(電波なし)の時間: %.1f%%" % p,
                                    "自宅や職場など普段いる場所が LTE 圏外/弱電界の可能性があります。" if lvl != OK else ""))
        rt = bs.get("radio_types") or {}
        umts = sum(v for k, v in rt.items() if k in ("umts", "hsdpa", "hsupa", "hspa", "hspap"))
        if umts > 0:
            findings.append(Finding(WARN, "統計上 3G で通信していた時間: %.1f%%" % umts,
                                    "停波前の記録が残っている可能性もあります。reset-stats 後に再確認してください。"))
        if bs.get("radio_active_ms"):
            pct = bs["radio_active_ms"] * 100.0 / total
            lvl = WARN if pct >= 20 else OK
            findings.append(Finding(lvl, "モバイル通信の稼働時間: %s (%.1f%%)" % (fmt_ms(bs["radio_active_ms"]), pct),
                                    "アプリがバックグラウンドで頻繁に通信しています。" if lvl != OK else ""))
        for name, ms in bs.get("wakelocks", [])[:3]:
            if ms * 100.0 / total >= 5:
                findings.append(Finding(WARN, "スリープを妨げている処理: %s (%s)" % (name, fmt_ms(ms))))
    else:
        findings.append(Finding(WARN, "電池統計を取得できませんでした"))

    # 5. 電池本体
    try:
        b = parse_battery(adb.shell("dumpsys battery"))
    except AdbError:
        b = {}
    health = b.get("health")
    if health is not None:
        names = {1: "不明", 2: "良好", 3: "過熱", 4: "寿命", 5: "過電圧", 6: "異常", 7: "低温"}
        lvl = OK if health == 2 else BAD
        findings.append(Finding(lvl, "電池の状態(端末の自己申告): %s" % names.get(health, health),
                                "" if lvl == OK else "電池パックの交換をおすすめします。"))
    if "temperature" in b and b["temperature"] >= 400:
        findings.append(Finding(WARN, "電池温度が高めです: %.1f℃" % (b["temperature"] / 10.0)))
    findings.append(Finding(INFO, "電池パック自体の劣化",
                            "SH-01J は 2016 年発売です。購入から数年経っていれば、停波と関係なく電池の劣化も"
                            "考えられます(「良好」表示でも容量は減っていることがあります)。"))

    # 6. その他の電池を使う設定
    if adb.get_setting("global", "wifi_scan_always_enabled") == "1":
        findings.append(Finding(WARN, "Wi-Fi OFF 時も常に Wi-Fi スキャンする設定が ON",
                                fix=("setting", "global", "wifi_scan_always_enabled", "1", "0")))
    if adb.get_setting("global", "bluetooth_on") == "1":
        findings.append(Finding(INFO, "Bluetooth が ON です(使っていなければ OFF で節電)"))
    return findings


def print_findings(findings):
    marks = {OK: "[ OK ]", WARN: "[注意]", BAD: "[問題]", INFO: "[情報]"}
    print()
    for f in findings:
        print("%s %s" % (marks[f.level], f.title))
        if f.detail:
            print("        " + f.detail)
    fixes = [f for f in findings if f.fix]
    print()
    if fixes:
        print("→ 修正できる項目が %d 件あります。 `python3 %s fix` で適用できます。"
              % (len(fixes), os.path.basename(sys.argv[0])))
    else:
        print("→ 自動で修正できる設定上の問題は見つかりませんでした。")
        print("  電波の弱い場所での使用や電池の劣化が原因の可能性があります(README 参照)。")


# ---------------------------------------------------------------- 修正
def confirm(msg, assume_yes):
    if assume_yes:
        return True
    try:
        return input(msg + " [y/N]: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def apply_fixes(adb, assume_yes=False):
    findings = diagnose(adb)
    fixes = [f for f in findings if f.fix]
    if not fixes:
        print("\n修正が必要な設定はありません。")
        return 0
    backup = {"time": datetime.now().isoformat(timespec="seconds"),
              "model": adb.prop("ro.product.model"), "settings": []}
    for f in fixes:
        kind = f.fix[0]
        print()
        if kind == "network_mode":
            _, key, old = f.fix
            print("・ネットワーク設定を「%s」→「LTEのみ」に変更します。" % NETWORK_MODES.get(old, old))
            print("  注意: LTE 圏外の場所では 3G に逃げられなくなりますが、停波後は 3G 自体が無いので実質的な影響はありません。")
            if confirm("  適用しますか?", assume_yes):
                for k in ("preferred_network_mode", "preferred_network_mode1"):
                    prev = adb.get_setting("global", k)
                    if prev is not None:
                        backup["settings"].append(["global", k, prev])
                        adb.put_setting("global", k, LTE_ONLY)
                print("  → 適用しました")
        elif kind == "volte":
            _, key, old = f.fix
            print("・VoLTE を ON にします。")
            if confirm("  適用しますか?", assume_yes):
                for k in VOLTE_KEYS:
                    prev = adb.get_setting("global", k)
                    if prev is not None:
                        backup["settings"].append(["global", k, prev])
                        adb.put_setting("global", k, 1)
                print("  → 適用しました")
        elif kind == "setting":
            _, ns, key, old, new = f.fix
            print("・%s を %s → %s に変更します。" % (f.title, old, new))
            if confirm("  適用しますか?", assume_yes):
                backup["settings"].append([ns, key, old])
                adb.put_setting(ns, key, new)
                print("  → 適用しました")
    if backup["settings"]:
        with open(BACKUP_FILE, "w", encoding="utf-8") as fp:
            json.dump(backup, fp, ensure_ascii=False, indent=2)
        print("\n元の設定を %s に保存しました(restore で戻せます)。" % BACKUP_FILE)
        print("\n★ 設定をモデムに反映させるため、端末を再起動してください。")
        if confirm("今すぐ再起動しますか?", assume_yes):
            adb._run(["reboot"])
        print("再起動後、`diagnose` で設定が「LTEのみ」になっているか確認し、"
              "`reset-stats` → 満充電で 1〜2 日使って効果を確かめてください。")
    return 0


def restore(adb, assume_yes=False):
    if not os.path.exists(BACKUP_FILE):
        print("バックアップ (%s) がありません。" % BACKUP_FILE)
        return 1
    with open(BACKUP_FILE, encoding="utf-8") as fp:
        backup = json.load(fp)
    print("%s に保存した設定に戻します:" % backup.get("time"))
    for ns, key, val in backup["settings"]:
        print("  %s %s = %s" % (ns, key, val))
    if not confirm("戻しますか?", assume_yes):
        return 1
    for ns, key, val in backup["settings"]:
        adb.put_setting(ns, key, val)
    print("戻しました。端末を再起動してください。")
    return 0


def reset_stats(adb):
    adb.shell("dumpsys batterystats --reset")
    print("電池統計をリセットしました。満充電して USB を抜き、1〜2 日普段どおり使ってから diagnose してください。")
    return 0


# ---------------------------------------------------------------- main
def pick_device(adb):
    devs = adb.devices()
    ready = [d for d, s in devs if s == "device"]
    if adb.serial:
        return
    if not devs:
        raise AdbError("端末が見つかりません。USB 接続と USB デバッグの有効化を確認してください。")
    if not ready:
        states = ", ".join("%s(%s)" % d for d in devs)
        raise AdbError("端末は見えていますが使えません: %s\n"
                       "unauthorized の場合は端末に出ている「USB デバッグを許可」を OK してください。" % states)
    if len(ready) > 1:
        raise AdbError("複数の端末が接続されています。-s でシリアルを指定してください: " + ", ".join(ready))


def main(argv=None):
    ap = argparse.ArgumentParser(description="SH-01J 電池持ち診断・修正ツール (FOMA 停波対策)")
    ap.add_argument("command", choices=["diagnose", "fix", "restore", "reset-stats"], nargs="?",
                    default="diagnose")
    ap.add_argument("-y", "--yes", action="store_true", help="確認なしで適用")
    ap.add_argument("-s", "--serial", help="端末シリアル(複数接続時)")
    ap.add_argument("--adb", default=os.environ.get("ADB", shutil.which("adb") or "adb"),
                    help="adb の場所")
    a = ap.parse_args(argv)
    adb = Adb(a.adb, a.serial)
    try:
        pick_device(adb)
        if a.command == "diagnose":
            print_findings(diagnose(adb))
            return 0
        if a.command == "fix":
            return apply_fixes(adb, a.yes)
        if a.command == "restore":
            return restore(adb, a.yes)
        return reset_stats(adb)
    except AdbError as e:
        print("エラー: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
