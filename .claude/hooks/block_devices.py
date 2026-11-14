#!/usr/bin/env python3
"""PreToolUse フック：開発機で実デバイスを参照する Bash コマンドをブロックする。

終了コード 2 でブロック（1 ではブロックされない）。
最終防衛線は「開発機に実ドライブをつながない」こと（パターンは迂回されうる）。
"""
import json
import re
import sys

DEVICE = re.compile(r"/dev/(sd[a-z]|hd[a-z]|vd[a-z]|nvme\d|mmcblk\d|disk\d|rdisk\d|loop\d|mapper/|dm-\d|sg\d|sr\d)")

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(0)
cmd = (data.get("tool_input") or {}).get("command") or ""

if DEVICE.search(cmd):
    print("BLOCKED: 開発機で実デバイスを参照するコマンドは禁止。fixtures/ のイメージを使うこと。",
          file=sys.stderr)
    sys.exit(2)
sys.exit(0)
