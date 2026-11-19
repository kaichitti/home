"""E1 媒体識別・方式選択（企画書 §8.3、NIST SP 800-88 Rev.2 の区分）。

入力（読み取り専用コマンドの出力。テストではモック）:
  lsblk -J -b -o NAME,SERIAL,MODEL,SIZE,TRAN,ROTA,RM,TYPE   接続方式（sata/nvme/usb/mmc）・回転の有無
  smartctl -j -a <dev>                                       プロトコル・回転数・シリアル・容量
  hdparm -I <dev>                                            ATA の Security / Sanitize 対応、frozen
  hdparm -N <dev>                                            HPA（隠し領域）の有無
  nvme id-ctrl <dev> -o json                                 SANICAP / FNA / OACS

選んだ方式は「区分（Clear / Purge / Destroy）・名前・実行予定コマンド・注意」で返す。
具体的なオプションは各ツールの man で確認済み（hdparm 9.65 / nvme-cli 2.8 / nwipe 0.34）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CLEAR, PURGE, DESTROY = "Clear", "Purge", "Destroy"
DIRECT_CONNECT = "本体スロットに直結"


@dataclass
class Probe:
    serial: str | None = None
    model: str | None = None
    capacity: int | None = None
    media: str = "unknown"          # hdd / sata_ssd / nvme / usb_flash / sd / usb_ssd / usb_hdd / unknown
    transport: str | None = None    # sata / nvme / usb / mmc / sas
    rotational: bool | None = None
    removable: bool = False
    ata_security: bool = False
    ata_enhanced_erase: bool = False
    ata_frozen: bool = False
    ata_sanitize: set[str] = field(default_factory=set)     # overwrite / block / crypto
    nvme_sanitize: set[str] = field(default_factory=set)    # block / crypto / overwrite
    nvme_format_crypto: bool = False
    nvme_format: bool = False
    hpa: bool = False
    readable: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class Method:
    category: str | None            # Clear / Purge / Destroy / None（実行できない）
    name: str
    commands: list[list[str]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)   # 解消するまで実行しない事項
    notes: list[str] = field(default_factory=list)
    status_command: list[str] | None = None             # 完了ステータスの確認コマンド
    expected_pattern: bytes | None = None               # 読み戻しで期待する内容（上書き系のみ）

    @property
    def executable(self) -> bool:
        return self.category in (CLEAR, PURGE) and not self.blockers


# ---------------------------------------------------------------- 解析
def parse_lsblk(data: dict, serial: str) -> dict | None:
    for dev in data.get("blockdevices", []):
        if (dev.get("serial") or "").strip() == serial.strip() and dev.get("type", "disk") == "disk":
            return dev
    return None


def apply_lsblk(p: Probe, dev: dict) -> None:
    p.transport = (dev.get("tran") or "").lower() or None
    rota = dev.get("rota")
    p.rotational = None if rota is None else rota in (True, 1, "1")
    p.removable = dev.get("rm") in (True, 1, "1")
    p.serial = p.serial or dev.get("serial")
    p.model = p.model or (dev.get("model") or "").strip() or None
    p.capacity = p.capacity or (int(dev["size"]) if dev.get("size") else None)


def apply_smartctl(p: Probe, data: dict) -> None:
    p.serial = data.get("serial_number") or p.serial
    p.model = data.get("model_name") or p.model
    cap = (data.get("user_capacity") or {}).get("bytes")
    p.capacity = cap or p.capacity
    rr = data.get("rotation_rate")
    if rr is not None:
        p.rotational = rr > 0
    proto = ((data.get("device") or {}).get("protocol") or "").upper()
    if proto == "NVME":
        p.transport = p.transport or "nvme"
    if data.get("smartctl", {}).get("exit_status", 0) & 0x02:
        p.notes.append("smartctl で媒体を開けません（読めない媒体の可能性）")


def apply_hdparm_identify(p: Probe, text: str) -> None:
    sec = re.search(r"^Security:\s*\n(.*?)(?:^\S|\Z)", text, re.S | re.M)
    if sec:
        block = sec.group(1)
        p.ata_security = re.search(r"^\s*supported\s*$", block, re.M) is not None
        p.ata_enhanced_erase = re.search(r"^\s*supported: enhanced erase", block, re.M) is not None
        p.ata_frozen = re.search(r"^\s*frozen\s*$", block, re.M) is not None
    if "SANITIZE feature set" in text:
        if "OVERWRITE_EXT command" in text:
            p.ata_sanitize.add("overwrite")
        if "BLOCK_ERASE_EXT command" in text:
            p.ata_sanitize.add("block")
        if "CRYPTO_SCRAMBLE_EXT command" in text:
            p.ata_sanitize.add("crypto")
    m = re.search(r"Nominal Media Rotation Rate:\s*(.+)", text)
    if m:
        p.rotational = "Solid State" not in m.group(1)


def apply_hdparm_hpa(p: Probe, text: str) -> None:
    if re.search(r"HPA is enabled", text):
        p.hpa = True


def apply_nvme_id_ctrl(p: Probe, data: dict) -> None:
    sanicap = int(data.get("sanicap", 0))
    if sanicap & 0x1:
        p.nvme_sanitize.add("crypto")
    if sanicap & 0x2:
        p.nvme_sanitize.add("block")
    if sanicap & 0x4:
        p.nvme_sanitize.add("overwrite")
    oacs = int(data.get("oacs", 0))
    p.nvme_format = bool(oacs & 0x2)
    p.nvme_format_crypto = bool(int(data.get("fna", 0)) & 0x4)
    p.serial = (data.get("sn") or "").strip() or p.serial
    p.model = (data.get("mn") or "").strip() or p.model
    p.transport = p.transport or "nvme"


def classify(p: Probe, declared_kind: str | None = None) -> None:
    """接続方式・回転・受付時の申告種別から媒体の種類を決める。"""
    kind = (declared_kind or "").replace(" ", "").lower()
    if p.transport == "nvme":
        p.media = "nvme"
    elif p.transport == "mmc" or "sd" == kind.replace("カード", ""):
        p.media = "sd"
    elif p.transport == "usb":
        if "usbメモリ" in kind:
            p.media = "usb_flash"
        elif "sdカード" in kind:
            p.media = "sd"
        elif p.rotational:
            p.media = "usb_hdd"
        elif "ssd" in kind or p.rotational is False and not p.removable:
            p.media = "usb_ssd"
        else:
            p.media = "usb_flash"
    elif p.rotational:
        p.media = "hdd"
    elif p.rotational is False:
        p.media = "sata_ssd"


# ---------------------------------------------------------------- 方式選択
def select_method(p: Probe, dev: str = "<DEVICE>") -> Method:
    """§8.3 の表に従って方式を選ぶ。dev は実行直前に解決したデバイスパス。"""
    if not p.readable:
        return Method(DESTROY, "物理破壊（読めない・書けない媒体）",
                      notes=["穿孔機で物理破壊し、破壊後の写真を記録する"])

    if p.media == "usb_ssd":
        return Method(None, DIRECT_CONNECT,
                      blockers=["USB 変換アダプタ経由では消去命令が正しく届かない場合があるため、"
                                "SSD を本体の SATA / M.2 スロットに直結して再識別する"],
                      notes=["SSD に上書き消去は使わない"])

    if p.media == "nvme":
        if "crypto" in p.nvme_sanitize:
            return Method(PURGE, "NVMe Sanitize（Crypto Erase）",
                          [["nvme", "sanitize", dev, "--sanact=0x04"]],
                          status_command=["nvme", "sanitize-log", dev, "-o", "json"])
        if "block" in p.nvme_sanitize:
            return Method(PURGE, "NVMe Sanitize（Block Erase）",
                          [["nvme", "sanitize", dev, "--sanact=0x02"]],
                          status_command=["nvme", "sanitize-log", dev, "-o", "json"])
        if p.nvme_format and p.nvme_format_crypto:
            return Method(PURGE, "NVMe Format NVM（Cryptographic Erase, SES=2）",
                          [["nvme", "format", dev, "--ses=2", "--force"]])
        if p.nvme_format:
            return Method(PURGE, "NVMe Format NVM（User Data Erase, SES=1）",
                          [["nvme", "format", dev, "--ses=1", "--force"]],
                          notes=["User Data Erase の扱いは製品により異なる。読み戻しと復旧試行で確認する"])
        return Method(DESTROY, "物理破壊（消去命令に未対応の NVMe SSD）", notes=["SSD に上書き消去は使わない"])

    if p.media == "sata_ssd":
        blockers = []
        if p.ata_frozen:
            blockers.append("SATA のセキュリティが frozen。BIOS 設定の変更、またはスリープ復帰・"
                            "ホットプラグで解除してから再識別する")
        if "crypto" in p.ata_sanitize:
            return Method(PURGE, "ATA Sanitize（Crypto Scramble）",
                          [["hdparm", "--yes-i-know-what-i-am-doing", "--sanitize-crypto-scramble", dev]],
                          blockers=blockers, status_command=["hdparm", "--sanitize-status", dev])
        if "block" in p.ata_sanitize:
            return Method(PURGE, "ATA Sanitize（Block Erase）",
                          [["hdparm", "--yes-i-know-what-i-am-doing", "--sanitize-block-erase", dev]],
                          blockers=blockers, status_command=["hdparm", "--sanitize-status", dev])
        if p.ata_security and p.ata_enhanced_erase:
            pw = "resq-erase"
            return Method(PURGE, "ATA Enhanced Secure Erase",
                          [["hdparm", "--user-master", "u", "--security-set-pass", pw, dev],
                           ["hdparm", "--user-master", "u", "--security-erase-enhanced", pw, dev]],
                          blockers=blockers,
                          notes=["一時パスワードは消去完了で解除される。失敗時は --security-disable で解除"])
        return Method(DESTROY, "物理破壊（消去命令に未対応の SATA SSD）", notes=["SSD に上書き消去は使わない"])

    if p.media in ("hdd", "usb_hdd"):
        blockers = []
        if p.hpa:
            blockers.append("HPA（隠し領域）が有効。解除してから全域を対象にする（hdparm -N で確認）")
        if p.media == "hdd" and "overwrite" in p.ata_sanitize:
            return Method(PURGE, "ATA Sanitize（Overwrite）",
                          [["hdparm", "--yes-i-know-what-i-am-doing", "--sanitize-overwrite-passes", "1",
                            "--sanitize-overwrite", "hex:00000000", dev]],
                          blockers=blockers, status_command=["hdparm", "--sanitize-status", dev],
                          expected_pattern=b"\0")
        if p.media == "hdd" and "crypto" in p.ata_sanitize:
            return Method(PURGE, "ATA Sanitize（Crypto Scramble）",
                          [["hdparm", "--yes-i-know-what-i-am-doing", "--sanitize-crypto-scramble", dev]],
                          blockers=blockers, status_command=["hdparm", "--sanitize-status", dev])
        return Method(CLEAR, "全領域 1 回上書き（ゼロ）＋全域検証",
                      [["nwipe", "--autonuke", "--nogui", "--method=zero", "--verify=last", "--rounds=1", dev]],
                      blockers=blockers, expected_pattern=b"\0")

    if p.media in ("usb_flash", "sd"):
        return Method(CLEAR, "全領域上書き（ゼロ）＋全域検証",
                      [["nwipe", "--autonuke", "--nogui", "--method=zero", "--verify=last", "--rounds=1", dev]],
                      expected_pattern=b"\0",
                      notes=["汎用の消去命令を持たない媒体。Purge 相当が必要な場合は物理破壊"])

    return Method(None, "媒体を識別できない", blockers=["種別・接続方式を確認して再識別する"])


def probe_from_outputs(serial: str, *, lsblk: dict | None = None, smartctl: dict | None = None,
                       hdparm_i: str | None = None, hdparm_n: str | None = None, nvme_id: dict | None = None,
                       declared_kind: str | None = None, readable: bool = True) -> Probe:
    p = Probe(serial=serial, readable=readable)
    if lsblk:
        dev = parse_lsblk(lsblk, serial)
        if dev:
            apply_lsblk(p, dev)
    if smartctl:
        apply_smartctl(p, smartctl)
    if hdparm_i:
        apply_hdparm_identify(p, hdparm_i)
    if hdparm_n:
        apply_hdparm_hpa(p, hdparm_n)
    if nvme_id:
        apply_nvme_id_ctrl(p, nvme_id)
    classify(p, declared_kind)
    return p
