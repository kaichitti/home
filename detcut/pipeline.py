"""処理全体の流れ（解析 → 判定 → カット → テロップ/SE/BGM/ズーム → 書き出し）。

  prepare()      ffprobe・入力ハッシュ・PCM抽出とエネルギー計算（キャッシュあり）
  detect()       発話判定とカットリスト（GUIのプレビューで何度も呼ぶ。速い）
  make_plan()    テロップ・SE・BGM・ズームを含むタイムラインを作る
  write_outputs()  .aup2 / .exo / cutlist.json / timeline.json / report.csv / run.json
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

import numpy as np

from detcut import __version__
from detcut.analysis.segments import SpeechResult, detect_speech
from detcut.asr.transcript import Transcript, load_transcript, to_srt
from detcut.common import (DetCutError, FileHashCache, canonical_json, dumps_json, sha256_bytes, sha256_text,
                           write_bytes)
from detcut.config import Config
from detcut.edit.bgm import BgmPiece, build_bgm
from detcut.edit.chapters import load_chapters
from detcut.edit.cutlist import CutList, build_cutlist
from detcut.edit.dictionary import load_dictionary
from detcut.edit.rules_se import SEEvent, build_se
from detcut.edit.telop import TelopResult, build_telops
from detcut.edit.zoom import plan_pieces
from detcut.media.pcm import PCM_ARGS_VERSION, EnergyData, extract_energies
from detcut.media.probe import FfmpegInfo, MediaInfo, ffmpeg_info, media_duration, probe
from detcut.report import build_report_csv
from detcut.timebase import TimeBase
from detcut.timeline.build import ChapterTitle, build_timeline
from detcut.timeline.model import Timeline
from detcut.writers.aup2 import write_aup2
from detcut.writers.effects import load_samples
from detcut.writers.exo import write_exo
from detcut.writers.paths import output_path

ANALYSIS_SR = 48000
WINDOW_MS = 10

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


@dataclass
class Prepared:
    input_path: str
    media: MediaInfo
    ffmpeg: FfmpegInfo
    input_sha256: str
    input_size: int
    energy: EnergyData
    tb: TimeBase
    width: int
    height: int
    total_src_frames: int | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Plan:
    prep: Prepared
    cfg: Config
    speech: SpeechResult
    cutlist: CutList
    transcript: Transcript | None
    transcript_info: dict[str, Any]
    telops: TelopResult | None
    se_events: list[SEEvent]
    bgm_pieces: list[BgmPiece]
    timeline: Timeline
    warnings: list[str]
    produced_transcript: bool = False


@dataclass
class RunResult:
    out_dir: str
    files: dict[str, str]          # 種別 -> パス
    hashes: dict[str, str]         # ファイル名 -> sha256
    warnings: list[str]
    stats: dict[str, Any]
    plan: Plan | None = None


# ---------------------------------------------------------------- prepare

def resolve_fps(cfg: Config, media: MediaInfo, warnings: list[str]) -> Fraction:
    v = cfg["project"]["fps"]
    if v != "auto":
        fps = Fraction(v)
        if media.has_video and media.fps and media.fps != fps:
            warnings.append(f"プロジェクトのfps({fps})と素材のfps({media.fps})が異なります。"
                            "従来版(.exo)では再生位置がずれることがあるため、同じfpsにするのがおすすめです。")
        return fps
    if media.has_video:
        for cand in (media.fps, media.avg_fps):
            if cand and 1 <= cand <= 240:
                return cand
    return Fraction(30)


def _analysis_cache_key(input_sha: str, ff: FfmpegInfo) -> str:
    return sha256_text(canonical_json({
        "input_sha256": input_sha, "ffmpeg": ff.version_sha256, "sr": ANALYSIS_SR,
        "window_ms": WINDOW_MS, "pcm_args": PCM_ARGS_VERSION,
    }))


def prepare(input_path: str, cfg: Config, log: Log = _noop, progress: Callable[[float], None] | None = None,
            use_cache: bool = True) -> Prepared:
    input_path = os.path.normpath(os.path.abspath(input_path))
    if not os.path.isfile(input_path):
        raise DetCutError(f"入力ファイルが見つかりません: {input_path}")
    warnings: list[str] = []
    ff = ffmpeg_info(cfg["ffmpeg"]["ffmpeg"])
    exp = cfg["ffmpeg"]["expected_version_sha256"]
    if exp and exp.lower() != ff.version_sha256:
        warnings.append(f"FFmpegのバージョンが推奨と異なります（{ff.version_line}）。結果が変わる可能性があります。")
    media = probe(input_path, cfg["ffmpeg"]["ffprobe"])
    if not media.has_audio:
        raise DetCutError("入力に音声トラックがありません（無音判定ができません）")
    if media.vfr_suspect:
        warnings.append(
            f"可変フレームレート(VFR)の可能性があります（r={media.fps}, avg={media.avg_fps}）。音ズレを防ぐため、"
            "固定フレームレートに変換してから使うのがおすすめです。例:\n"
            f"  ffmpeg -i \"{input_path}\" -fps_mode cfr -r {media.avg_fps or media.fps} -c:v libx264 -crf 18 -c:a copy out_cfr.mp4")
    fps = resolve_fps(cfg, media, warnings)
    tb = TimeBase(fps=fps, sample_rate=ANALYSIS_SR)

    cache_dir = cfg["cache"]["dir"] if (cfg["cache"]["enabled"] and use_cache) else None
    log("入力ファイルのハッシュを計算中…")
    input_sha = FileHashCache(cache_dir).get(input_path)
    energy = None
    key = _analysis_cache_key(input_sha, ff)
    npy = os.path.join(cache_dir, "analysis", key + ".npz") if cache_dir else None
    if npy and os.path.exists(npy):
        try:
            z = np.load(npy)
            energy = EnergyData(sample_rate=int(z["sr"]), window=int(z["window"]), energies=z["energies"],
                                total_samples=int(z["total"]), pcm_sha256=str(z["pcm_sha256"]))
            log("音声解析: キャッシュを使用します")
        except (OSError, KeyError, ValueError):
            energy = None
    if energy is None:
        log("音声を解析中（FFmpegでPCM抽出 → 10ms窓のエネルギー）…")
        expected = int(media.audio_duration * ANALYSIS_SR) if media.audio_duration else None
        energy = extract_energies(cfg["ffmpeg"]["ffmpeg"], input_path, ANALYSIS_SR, WINDOW_MS, progress, expected)
        if npy:
            os.makedirs(os.path.dirname(npy), exist_ok=True)
            tmp = npy[:-4] + ".tmp.npz"
            np.savez(tmp, sr=energy.sample_rate, window=energy.window, energies=energy.energies,
                     total=energy.total_samples, pcm_sha256=energy.pcm_sha256)
            os.replace(tmp, npy)

    pr = cfg["project"]
    width = pr["width"] if pr["width"] != "auto" else (media.width or 1920)
    height = pr["height"] if pr["height"] != "auto" else (media.height or 1080)
    total_src_frames = tb.seconds_to_frames_floor(media.video_duration) if (media.has_video and media.video_duration) else None
    return Prepared(input_path=input_path, media=media, ffmpeg=ff, input_sha256=input_sha,
                    input_size=os.path.getsize(input_path), energy=energy, tb=tb, width=int(width),
                    height=int(height), total_src_frames=total_src_frames, warnings=warnings)


def detect(prep: Prepared, cut_cfg: dict[str, Any]) -> tuple[SpeechResult, CutList]:
    e = prep.energy
    speech = detect_speech(e.energies, e.window, e.sample_rate, e.total_samples,
                           cut_cfg["speech_on_db"], cut_cfg["speech_off_db"],
                           cut_cfg["min_silence_ms"], cut_cfg["min_speech_ms"])
    cl = build_cutlist(speech, e.energies, cut_cfg, prep.tb, prep.total_src_frames)
    return speech, cl


# ---------------------------------------------------------------- plan

def make_plan(prep: Prepared, cfg: Config, log: Log = _noop, use_cache: bool = True) -> Plan:
    warnings = list(prep.warnings)
    tb = prep.tb
    speech, cl = detect(prep, cfg["cut"])
    if not cl.keeps:
        raise DetCutError("残す区間がありません（すべて無音と判定されました）。"
                          "`detcut analyze` で音量分布を確認し、cut.speech_on_db / speech_off_db を下げてください。")
    log(f"カット: {len(cl.keeps)} 区間を残し、{len(cl.cuts)} 区間をカット"
        f"（{cl.total_src_frames} → {cl.total_tl_frames} フレーム）")

    ffprobe = cfg["ffmpeg"]["ffprobe"]
    dur_cache: dict[str, Fraction | None] = {}

    def duration_fn(path: str) -> Fraction | None:
        if path not in dur_cache:
            dur_cache[path] = media_duration(path, ffprobe)
        return dur_cache[path]

    # --- テロップ
    tel = cfg["telop"]
    transcript = None
    tinfo: dict[str, Any] = {}
    telops = None
    produced = False
    if tel["enabled"]:
        if tel["transcript_file"]:
            transcript = load_transcript(tel["transcript_file"])
            tinfo = {"source": "file", "path": tel["transcript_file"]}
            log(f"文字起こし: ファイルを使用 {tel['transcript_file']}")
        else:
            from detcut.asr.whisper_stage import transcribe_cached
            cache_dir = cfg["cache"]["dir"] if cfg["cache"]["enabled"] else None
            transcript, tinfo = transcribe_cached(prep.input_path, prep.energy.pcm_sha256, tel["asr"], cache_dir,
                                                  cfg["ffmpeg"]["ffmpeg"], log, use_cache=use_cache)
            tinfo["source"] = "asr"
            produced = True
        rules = load_dictionary(tel["dictionary"])
        telops = build_telops(transcript, cl, tb, tel, rules)
        log(f"テロップ: {len(telops.telops)} 枚")

    # --- 章
    ch = cfg["chapters"]
    chapters = load_chapters(ch["file"], ch["items"])
    chapter_frames = [cl.src_frame_to_tl_or_next(tb.ms_to_frame_floor(c.at_ms)) for c in chapters]
    titles: list[ChapterTitle] = []
    if ch["title_telop"]:
        dur = max(1, tb.ms_to_frames_ceil(int(ch["title_ms"])))
        for i, (c, f) in enumerate(zip(chapters, chapter_frames)):
            if not c.title or f >= cl.total_tl_frames:
                continue
            nxt = chapter_frames[i + 1] if i + 1 < len(chapters) else cl.total_tl_frames
            end = min(f + dur, max(f + 1, nxt), cl.total_tl_frames) - 1
            if titles and f <= titles[-1].end:
                continue
            titles.append(ChapterTitle(f, end, c.title))

    # --- SE
    se_events: list[SEEvent] = []
    if cfg["se"]["enabled"]:
        se_events = build_se(cfg["se"], telops.telops if telops else [], cl, chapter_frames, tb, duration_fn, warnings)
        log(f"SE: {sum(1 for e in se_events if e.accepted)} 個（候補 {len(se_events)}）")

    # --- BGM
    bgm_pieces: list[BgmPiece] = []
    bgm = cfg["bgm"]
    if bgm["enabled"]:
        if not bgm["file"] or not os.path.isfile(bgm["file"]):
            warnings.append(f"BGMファイルが見つからないため配置しません: {bgm['file']}")
        else:
            speech_tl: list[tuple[int, int]] = []
            for s in speech.segments:
                f0 = tb.sample_to_frame_floor(s.start)
                f1 = tb.sample_to_frame_ceil(s.end)
                speech_tl.extend(cl.src_frames_to_tl_intervals(f0, f1))
            bgm_pieces = build_bgm(bgm, cl.total_tl_frames, speech_tl, tb, duration_fn(bgm["file"]))
            log(f"BGM: {len(bgm_pieces)} 区間")

    # --- ズーム・映像の区切り
    pieces = plan_pieces(cl.keeps, cfg["zoom"], tb)

    meta = {
        "tool": "detcut", "tool_version": __version__,
        "input_sha256": prep.input_sha256, "config_sha256": cfg.sha256,
    }
    timeline, w2 = build_timeline(
        input_path=prep.input_path, media=prep.media, tb=tb, width=prep.width, height=prep.height,
        cfg=cfg.data, cl=cl, pieces=pieces, telops=telops.telops if telops else [],
        chapter_titles=titles, se_events=se_events, bgm_pieces=bgm_pieces, meta=meta,
    )
    warnings.extend(w2)
    return Plan(prep=prep, cfg=cfg, speech=speech, cutlist=cl, transcript=transcript, transcript_info=tinfo,
                telops=telops, se_events=se_events, bgm_pieces=bgm_pieces, timeline=timeline, warnings=warnings,
                produced_transcript=produced)


# ---------------------------------------------------------------- outputs

def _read(path: str | None, encoding: str = "utf-8-sig") -> str | None:
    if not path:
        return None
    try:
        data = open(path, "rb").read()
    except OSError as e:
        raise DetCutError(f"ファイルを読めません: {path}") from e
    if encoding == "cp932":
        return data.decode("cp932", errors="replace")
    return data.decode(encoding)


def asset_hashes(cfg: Config, plan: Plan) -> dict[str, str]:
    paths: list[str] = []
    pr, tel = cfg["project"], cfg["telop"]
    for p in (pr["template_aup2"], pr["object_samples_aup2"], pr["object_samples_exo"],
              tel["style_template"], tel["style_template_exo"], tel["dictionary"],
              tel["transcript_file"] if tel["enabled"] else None, cfg["chapters"]["file"],
              cfg["bgm"]["file"] if cfg["bgm"]["enabled"] else None):
        if p:
            paths.append(p)
    paths.extend(sorted({e.file for e in plan.se_events if e.accepted}))
    cache = FileHashCache(cfg["cache"]["dir"] if cfg["cache"]["enabled"] else None)
    out = {}
    for p in paths:
        out[p] = cache.get(p) if os.path.isfile(p) else "missing"
    return out


def write_outputs(plan: Plan, out_dir: str | None = None, target: str | None = None) -> RunResult:
    cfg = plan.cfg
    prep = plan.prep
    out_dir = os.path.normpath(os.path.abspath(out_dir or cfg["output"]["dir"]))
    os.makedirs(out_dir, exist_ok=True)
    target = target or cfg["project"]["target"]
    stem = Path(prep.input_path).stem
    o = cfg["output"]
    path_fn = lambda p: output_path(p, o["path_map"], o["windows_paths"])  # noqa: E731
    warnings = list(plan.warnings)
    files: dict[str, str] = {}
    blobs: dict[str, bytes] = {}
    template_version = None

    if target in ("aup2", "both"):
        data, w, template_version = write_aup2(
            plan.timeline,
            template_text=_read(cfg["project"]["template_aup2"]),
            samples=load_samples(cfg["project"]["object_samples_aup2"]),
            style_template_text=_read(cfg["telop"]["style_template"]),
            scene=int(cfg["project"]["scene"]),
            audio_mode=cfg["project"]["aup2_audio"],
            path_fn=path_fn,
        )
        warnings.extend(w)
        blobs[f"{stem}.aup2"] = data
        files["aup2"] = f"{stem}.aup2"
    if target in ("exo", "both"):
        data, w = write_exo(
            plan.timeline,
            samples=load_samples(cfg["project"]["object_samples_exo"]),
            style_template_text=_read(cfg["telop"]["style_template_exo"], "cp932"),
            path_fn=path_fn,
        )
        warnings.extend(w)
        blobs[f"{stem}.exo"] = data
        files["exo"] = f"{stem}.exo"

    meta = {"input_sha256": prep.input_sha256, "config_sha256": cfg.sha256, "tool_version": __version__}
    if o["cutlist_json"]:
        blobs[f"{stem}.cutlist.json"] = dumps_json(plan.cutlist.to_json(meta)).encode("utf-8")
        files["cutlist"] = f"{stem}.cutlist.json"
    if o["timeline_json"]:
        blobs[f"{stem}.timeline.json"] = dumps_json(plan.timeline.to_json()).encode("utf-8")
        files["timeline"] = f"{stem}.timeline.json"
    if o["report_csv"]:
        blobs[f"{stem}.report.csv"] = build_report_csv(plan.cutlist, plan.telops, plan.se_events,
                                                         plan.bgm_pieces, plan.timeline)
        files["report"] = f"{stem}.report.csv"
    if plan.produced_transcript and plan.transcript is not None:
        blobs[f"{stem}.transcript.json"] = plan.transcript.dumps().encode("utf-8")
        blobs[f"{stem}.srt"] = to_srt(plan.transcript).encode("utf-8")
        files["transcript"] = f"{stem}.transcript.json"
        files["srt"] = f"{stem}.srt"

    hashes = {name: sha256_bytes(b) for name, b in sorted(blobs.items())}
    cl = plan.cutlist
    stats = {
        "keeps": len(cl.keeps), "cuts": len(cl.cuts),
        "src_frames": cl.total_src_frames, "tl_frames": cl.total_tl_frames,
        "src_ms": cl.tb.frame_to_ms(cl.total_src_frames), "tl_ms": cl.tb.frame_to_ms(cl.total_tl_frames),
        "reduction_percent": (100 - cl.total_tl_frames * 100 // cl.total_src_frames) if cl.total_src_frames else 0,
        "telops": len(plan.telops.telops) if plan.telops else 0,
        "se": sum(1 for e in plan.se_events if e.accepted),
        "bgm_pieces": len(plan.bgm_pieces),
        "clips": len(plan.timeline.clips),
    }
    run = {
        "tool": {"name": "detcut", "version": __version__, "python": platform.python_version(),
                 "numpy": np.__version__, "platform": sys.platform},
        "ffmpeg": {"version": prep.ffmpeg.version_line, "version_sha256": prep.ffmpeg.version_sha256},
        "input": {"path": prep.input_path, "sha256": prep.input_sha256, "size": prep.input_size,
                  "pcm_sha256": prep.energy.pcm_sha256, "media": prep.media.summary()},
        "project": {"fps": prep.tb.fps, "width": prep.width, "height": prep.height, "target": target,
                    "aup2_template_version": template_version},
        "config_sha256": cfg.sha256,
        "config": cfg.hashed_view,
        "assets": asset_hashes(cfg, plan),
        "transcript": plan.transcript_info,
        "outputs": hashes,
        "stats": stats,
        "warnings": warnings,
    }
    blobs[f"{stem}.run.json"] = dumps_json(run).encode("utf-8")
    files["run"] = f"{stem}.run.json"
    for name, data in blobs.items():
        write_bytes(os.path.join(out_dir, name), data)
    return RunResult(out_dir=out_dir, files={k: os.path.join(out_dir, v) for k, v in files.items()},
                     hashes=hashes, warnings=warnings, stats=stats, plan=plan)


def run(input_path: str, cfg: Config, out_dir: str | None = None, target: str | None = None, log: Log = _noop,
        progress: Callable[[float], None] | None = None, use_cache: bool = True) -> RunResult:
    prep = prepare(input_path, cfg, log, progress, use_cache)
    plan = make_plan(prep, cfg, log, use_cache)
    return write_outputs(plan, out_dir, target)
