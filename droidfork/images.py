"""実機の Android バージョンから Redroid のベースイメージを選ぶ。

Redroid の提供範囲は Android 8.1〜16（企画書7章）。範囲外は最も近いものを使い、注記を残す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .util import DroidForkError

# API レベル → Redroid のイメージのバージョン
SDK_TO_VERSION = {
    27: "8.1.0",
    28: "9.0.0",
    29: "10.0.0",
    30: "11.0.0",
    31: "12.0.0",
    32: "12.0.0",  # 12L は 12 のイメージで代用
    33: "13.0.0",
    34: "14.0.0",
    35: "15.0.0",
    36: "16.0.0",
}
VERSION_TO_SDK = {"8.1.0": 27, "9.0.0": 28, "10.0.0": 29, "11.0.0": 30, "12.0.0": 31,
                  "13.0.0": 33, "14.0.0": 34, "15.0.0": 35, "16.0.0": 36}
SUPPORTED_VERSIONS = list(VERSION_TO_SDK)
MIN_SDK = min(SDK_TO_VERSION)
MAX_SDK = max(SDK_TO_VERSION)

# 64bit専用イメージ（"_64only"）が提供されている最初のメジャーバージョン
VARIANT_MIN_MAJOR = {"_64only": 12}


@dataclass(frozen=True)
class VersionChoice:
    version: str
    exact: bool
    note: str | None = None


def _sdk_from_release(release: str | None) -> int | None:
    if not release:
        return None
    m = re.match(r"^(\d+)(?:\.(\d+))?", release.strip())
    if not m:
        return None
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    if major == 8:
        return 27 if minor >= 1 else 26
    for sdk, version in SDK_TO_VERSION.items():
        if int(version.split(".")[0]) == major:
            return sdk
    # 表にない古い/新しいバージョンは、範囲外であることが分かる値を返す
    return 26 - (8 - major) if major < 8 else MAX_SDK + (major - 16)


def choose_version(sdk: int | None, release: str | None = None) -> VersionChoice:
    label = f"Android {release or '?'}（API {sdk if sdk is not None else '?'}）"
    if sdk is None:
        sdk = _sdk_from_release(release)
    if sdk is None:
        return VersionChoice("14.0.0", False, f"{label} を判定できなかったため Android 14 のイメージを使います。")
    if sdk in SDK_TO_VERSION:
        version = SDK_TO_VERSION[sdk]
        if sdk == 32:
            return VersionChoice(version, False, f"{label} は 12.0.0 のイメージで代用します。")
        return VersionChoice(version, True)
    if sdk < MIN_SDK:
        return VersionChoice(
            SDK_TO_VERSION[MIN_SDK], False,
            f"{label} のイメージはないため、提供範囲で最も古い 8.1 を使います。一部アプリは動かない可能性があります。",
        )
    return VersionChoice(
        SDK_TO_VERSION[MAX_SDK], False,
        f"{label} のイメージはまだないため、提供範囲で最も新しい 16 を使います。新しいAPIを必須とするアプリは入らない可能性があります。",
    )


def parse_version_arg(text: str) -> str:
    """利用者が指定した "14" "14.0" "8.1" などをイメージのバージョン表記にする。"""
    t = text.strip()
    candidates = [t, f"{t}.0", f"{t}.0.0"]
    for c in candidates:
        if c in VERSION_TO_SDK:
            return c
    raise DroidForkError(
        f"Android バージョン「{text}」のイメージはありません。",
        hint="指定できるのは " + ", ".join(v.rsplit(".0", 1)[0] if v.endswith(".0.0") else v for v in SUPPORTED_VERSIONS) + " です。",
    )


def image_ref(repo: str, version: str, variant: str = "") -> tuple[str, str | None]:
    """イメージ名を返す。指定のバリアントが使えない場合は通常版に戻し、注記を返す。"""
    major = int(version.split(".")[0])
    if variant and major < VARIANT_MIN_MAJOR.get(variant, 0):
        return (
            f"{repo}:{version}-latest",
            f"バリアント {variant} は Android {VARIANT_MIN_MAJOR[variant]} 以降のみのため、通常版を使います。",
        )
    return f"{repo}:{version}{variant}-latest", None
