"""SH-01J 電池消費の原因を特定する深掘り分析

「LTEのみ」にしても電池の減りが改善しない場合に、次のどれが原因かを
端末の統計とログから判定します。

  A. アプリ … 画面OFF中もアプリが端末を起こし続けている(ウェイクロック/アラーム/再起動ループ)
  B. 通信の再試行 … データ接続や VoLTE(IMS)登録の失敗→再試行ループ
  C. 電波環境 … 圏外/弱電界で電波を探し続けている
  D. 電池の劣化 … 端末は眠れているのに、電池の減りが速い
"""
import re
from collections import Counter, defaultdict

from sh01j_battery import parse_duration_ms, fmt_ms

# 止めると端末が使えなくなるので、自動停止の対象外にするパッケージ
PROTECTED_EXACT = {
    "android", "com.android.phone", "com.android.systemui", "com.android.settings",
    "com.android.server.telecom", "com.android.shell", "com.android.keychain",
    "com.android.packageinstaller", "com.android.defcontainer",
}
PROTECTED_WORDS = ("telephony", "ims", "launcher", "inputmethod", "keyboard", "providers",
                   "systemui", "phone", "dialer", "mms", "sms", "contacts", "bluetooth",
                   "nfc", "location", "wifi", "provision", "setupwizard")

# モデム/通信が原因で端末が起きていることを示すカーネルウェイクロック
RADIO_KERNEL_WAKELOCKS = ("radio-interface", "qcril", "qmi", "ipa", "rmnet", "msm_rx",
                          "qcom_rx", "wlan_rx", "netlink", "smd", "ril")


# ---------------------------------------------------------------- 解析
def parse_detail_stats(text):
    """dumpsys batterystats(Android 5.x)から原因判定に使う値を抽出"""
    r = {"uid_power": {}, "uid_wakelocks": defaultdict(list), "kernel_wakelocks": []}
    m = re.search(r"Time on battery screen off:\s*([^(]+)\([^)]*\)\s*realtime,\s*([^(]+)\(", text)
    if m:
        r["screen_off_ms"] = parse_duration_ms(m.group(1))
        r["screen_off_awake_ms"] = parse_duration_ms(m.group(2))
    m = re.search(r"Amount discharged while screen off:\s*(\d+)", text)
    if m:
        r["discharged_screen_off"] = int(m.group(1))
    m = re.search(r"Capacity:\s*(\d+)", text)
    if m:
        r["capacity_mah"] = int(m.group(1))

    # Estimated power use (mAh): 以下のブロック
    m = re.search(r"Estimated power use \(mAh\):\n((?:\s{4}.*\n?)+)", text)
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"\s*Uid (\S+):\s*([\d.]+)", line)
            if mm:
                r["uid_power"][mm.group(1)] = float(mm.group(2))
                continue
            mm = re.match(r"\s*(Cell standby|Idle|Phone calls|Wifi|Bluetooth|Screen|Flashlight|"
                          r"Unaccounted|Over-counted):\s*([\d.]+)", line)
            if mm:
                r[mm.group(1)] = float(mm.group(2))

    # UID ごとのウェイクロック
    uid = None
    for line in text.splitlines():
        mm = re.match(r"^  (u\d+[ai]\d+|\d+):\s*$", line)
        if mm:
            uid = mm.group(1)
            continue
        if re.match(r"^  \S", line):
            uid = None
        if uid:
            mm = re.match(r"\s+Wake lock (.+?): ([0-9dhms ]+?)\s*partial", line)
            if mm:
                r["uid_wakelocks"][uid].append((mm.group(1), parse_duration_ms(mm.group(2))))
        mm = re.match(r"\s+Kernel Wake lock (.+?): ([0-9dhms ]+?)\s*(?:\(|realtime)", line)
        if mm:
            r["kernel_wakelocks"].append((mm.group(1), parse_duration_ms(mm.group(2))))
    r["kernel_wakelocks"].sort(key=lambda x: -x[1])
    return r


def uid_to_int(uid):
    """'u0a87' → 10087, '1000' → 1000"""
    m = re.match(r"u(\d+)a(\d+)$", uid)
    if m:
        return int(m.group(1)) * 100000 + 10000 + int(m.group(2))
    return int(uid) if uid.isdigit() else None


def parse_packages(text):
    """dumpsys package から uid → [パッケージ名] を作る"""
    mp = defaultdict(list)
    pkg = None
    for line in text.splitlines():
        m = re.match(r"\s*Package \[([^\]]+)\]", line)
        if m:
            pkg = m.group(1)
            continue
        m = re.match(r"\s*userId=(\d+)", line)
        if m and pkg:
            if pkg not in mp[int(m.group(1))]:
                mp[int(m.group(1))].append(pkg)
            pkg = None
    return mp


def parse_alarms(text):
    """dumpsys alarm の Top Alarms から パッケージ → 起床回数"""
    c = Counter()
    for wakeups, pkg in re.findall(r"(\d+) wakeups?, \d+ alarms?: (?:u?\d+a?\d*:)?(\S+)", text):
        c[pkg] += int(wakeups)
    return c


_TS = re.compile(r"^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)")


def log_span_hours(lines):
    """logcat -v time の先頭と末尾の時刻から、ログがカバーする時間(h)"""
    stamps = []
    for line in (lines[0:50] + lines[-50:]) if lines else []:
        m = _TS.match(line)
        if m:
            mo, d, h, mi, s = map(int, m.groups())
            stamps.append((((mo * 31 + d) * 24 + h) * 60 + mi) * 60 + s)
    if len(stamps) < 2:
        return 0.0
    return max(0.0, (max(stamps) - min(stamps)) / 3600.0)


def parse_radio_log(text):
    """logcat -b radio から データ接続/IMS登録/電波サーチ の再試行回数"""
    lines = text.splitlines()
    r = {"hours": log_span_hours(lines), "setup_data": 0, "data_fail": 0,
         "ims_fail": 0, "oos": 0, "fail_causes": Counter()}
    for line in lines:
        if "SETUP_DATA_CALL" in line and ">" in line:
            r["setup_data"] += 1
        m = re.search(r"(?:DcFailCause|cause)[=:\s]+([A-Z_]{4,})", line)
        if m and ("fail" in line.lower() or "DcFailCause" in line):
            if m.group(1) not in ("NONE", "OK"):
                r["data_fail"] += 1
                r["fail_causes"][m.group(1)] += 1
        low = line.lower()
        if "ims" in low and "regist" in low and ("fail" in low or "error" in low or "403" in low):
            r["ims_fail"] += 1
        if "OUT_OF_SERVICE" in line or "mVoiceRegState=1" in line or "OOS" in line:
            r["oos"] += 1
    return r


def parse_events_log(text):
    """logcat -b events から プロセス起動回数とクラッシュ回数(プロセス名ごと)"""
    lines = text.splitlines()
    starts, crashes = Counter(), Counter()
    for line in lines:
        m = re.search(r"am_proc_start(?:\(\s*\d+\))?\s*:\s*\[([^\]]+)\]", line)
        if m:
            f = [x.strip() for x in m.group(1).split(",")]
            name = f[3] if len(f) >= 6 else (f[2] if len(f) >= 3 else "?")
            starts[name.split(":")[0]] += 1
        m = re.search(r"am_(?:crash|anr)(?:\(\s*\d+\))?\s*:\s*\[([^\]]+)\]", line)
        if m:
            f = [x.strip() for x in m.group(1).split(",")]
            name = next((x for x in f if re.match(r"[a-z][\w]*(\.[\w]+)+", x)), "?")
            crashes[name.split(":")[0]] += 1
    return {"hours": log_span_hours(lines), "starts": starts, "crashes": crashes}


def is_protected(pkg):
    if pkg in PROTECTED_EXACT:
        return True
    low = pkg.lower()
    return any(w in low for w in PROTECTED_WORDS)


# ---------------------------------------------------------------- 判定
class Cause:
    def __init__(self, kind, score, title, evidence, advice, packages=()):
        self.kind, self.score, self.title = kind, score, title
        self.evidence, self.advice, self.packages = evidence, advice, list(packages)


def collect_raw(adb):
    """分析に使う生データを端末から取得(取れないものは空文字)"""
    cmds = {
        "batterystats": "dumpsys batterystats",
        "alarm": "dumpsys alarm",
        "package": "dumpsys package packages",
        "radio_log": "logcat -b radio -d -v time",
        "events_log": "logcat -b events -d -v time",
        "telephony": "dumpsys telephony.registry",
        "battery": "dumpsys battery",
        "apn": "content query --uri content://telephony/carriers/preferapn",
    }
    raw = {}
    for k, c in cmds.items():
        try:
            raw[k] = adb.shell(c, timeout=180)
        except Exception:
            raw[k] = ""
    return raw


def analyze(raw):
    """生データから原因候補をスコア付きで返す(スコアの高い順)"""
    st = parse_detail_stats(raw.get("batterystats", ""))
    pkgs = parse_packages(raw.get("package", ""))
    alarms = parse_alarms(raw.get("alarm", ""))
    radio = parse_radio_log(raw.get("radio_log", ""))
    events = parse_events_log(raw.get("events_log", ""))
    causes, facts = [], []

    def names(uid):
        n = uid_to_int(uid)
        return pkgs.get(n, []) if n is not None else []

    off = st.get("screen_off_ms", 0)
    awake_pct = st["screen_off_awake_ms"] * 100.0 / off if off else None
    drain_per_h = None
    if off >= 3600000 and "discharged_screen_off" in st:
        drain_per_h = st["discharged_screen_off"] / (off / 3600000.0)
    if off:
        facts.append("画面OFFの時間: %s" % fmt_ms(off))
    if awake_pct is not None:
        facts.append("画面OFF中に端末が起きていた割合: %.0f%% (正常なら10%%未満)" % awake_pct)
    if drain_per_h is not None:
        facts.append("画面OFF中の電池の減り: 1時間あたり %.1f%% (正常なら0.5%%前後以下)" % drain_per_h)

    # ---- A. アプリ
    total_power = sum(st["uid_power"].values()) + sum(
        st.get(k, 0) for k in ("Cell standby", "Idle", "Screen", "Wifi", "Bluetooth", "Phone calls"))
    app_rows = []
    for uid, mah in st["uid_power"].items():
        n = uid_to_int(uid)
        if n is None or n < 10000:
            continue
        wl = sum(ms for _, ms in st["uid_wakelocks"].get(uid, []))
        app_rows.append((uid, mah, wl))
    # 電力推定に出てこなくても、ウェイクロックが長い UID は対象
    for uid, lst in st["uid_wakelocks"].items():
        n = uid_to_int(uid)
        if n and n >= 10000 and uid not in st["uid_power"]:
            app_rows.append((uid, 0.0, sum(ms for _, ms in lst)))

    suspects = {}
    for uid, mah, wl in app_rows:
        ev = []
        score = 0
        if total_power and mah / total_power >= 0.15:
            score += 2 if mah / total_power >= 0.3 else 1
            ev.append("推定消費 %.0fmAh (全体の%.0f%%)" % (mah, mah * 100 / total_power))
        if off and wl / off >= 0.05:
            score += 2 if wl / off >= 0.2 else 1
            top = max(st["uid_wakelocks"][uid], key=lambda x: x[1])
            ev.append("スリープ妨害 %s (主に「%s」)" % (fmt_ms(wl), top[0]))
        if score:
            for p in names(uid) or [uid]:
                suspects.setdefault(p, [0, []])
                suspects[p][0] += score
                suspects[p][1] += ev
    hours = max(radio["hours"], events["hours"], (off / 3600000.0) if off else 0) or 1.0
    for pkg, n in alarms.items():
        rate = n / max(hours, 1.0)
        if rate >= 12:  # 5分に1回以上
            suspects.setdefault(pkg, [0, []])
            suspects[pkg][0] += 2 if rate >= 60 else 1
            suspects[pkg][1].append("アラームで端末を %d 回起こしている(約%.0f回/時)" % (n, rate))
    ev_hours = events["hours"] or 1.0
    for proc, n in events["starts"].items():
        if n / ev_hours >= 6 and n >= 10:
            suspects.setdefault(proc, [0, []])
            suspects[proc][0] += 2
            suspects[proc][1].append("起動を %d 回繰り返している(約%.0f回/時)" % (n, n / ev_hours))
    for proc, n in events["crashes"].items():
        if n >= 3:
            suspects.setdefault(proc, [0, []])
            suspects[proc][0] += 2
            suspects[proc][1].append("異常終了/応答なし %d 回" % n)

    for pkg, (score, ev) in sorted(suspects.items(), key=lambda x: -x[1][0]):
        if pkg.isdigit() or re.match(r"u\d+a\d+", pkg):
            continue
        prot = is_protected(pkg)
        causes.append(Cause(
            "app", score + (1 if awake_pct and awake_pct >= 20 else 0),
            "アプリ「%s」が電池を消費しています" % pkg, ev,
            "このアプリは端末の動作に必要なため自動では止めません。設定 → アプリ から通知・自動更新を OFF にしてください。"
            if prot else
            "使っていないアプリなら `fix` で無効化できます(`restore` で戻せます)。"
            "停波やサービス終了で接続先が無くなったアプリが再試行を繰り返しているケースが多いです。",
            packages=[] if prot else [pkg]))

    # ---- B. 通信の再試行ループ
    rh = radio["hours"] or 0
    ev = []
    score = 0
    if rh >= 0.5:
        sd = radio["setup_data"] / rh
        if sd >= 6:
            score += 2 if sd >= 30 else 1
            ev.append("データ接続の再試行 %d 回(約%.0f回/時)" % (radio["setup_data"], sd))
        if radio["data_fail"] >= 5:
            score += 1
            causes_txt = ", ".join("%s×%d" % kv for kv in radio["fail_causes"].most_common(3))
            ev.append("データ接続の失敗 %d 回 (%s)" % (radio["data_fail"], causes_txt))
        if radio["ims_fail"] / rh >= 2 or radio["ims_fail"] >= 10:
            score += 2
            ev.append("VoLTE(IMS)登録の失敗 %d 回" % radio["ims_fail"])
    phone_uid_power = st["uid_power"].get("1001", 0)
    if total_power and phone_uid_power / total_power >= 0.15:
        score += 1
        ev.append("電話/通信システム(UID 1001)の消費が全体の%.0f%%" % (phone_uid_power * 100 / total_power))
    radio_kwl = [(n, ms) for n, ms in st["kernel_wakelocks"]
                 if any(k in n.lower() for k in RADIO_KERNEL_WAKELOCKS)]
    if off and radio_kwl and sum(ms for _, ms in radio_kwl) / off >= 0.1:
        score += 1
        ev.append("モデム由来のスリープ妨害: " + ", ".join(
            "%s %s" % (n, fmt_ms(ms)) for n, ms in radio_kwl[:3]))
    apn = raw.get("apn", "")
    m = re.search(r"apn=([^,\s]+)", apn)
    apn_name = m.group(1) if m else None
    if apn_name:
        facts.append("使用中の APN: %s" % apn_name)
        if "mopera" in apn_name.lower() or "foma" in apn_name.lower():
            score += 2
            ev.append("APN が FOMA 時代の設定のまま(%s)" % apn_name)
    if score:
        causes.append(Cause(
            "network", score, "通信の再試行ループ(データ接続/VoLTE登録の失敗の繰り返し)", ev,
            "停波後、3G 前提の設定が残っていると LTE 上で接続失敗→再試行を繰り返します。"
            "①APN を契約先の指定値(ドコモ/ahamo なら spmode.ne.jp)に設定し直す ②`fix` で VoLTE を再登録(OFF→ON+再起動)。"
            "改善しなければ SIM カードの抜き差し、それでもダメならドコモショップで SIM 交換を相談してください。"))

    # ---- C. 電波環境
    ns = None
    m = re.search(r"none\s+([^(]+)\(\s*([\d.]+)%\)", raw.get("batterystats", ""))
    if m:
        ns = float(m.group(2))
    cell = st.get("Cell standby", 0)
    ev, score = [], 0
    if ns is not None and ns >= 5:
        score += 2 if ns >= 20 else 1
        ev.append("圏外の時間 %.0f%%" % ns)
    if total_power and cell / total_power >= 0.3:
        score += 1
        ev.append("待受(電波)の消費が全体の%.0f%%" % (cell * 100 / total_power))
    if score:
        causes.append(Cause(
            "signal", score, "電波が弱い/圏外の場所で電波を探し続けています", ev,
            "設定では直せません。長くいる場所(寝室・職場の奥など)で圏外なら機内モードにする、"
            "窓際に置く、docomo の電波改善窓口に相談する、が有効です。"))

    # ---- D. 電池の劣化
    if drain_per_h is not None and awake_pct is not None:
        ev, score = [], 0
        if awake_pct < 15 and drain_per_h >= 0.8 and not any(c.score >= 3 for c in causes):
            score = 3 if drain_per_h >= 1.5 else 2
            ev.append("端末は画面OFF中ほぼ眠れている(起きていた割合 %.0f%%)のに、1時間で %.1f%% 減っている"
                      % (awake_pct, drain_per_h))
        if score:
            causes.append(Cause(
                "battery", score, "電池パックの劣化", ev,
                "ソフトの問題ではないため設定では直せません。電池パックの交換(ドコモショップ等)をおすすめします。"))

    causes.sort(key=lambda c: -c.score)
    return causes, facts


def print_analysis(causes, facts):
    print("\n==== 深掘り分析 ====")
    for f in facts:
        print("  ・" + f)
    if not causes:
        print("\n  はっきりした原因は見つかりませんでした。")
        print("  統計が短すぎる可能性があります。`reset-stats` → 満充電 → 半日以上使ってから再実行してください。")
        return
    print("\n推定原因(可能性の高い順):")
    for i, c in enumerate(causes, 1):
        bar = "★" * min(c.score, 5)
        print("\n %d. %s  %s" % (i, c.title, bar))
        for e in c.evidence:
            print("      根拠: " + e)
        print("      対策: " + c.advice)
