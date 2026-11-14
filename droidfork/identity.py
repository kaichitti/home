"""インスタンスごとの識別子を新規に生成する（企画書8章）。

方針:
- 実機の IMEI・シリアル・広告ID などはコピーしない。ここで作る値はすべて新規の乱数。
- 機種名・メーカー名は製品名で固定し、特定機種になりすまさない。
- Android ID は雛形に残さず、各インスタンスの初回起動時に Android 自身が生成する
  （雛形側の処理は template.py の seal を参照）。
"""

from __future__ import annotations

import re
import secrets
from typing import Iterable

# 読み間違えやすい文字（0/O, 1/I）を除いたシリアル用の文字
SERIAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SERIAL_RE = re.compile(r"^DF[0-9]{4}[A-HJ-NP-Z2-9]{6}$")

# 02 = ローカル管理・ユニキャストのMAC。44:46 は "DF" のASCII。
MAC_PREFIX = "02:44:46"
MAC_RE = re.compile(r"^02:44:46(:[0-9a-f]{2}){3}$")

# Redroid の起動パラメータ（key=value）に安全に載せられる値
PROP_VALUE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def random_token(length: int) -> str:
    return "".join(secrets.choice(SERIAL_ALPHABET) for _ in range(length))


def new_serial(seq: int, taken: Iterable[str] = ()) -> str:
    """連番＋ランダムのシリアル（例: DF0003K7Q2ZP）。"""
    used = set(taken)
    for _ in range(1000):
        serial = f"DF{seq % 10000:04d}{random_token(6)}"
        if serial not in used:
            return serial
    raise RuntimeError("シリアル番号を生成できませんでした")


def build_serial() -> str:
    """雛形を作るときだけ使う使い捨てのシリアル。"""
    return "DFBUILD" + random_token(5)


def new_mac(taken: Iterable[str] = ()) -> str:
    used = {m.lower() for m in taken}
    for _ in range(1000):
        tail = secrets.token_bytes(3)
        mac = MAC_PREFIX + ":" + ":".join(f"{b:02x}" for b in tail)
        if mac not in used:
            return mac
    raise RuntimeError("MACアドレスを生成できませんでした")


def is_valid_prop_value(value: str) -> bool:
    return bool(PROP_VALUE_RE.match(value))


def device_props(manufacturer: str, model: str) -> dict[str, str]:
    """全インスタンス共通の機種名・メーカー名（実機の値は使わない）。"""
    return {
        "ro.product.manufacturer": manufacturer,
        "ro.product.model": model,
    }
