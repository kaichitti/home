"""コマンドライン（detcut run / analyze / verify / harvest / transcribe / shortcut / gui / presets）。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from detcut import __version__
from detcut.common import DetCutError

REPO_ROOT = Path(__file__).resolve().parent.parent


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _quiet(_: str) -> None:
    pass


def _progress_printer():
    last = [-1]

    def cb(frac: float) -> None:
        pct = int(frac * 100)
        if pct // 10 != last[0] // 10:
            last[0] = pct
            print(f"  … {pct}%", file=sys.stderr, flush=True)
    return cb


def _load(args):
    from detcut.config import load_config
    return load_config(args.preset, getattr(args, "set", None))


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("-p", "--preset", help="プリセット（YAML）。省略時は既定値")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="設定の上書き（例: --set cut.speech_on_db=-40）。複数指定可")


# ---------------------------------------------------------------- commands

def cmd_run(args) -> int:
    from detcut.pipeline import run
    cfg = _load(args)
    log = _quiet if args.quiet else _log
    status = 0
    for inp in args.inputs:
        log(f"=== {inp}")
        res = run(inp, cfg, out_dir=args.output, target=args.target, log=log,
                  progress=None if args.quiet else _progress_printer(), use_cache=not args.no_cache)
        for w in res.warnings:
            log(f"[注意] {w}")
        s = res.stats
        print(f"{Path(inp).name}: {s['keeps']}区間を残し{s['cuts']}区間をカット "
              f"{s['src_ms'] / 1000:.1f}s → {s['tl_ms'] / 1000:.1f}s（-{s['reduction_percent']}%）"
              f" テロップ{s['telops']} SE{s['se']} BGM{s['bgm_pieces']}")
        for kind in ("aup2", "exo", "report"):
            if kind in res.files:
                print(f"  {kind}: {res.files[kind]}")
        if cfg["output"]["open_after"] and "aup2" in res.files:
            exe = cfg["output"]["aviutl2_exe"]
            if exe and os.path.isfile(exe):
                subprocess.Popen([exe, res.files["aup2"]])
            else:
                log("[注意] output.aviutl2_exe が設定されていないため AviUtl2 を起動しません")
    return status


def cmd_analyze(args) -> int:
    from detcut.analysis.suggest import render_histogram, suggest
    from detcut.pipeline import detect, prepare
    cfg = _load(args)
    prep = prepare(args.input, cfg, _log, _progress_printer())
    m = prep.media
    print(f"ファイル: {prep.input_path}")
    print(f"  映像: {'あり' if m.has_video else 'なし'}  {m.width}x{m.height}  fps={m.fps} (avg {m.avg_fps})"
          f"{'  ※VFRの可能性' if m.vfr_suspect else ''}")
    print(f"  音声: {m.audio_rate}Hz {m.audio_channels}ch  長さ {float(m.duration or 0):.2f}s")
    print(f"  プロジェクトfps: {prep.tb.fps}  入力SHA-256: {prep.input_sha256}")
    sg = suggest(prep.energy.energies, prep.energy.window)
    print("\n音量分布（10ms窓のdBFS）:")
    for line in render_histogram(sg.histogram):
        print("  " + line)
    print(f"\n推定ノイズフロア: {sg.noise_floor_db} dB / 発話レベル: {sg.speech_level_db} dB")
    print(f"提案: --set cut.speech_on_db={sg.speech_on_db} --set cut.speech_off_db={sg.speech_off_db}")
    cut = cfg["cut"]
    for label, on, off in (("現在の設定", cut["speech_on_db"], cut["speech_off_db"]),
                           ("提案の設定", sg.speech_on_db, sg.speech_off_db)):
        c = dict(cut, speech_on_db=on, speech_off_db=off)
        _, cl = detect(prep, c)
        red = 100 - cl.total_tl_frames * 100 // cl.total_src_frames if cl.total_src_frames else 0
        print(f"  {label}（on={on} / off={off}）: {len(cl.keeps)}区間, "
              f"{prep.tb.frame_to_ms(cl.total_tl_frames) / 1000:.1f}s 残す（-{red}%）")
    return 0


def cmd_verify(args) -> int:
    """同じ入力で2回実行し、出力のSHA-256が一致するか確かめる（1回目はキャッシュなし）。"""
    from detcut.pipeline import run
    cfg = _load(args)
    with tempfile.TemporaryDirectory(prefix="detcut_verify_") as tmp:
        r1 = run(args.input, cfg, out_dir=os.path.join(tmp, "a"), target=args.target, log=_quiet, use_cache=False)
        r2 = run(args.input, cfg, out_dir=os.path.join(tmp, "b"), target=args.target, log=_quiet, use_cache=True)
        names = sorted(set(r1.hashes) | set(r2.hashes) | {Path(r1.files["run"]).name})
        ok = True
        for name in names:
            a = _sha(os.path.join(r1.out_dir, name))
            b = _sha(os.path.join(r2.out_dir, name))
            same = a == b and a is not None
            ok &= same
            print(f"  {'一致' if same else '不一致'}  {name}  {a}")
    print("決定論性チェック: " + ("OK（2回の出力がバイト単位で一致）" if ok else "NG（差分あり）"))
    return 0 if ok else 3


def _sha(path: str):
    from detcut.common import sha256_file
    return sha256_file(path) if os.path.exists(path) else None


def cmd_harvest(args) -> int:
    from detcut.writers.aup2 import VERIFIED_VERSION
    from detcut.writers.effects import AUP2_BUILTIN, EXO_BUILTIN, diff_against_builtin, load_samples, read_text_auto
    from detcut.writers.ini import parse_ini
    samples = load_samples(args.sample) or {}
    is_exo = args.sample.lower().endswith(".exo")
    print(f"サンプル: {args.sample}（{'従来版 .exo' if is_exo else 'AviUtl2'}）")
    if not is_exo:
        secs = parse_ini(read_text_auto(args.sample))
        proj = next((s for s in secs if s.name == "project"), None)
        if proj is not None:
            print(f"  [project] version={proj.get('version')}（組み込み表の確認版: {VERIFIED_VERSION}）")
    print(f"  採取したエフェクト: {len(samples)} 種類")
    for name in sorted(samples):
        print(f"    {name}: " + ", ".join(k for k, _ in samples[name]))
    print("\n組み込みキー表との比較:")
    for line in diff_against_builtin(samples, EXO_BUILTIN if is_exo else AUP2_BUILTIN):
        print("  " + line)
    key = "object_samples_exo" if is_exo else "object_samples_aup2"
    print(f"\nこのサンプルを使うには、プリセットの project.{key} に\n  {os.path.abspath(args.sample)}\nを指定してください。")
    return 0


def cmd_transcribe(args) -> int:
    from detcut.asr.transcript import to_srt
    from detcut.asr.whisper_stage import transcribe_cached
    from detcut.common import write_bytes
    from detcut.pipeline import prepare
    cfg = _load(args)
    prep = prepare(args.input, cfg, _log, _progress_printer())
    cache_dir = cfg["cache"]["dir"] if cfg["cache"]["enabled"] else None
    t, _ = transcribe_cached(prep.input_path, prep.energy.pcm_sha256, cfg["telop"]["asr"], cache_dir,
                             cfg["ffmpeg"]["ffmpeg"], _log, use_cache=not args.no_cache)
    out = os.path.abspath(args.output or cfg["output"]["dir"])
    stem = Path(prep.input_path).stem
    write_bytes(os.path.join(out, f"{stem}.transcript.json"), t.dumps().encode("utf-8"))
    write_bytes(os.path.join(out, f"{stem}.srt"), to_srt(t).encode("utf-8"))
    print(f"文字起こし: {len(t.segments)} セグメント")
    print(f"  {os.path.join(out, stem + '.transcript.json')}")
    print(f"  {os.path.join(out, stem + '.srt')}")
    print("誤字を直したら、プリセットの telop.transcript_file にこのファイルを指定すると、以降はAIなしで同じ結果になります。")
    return 0


def cmd_shortcut(args) -> int:
    from detcut.shortcuts import find_shortcut, write_shortcut
    cfg = _load(args)
    if args.list or (not args.ids and not args.all):
        if not cfg["shortcuts"]:
            print("プリセットに shortcuts が定義されていません")
        for sc in cfg["shortcuts"]:
            print(f"  {sc['id']}: {sc['label']}（{len(sc['items'])} アイテム）")
        return 0
    targets = cfg["shortcuts"] if args.all else [find_shortcut(cfg, i) for i in args.ids]
    out = os.path.abspath(args.output or cfg["output"]["dir"])
    for sc in targets:
        for p in write_shortcut(sc, cfg, out):
            print(p)
    return 0


def cmd_gui(args) -> int:
    from detcut.gui.app import main as gui_main
    return gui_main(args.input, args.preset)


def cmd_presets(args) -> int:
    from detcut.config import find_presets
    for p in find_presets(Path.cwd() / "presets", REPO_ROOT / "presets"):
        print(p)
    return 0


# ---------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="detcut", description="AviUtl向け 決定論的自動編集ツール DetCut")
    ap.add_argument("--version", action="version", version=f"detcut {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="無音カット等を行い .aup2 / .exo / レポートを書き出す")
    p.add_argument("inputs", nargs="+", help="入力の動画・音声ファイル（複数可）")
    _add_common(p)
    p.add_argument("-o", "--output", help="出力フォルダ（既定: プリセットの output.dir）")
    p.add_argument("-t", "--target", choices=["aup2", "exo", "both"], help="出力形式（既定: project.target）")
    p.add_argument("--no-cache", action="store_true", help="キャッシュを使わない")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("analyze", help="音量分布を表示し、しきい値を提案する")
    p.add_argument("input")
    _add_common(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("verify", help="2回実行して出力が一致するか（決定論性）を確認する")
    p.add_argument("input")
    _add_common(p)
    p.add_argument("-t", "--target", choices=["aup2", "exo", "both"], default="both")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("harvest", help="AviUtlで保存したサンプルからキー名を採取し、組み込み表と比較する")
    p.add_argument("sample", help=".aup2 / .object / .exo")
    p.set_defaults(func=cmd_harvest)

    p = sub.add_parser("transcribe", help="文字起こしだけ行い、JSONとSRTを書き出す（AI段）")
    p.add_argument("input")
    _add_common(p)
    p.add_argument("-o", "--output")
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("shortcut", help="ショートカットボタンのファイル（.object / .exo）を作る")
    p.add_argument("ids", nargs="*", help="ショートカットID")
    _add_common(p)
    p.add_argument("-o", "--output")
    p.add_argument("--all", action="store_true", help="すべて作る")
    p.add_argument("--list", action="store_true", help="一覧を表示")
    p.set_defaults(func=cmd_shortcut)

    p = sub.add_parser("gui", help="GUIを起動する")
    p.add_argument("input", nargs="?")
    p.add_argument("-p", "--preset")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("presets", help="プリセットの一覧")
    p.set_defaults(func=cmd_presets)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except DetCutError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("中断しました", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

