"""任意の文字起こし段（faster-whisper）とキャッシュ。

AIを使うのはここだけ。決定論性のために:
  - モデル名とモデルファイル(model.bin)のハッシュを記録・照合
  - temperature は単一値（既定 0.0）で渡し、温度フォールバックを無効化
  - beam_size・language・VAD・cpu_threads を固定（スレッド数で演算順序が変わりうるため）
  - CPU + int8 を推奨（GPU演算は非決定的になりうる）
  - 結果を transcript JSON に保存し、音声ハッシュと設定ハッシュが同じなら再計算しない
"""

from __future__ import annotations

import os
from importlib import metadata
from typing import Any, Callable

from detcut.asr.transcript import TSegment, Transcript, Word, load_transcript
from detcut.common import DetCutError, canonical_json, sha256_file, sha256_text, write_bytes


def _pkg_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def asr_settings(asr: dict[str, Any]) -> dict[str, Any]:
    keys = ("engine", "model", "model_path", "model_sha256", "device", "compute_type", "cpu_threads",
            "language", "beam_size", "temperature", "vad_filter", "condition_on_previous_text", "initial_prompt")
    return {k: asr.get(k) for k in keys}


def cache_key(pcm_sha256: str, asr: dict[str, Any]) -> str:
    return sha256_text(canonical_json({
        "pcm_sha256": pcm_sha256,
        "asr": asr_settings(asr),
        "faster_whisper": _pkg_version("faster-whisper"),
        "ctranslate2": _pkg_version("ctranslate2"),
        "stage_version": 1,
    }))


def transcribe_cached(
    input_path: str,
    pcm_sha256: str,
    asr: dict[str, Any],
    cache_dir: str | None,
    ffmpeg: str,
    log: Callable[[str], None] = print,
    use_cache: bool = True,
) -> tuple[Transcript, dict[str, Any]]:
    key = cache_key(pcm_sha256, asr)
    cache_path = os.path.join(cache_dir, "transcripts", f"{key}.json") if cache_dir else None
    if use_cache and cache_path and os.path.exists(cache_path):
        log("文字起こし: キャッシュを使用します")
        t = load_transcript(cache_path)
        return t, {"cache_key": key, **t.meta}

    t = run_whisper(input_path, asr, ffmpeg, log)
    t.meta["cache_key"] = key
    t.meta["pcm_sha256"] = pcm_sha256
    if cache_path:
        write_bytes(cache_path, t.dumps().encode("utf-8"))
    return t, {"cache_key": key, **t.meta}


def resolve_model_dir(asr: dict[str, Any]) -> str:
    if asr.get("model_path"):
        if not os.path.isdir(asr["model_path"]):
            raise DetCutError(f"telop.asr.model_path が見つかりません: {asr['model_path']}")
        return asr["model_path"]
    from faster_whisper.utils import download_model  # type: ignore
    return download_model(asr["model"])


def model_sha256(model_dir: str) -> str | None:
    p = os.path.join(model_dir, "model.bin")
    return sha256_file(p) if os.path.exists(p) else None


def run_whisper(input_path: str, asr: dict[str, Any], ffmpeg: str, log: Callable[[str], None]) -> Transcript:
    if asr.get("engine") != "faster-whisper":
        raise DetCutError("telop.asr.engine が none のため文字起こしできません。telop.transcript_file を指定してください。")
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise DetCutError(
            "faster-whisper がインストールされていません。\n"
            "  pip install faster-whisper\n"
            "または、手元の字幕を telop.transcript_file（.srt / .json）に指定してください。") from e
    from detcut.media.pcm import extract_float_pcm

    model_dir = resolve_model_dir(asr)
    msha = model_sha256(model_dir)
    if asr.get("model_sha256") and msha and asr["model_sha256"].lower() != msha:
        raise DetCutError(
            f"モデルファイルのハッシュが設定と一致しません。\n  設定: {asr['model_sha256']}\n  実際: {msha}\n"
            "モデルが更新された可能性があります（決定論性を保つため中止しました）。")
    log(f"文字起こし: モデル {asr['model']} を読み込み中（{asr['device']}, {asr['compute_type']}）")
    model = WhisperModel(model_dir, device=asr["device"], compute_type=asr["compute_type"],
                         cpu_threads=int(asr["cpu_threads"]), num_workers=1)
    audio = extract_float_pcm(ffmpeg, input_path, 16000)
    duration_ms = len(audio) * 1000 // 16000
    segments_iter, info = model.transcribe(
        audio,
        language=asr.get("language"),
        beam_size=int(asr["beam_size"]),
        temperature=float(asr["temperature"]),
        vad_filter=bool(asr["vad_filter"]),
        word_timestamps=True,
        condition_on_previous_text=bool(asr["condition_on_previous_text"]),
        initial_prompt=asr.get("initial_prompt"),
    )
    segs: list[TSegment] = []
    for s in segments_iter:
        words = [Word(int(round(w.start * 1000)), int(round(w.end * 1000)), w.word) for w in (s.words or [])]
        segs.append(TSegment(int(round(s.start * 1000)), int(round(s.end * 1000)), s.text, words))
        if duration_ms:
            log(f"文字起こし: {min(100, segs[-1].end_ms * 100 // duration_ms)}%")
    meta = {
        "engine": "faster-whisper",
        "faster_whisper": _pkg_version("faster-whisper"),
        "ctranslate2": _pkg_version("ctranslate2"),
        "model": asr["model"],
        "model_sha256": msha,
        "language": getattr(info, "language", asr.get("language")),
        "settings": asr_settings(asr),
    }
    return Transcript(segs, meta)
