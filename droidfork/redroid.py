"""Redroid 固有の知識をここに集める（企画書10章「上流への依存箇所を薄く保つ」）。

- コンテナ／ボリュームの命名
- 起動パラメータ（androidboot.redroid_* など）の組み立て
- docker run の引数の組み立て

入出力は持たない純粋な関数だけにして、Redroid 側の仕様変更はこのファイルで吸収する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .identity import is_valid_prop_value

ADB_PORT_IN_CONTAINER = 5555

# コンテナ内のマウント先
DATA = "/data"            # 雛形を作るときは通常の /data として書き込む
DATA_BASE = "/data-base"  # インスタンス: 全台で共有する雛形（読み取り専用）
DATA_DIFF = "/data-diff"  # インスタンス: そのインスタンスだけの差分

LABEL_MANAGED = "droidfork.managed"
LABEL_ROLE = "droidfork.role"
LABEL_INSTANCE = "droidfork.instance"
LABEL_TEMPLATE = "droidfork.template"
ROLE_INSTANCE = "instance"
ROLE_BUILD = "build"


def container_name(instance_id: str) -> str:
    return f"droidfork-{instance_id}"


def build_container_name(template: str) -> str:
    return f"droidfork-build-{template}"


def base_volume_name(template: str) -> str:
    return f"droidfork-base-{template}"


def diff_volume_name(instance_id: str) -> str:
    return f"droidfork-diff-{instance_id}"


def _even(n: float) -> int:
    v = int(round(n))
    return max(2, v - (v % 2))


@dataclass(frozen=True)
class Display:
    width: int
    height: int
    dpi: int
    fps: int = 30

    def scaled(self, factor: float) -> "Display":
        """解像度とDPIを同じ比率で下げる（画面上のレイアウトは保ったまま省メモリにする）。"""
        if factor == 1:
            return self
        return Display(
            width=_even(self.width * factor),
            height=_even(self.height * factor),
            dpi=max(120, int(round(self.dpi * factor))),
            fps=self.fps,
        )

    def with_fps(self, fps: int | None) -> "Display":
        if fps is None or fps == self.fps:
            return self
        return Display(self.width, self.height, self.dpi, fps)

    def label(self) -> str:
        return f"{self.width}x{self.height} {self.dpi}dpi {self.fps}fps"

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height, "dpi": self.dpi, "fps": self.fps}

    @classmethod
    def from_dict(cls, d: dict) -> "Display":
        return cls(int(d["width"]), int(d["height"]), int(d["dpi"]), int(d.get("fps", 30)))


@dataclass
class BootOptions:
    display: Display
    gpu_mode: str = "guest"        # guest = ソフト描画（省メモリ・GPU不要）
    use_memfd: bool = False        # ashmem のないカーネルでは memfd を使う
    overlay: bool = False          # /data-base（共有）＋ /data-diff（個別）で /data を組み立てる
    serialno: str | None = None
    props: dict[str, str] = field(default_factory=dict)
    dns: list[str] = field(default_factory=list)
    root_adb: bool = False         # 雛形作成時のみ: adb シェルを root にする（ro.secure=0）


def boot_args(opts: BootOptions) -> list[str]:
    d = opts.display
    args = [
        f"androidboot.redroid_width={d.width}",
        f"androidboot.redroid_height={d.height}",
        f"androidboot.redroid_dpi={d.dpi}",
        f"androidboot.redroid_fps={d.fps}",
        f"androidboot.redroid_gpu_mode={opts.gpu_mode}",
    ]
    if opts.use_memfd:
        args.append("androidboot.use_memfd=true")
    if opts.overlay:
        args.append("androidboot.use_redroid_overlayfs=1")
    if opts.dns:
        args.append(f"androidboot.redroid_net_ndns={len(opts.dns)}")
        args.extend(f"androidboot.redroid_net_dns{i}={dns}" for i, dns in enumerate(opts.dns, 1))
    if opts.serialno:
        # androidboot.serialno → ro.boot.serialno → ro.serialno が通常の経路。念のため直接も渡す。
        args.append(f"androidboot.serialno={opts.serialno}")
        args.append(f"ro.serialno={opts.serialno}")
    if opts.root_adb:
        args.append("ro.secure=0")
    for key, value in opts.props.items():
        if not is_valid_prop_value(value):
            raise ValueError(f"起動パラメータに使えない値です: {key}={value!r}")
        args.append(f"{key}={value}")
    return args


@dataclass(frozen=True)
class Mount:
    volume: str
    target: str
    readonly: bool = False


@dataclass
class RunSpec:
    name: str
    image: str
    labels: dict[str, str]
    bind_host: str
    host_port: int
    mounts: list[Mount]
    boot_args: list[str]
    mac: str | None = None


def docker_run_args(spec: RunSpec) -> list[str]:
    args = ["run", "-d", "--privileged", "--name", spec.name]
    for key, value in spec.labels.items():
        args += ["--label", f"{key}={value}"]
    args += ["-p", f"{spec.bind_host}:{spec.host_port}:{ADB_PORT_IN_CONTAINER}"]
    if spec.mac:
        args += ["--mac-address", spec.mac]
    for m in spec.mounts:
        args += ["-v", f"{m.volume}:{m.target}" + (":ro" if m.readonly else "")]
    args.append(spec.image)
    args.extend(spec.boot_args)
    return args


def adb_address(bind_host: str, port: int) -> str:
    """ホスト側から adb connect するときのアドレス。"""
    host = bind_host
    if host in ("", "0.0.0.0", "::", "localhost"):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    return f"{host}:{port}"
