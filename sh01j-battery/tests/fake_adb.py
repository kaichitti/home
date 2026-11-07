#!/usr/bin/env python3
"""テスト用の偽 adb。状態は環境変数 FAKE_ADB_STATE の JSON ファイルに保持。"""
import json, os, sys

path = os.environ["FAKE_ADB_STATE"]
st = json.load(open(path))
args = sys.argv[1:]
if args[:1] == ["-s"]:
    args = args[2:]
if args == ["devices"]:
    print("List of devices attached\nABC123\tdevice\n")
elif args[:1] == ["reboot"]:
    st["rebooted"] = True
elif args[:1] == ["shell"]:
    c = args[1].split()
    if c[0] == "getprop":
        print(st["props"].get(c[1], ""))
    elif c[:2] == ["settings", "get"]:
        print(st["settings"].get(c[3], "null"))
    elif c[:2] == ["settings", "put"]:
        st["settings"][c[3]] = c[4]
    elif c[0] == "dumpsys":
        if "--reset" in c:
            st["reset"] = True
        else:
            print(st["dumpsys"].get(c[1], ""))
json.dump(st, open(path, "w"))
