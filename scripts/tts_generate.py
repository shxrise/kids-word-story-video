#!/usr/bin/env python3
"""Synthesize word-story narration with edge-tts and write char-level
typewriter timings back into public/story/story.json.

For each scene:
  - reads scene.zh, synthesizes MP3 to public/audio/scene-<id>.mp3
  - captures WordBoundary events for exact per-word timestamps
  - expands them to per-character reveal times (zhChars); punctuation between
    words inherits the previous word's end time so typing never stalls oddly
  - fills scene.audio / scene.audioDurationSec

Usage:
  python tts_generate.py /abs/path/to/project [--voice zh-CN-XiaoxiaoNeural]
                          [--rate +0%] [--force]

Requires the project-local environment created by doctor.py --repair. FFmpeg
may come from FFMPEG, PATH, or project-local imageio-ffmpeg.
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from duration_control import (
    record_duration_preflight,
    target_visual_duration_sec,
)
from project_runtime import discover_toolchain
from tts_providers import synthesize as provider_synthesize
from pipeline_state import fail_stage, mark_stage


def find_ffmpeg(project: Path) -> str:
    ffmpeg = discover_toolchain(project).get("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found; run doctor.py --project <project> --repair")
    return str(ffmpeg)


def audio_duration_sec(ffmpeg: str, path: Path) -> float:
    out = subprocess.run(
        [ffmpeg, "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stderr
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    if not m:
        sys.exit(f"could not read duration of {path}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def normalized_word(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def insert_silence_after_words(
    ffmpeg: str,
    source: Path,
    destination: Path,
    pause_points: list[float],
    pause_sec: float,
) -> None:
    """Insert deterministic silence after selected word-end timestamps."""
    if not pause_points or pause_sec <= 0:
        os.replace(source, destination)
        return

    source_duration = audio_duration_sec(ffmpeg, source)
    points = sorted({p for p in pause_points if 0 < p < source_duration})
    if not points:
        os.replace(source, destination)
        return

    filters = []
    inputs = []
    starts = [0.0, *points]
    ends = [*points, source_duration]
    for index, (start, end) in enumerate(zip(starts, ends)):
        filters.append(
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},"
            "asetpts=PTS-STARTPTS,aresample=24000,"
            f"aformat=sample_fmts=fltp:channel_layouts=mono[a{index}]"
        )
        inputs.append(f"[a{index}]")
        if index < len(points):
            filters.append(
                f"anullsrc=r=24000:cl=mono:d={pause_sec:.3f},"
                f"aformat=sample_fmts=fltp:channel_layouts=mono[s{index}]"
            )
            inputs.append(f"[s{index}]")

    filters.append(f"{''.join(inputs)}concat=n={len(inputs)}:v=0:a=1[out]")
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(destination),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        sys.exit(f"ffmpeg silence insertion failed for {source}:\n{proc.stderr}")
    source.unlink(missing_ok=True)


def apply_target_pauses(
    words: list,
    targets: dict[str, str] | set[str],
    pause_sec: float,
    visual_duration_sec: float,
) -> tuple[list, list, list]:
    """Shift audio boundaries for optional pauses and create independent visual events."""
    shifted = []
    highlights = []
    pause_points = []
    accumulated_pause = 0.0
    for word in words:
        adjusted = dict(word)
        adjusted["start"] = round(word["start"] + accumulated_pause, 3)
        adjusted["end"] = round(word["end"] + accumulated_pause, 3)
        token = normalized_word(word["text"])
        if token in targets:
            display_word = targets[token] if isinstance(targets, dict) else str(word["text"])
            spoken_duration = max(0.001, adjusted["end"] - adjusted["start"])
            highlights.append(
                {
                    "word": token,
                    "displayWord": display_word,
                    "start": adjusted["start"],
                    "spokenDurationSec": round(spoken_duration, 3),
                    "visualDurationSec": round(max(spoken_duration, visual_duration_sec), 3),
                }
            )
            if pause_sec > 0:
                pause_points.append(word["end"])
            accumulated_pause += pause_sec
        shifted.append(adjusted)
    return shifted, highlights, pause_points


def synthesize_with_retries(
    provider: str,
    text: str,
    voice: str,
    rate: str,
    out_path: Path,
    retries: int,
) -> list:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        out_path.unlink(missing_ok=True)
        try:
            return provider_synthesize(provider, text, voice, rate, out_path)
        except Exception as exc:  # Network and service errors vary by edge-tts version.
            last_error = exc
            if attempt < retries:
                delay = min(8, 2 ** (attempt - 1))
                print(f"TTS attempt {attempt}/{retries} failed; retrying in {delay}s: {exc}")
                time.sleep(delay)
    raise RuntimeError(f"TTS failed after {retries} attempts: {last_error}")


def input_hash(
    provider: str,
    text: str,
    voice: str,
    rate: str,
    pause_sec: float,
    targets: set[str],
) -> str:
    payload = json.dumps(
        {
            "provider": provider,
            "text": text,
            "voice": voice,
            "rate": rate,
            "pauseSec": pause_sec,
            "targets": sorted(targets),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def timing_input_hash(
    audio_hash: str, visual_duration_sec: float, target_spellings: dict[str, str]
) -> str:
    payload = json.dumps(
        {
            "ttsAudioInputHash": audio_hash,
            "targetVisualDurationSec": visual_duration_sec,
            "targetSpellings": sorted(target_spellings.items()),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def write_story_atomic(path: Path, story: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def char_timings(text: str, words: list) -> list:
    """Expand word boundaries to one reveal time per character of `text`.
    Characters not covered by any boundary (punctuation, spaces) appear
    together with the end of the previous spoken word."""
    chars = []
    pos = 0
    last_t = words[0]["start"] if words else 0.0
    for w in words:
        idx = text.find(w["text"], pos)
        if idx == -1:
            continue  # TTS sometimes normalizes text; skip unmatched boundary
        for i in range(pos, idx):
            chars.append({"c": text[i], "t": round(last_t, 3)})
        n = len(w["text"])
        for j in range(n):
            t = w["start"] + (w["end"] - w["start"]) * j / n
            chars.append({"c": text[idx + j], "t": round(t, 3)})
        last_t = w["end"]
        pos = idx + n
    for i in range(pos, len(text)):
        chars.append({"c": text[i], "t": round(last_t, 3)})
    return chars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="Remotion project directory")
    ap.add_argument("--provider", choices=("edge", "azure"), default="edge")
    ap.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    ap.add_argument("--rate", default="-15%")
    ap.add_argument("--force", action="store_true", help="re-synthesize existing audio")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument(
        "--duration-preflight",
        action="store_true",
        help="Generate actual TTS early and enforce the configured duration gate before illustration",
    )
    args = ap.parse_args()

    project = Path(args.project).resolve()
    story_path = project / "public" / "story" / "story.json"
    audio_dir = project / "public" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    story = json.loads(story_path.read_text(encoding="utf-8"))
    ffmpeg = find_ffmpeg(project)

    provider = story.get("meta", {}).get("ttsProvider", args.provider)
    voice = story.get("meta", {}).get("voice", args.voice)
    rate = story.get("meta", {}).get("rate", args.rate)
    pause_targets = {
        normalized_word(str(word)): str(word)
        for word in story.get("meta", {}).get("pauseTargets", [])
    }
    pause_sec = float(story.get("meta", {}).get("targetPauseSec", 0))
    if not math.isfinite(pause_sec) or pause_sec < 0:
        sys.exit("meta.targetPauseSec must be a finite nonnegative number")
    try:
        visual_duration_sec = target_visual_duration_sec(story.get("meta", {}))
    except ValueError as exc:
        sys.exit(str(exc))

    intro_title = str(story.get("meta", {}).get("introTitle", "")).strip()
    if not intro_title:
        sys.exit("meta.introTitle is required before TTS generation")
    intro_rel = "audio/intro-title.mp3"
    intro_mp3 = project / "public" / intro_rel
    intro_hash = input_hash(provider, intro_title, voice, rate, 0, set())
    if args.force or not intro_mp3.exists() or story["meta"].get("introTtsInputHash") != intro_hash:
        synthesize_with_retries(provider, intro_title, voice, rate, intro_mp3, args.retries)
    intro_dur = audio_duration_sec(ffmpeg, intro_mp3)
    story["meta"]["introAudio"] = intro_rel
    story["meta"]["introAudioDurationSec"] = round(intro_dur, 3)
    story["meta"]["introTtsInputHash"] = intro_hash
    write_story_atomic(story_path, story)
    print(f"intro title: {intro_dur:.2f}s -> {intro_rel}")

    for scene in story["scenes"]:
        rel = f"audio/scene-{scene['id']}.mp3"
        mp3 = project / "public" / rel
        audio_hash = input_hash(
            provider, scene["zh"], voice, rate, pause_sec, set(pause_targets),
        )
        timing_hash = timing_input_hash(audio_hash, visual_duration_sec, pause_targets)
        if (
            mp3.exists()
            and scene.get("zhChars")
            and scene.get("targetHighlights") is not None
            and scene.get("ttsAudioInputHash") == audio_hash
            and all(
                isinstance(item, dict) and float(item.get("spokenDurationSec", 0) or 0) > 0
                for item in scene.get("targetHighlights", [])
            )
            and not args.force
        ):
            if scene.get("ttsTimingInputHash") != timing_hash:
                for item in scene.get("targetHighlights", []):
                    item["displayWord"] = pause_targets.get(str(item.get("word", "")), str(item.get("word", "")))
                    item["visualDurationSec"] = round(
                        max(float(item["spokenDurationSec"]), visual_duration_sec), 3
                    )
                visual_end = max(
                    (
                        float(item["start"]) + float(item["visualDurationSec"])
                        for item in scene.get("targetHighlights", [])
                    ),
                    default=0.0,
                )
                scene["visualTailSec"] = round(
                    max(0.0, visual_end - float(scene.get("audioDurationSec", 0) or 0)), 3
                )
                scene["ttsTimingInputHash"] = timing_hash
                write_story_atomic(story_path, story)
                print(f"scene {scene['id']}: reused audio and refreshed visual timing")
            else:
                print(f"scene {scene['id']}: audio exists, skipping (use --force to redo)")
            continue
        raw_mp3 = mp3.with_suffix(".raw.mp3") if pause_targets and pause_sec > 0 else mp3
        words = synthesize_with_retries(provider, scene["zh"], voice, rate, raw_mp3, args.retries)
        highlights = []
        if pause_targets:
            words, highlights, pause_points = apply_target_pauses(
                words,
                pause_targets,
                pause_sec,
                visual_duration_sec,
            )
            expected_targets = [
                normalized_word(word)
                for word in re.findall(r"[A-Za-z]+", scene["zh"])
                if normalized_word(word) in pause_targets
            ]
            actual_targets = [item["word"] for item in highlights]
            if actual_targets != expected_targets:
                sys.exit(
                    f"target boundary mismatch in scene {scene['id']}: "
                    f"expected {expected_targets}, got {actual_targets}"
                )
            if pause_sec > 0:
                insert_silence_after_words(
                    ffmpeg, raw_mp3, mp3, pause_points, pause_sec
                )
        dur = audio_duration_sec(ffmpeg, mp3)
        scene["audio"] = rel
        scene["audioDurationSec"] = round(dur, 3)
        scene["zhChars"] = char_timings(scene["zh"], words)
        scene["targetHighlights"] = highlights
        visual_end = max(
            (
                float(item["start"]) + float(item["visualDurationSec"])
                for item in highlights
            ),
            default=0.0,
        )
        scene["visualTailSec"] = round(max(0.0, visual_end - dur), 3)
        scene["ttsAudioInputHash"] = audio_hash
        scene["ttsTimingInputHash"] = timing_hash
        write_story_atomic(story_path, story)
        print(f"scene {scene['id']}: {dur:.2f}s, {len(words)} words -> {rel}")

    write_story_atomic(story_path, story)
    if args.duration_preflight:
        report = record_duration_preflight(project, story)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["status"] != "passed":
            fail_stage(project, "duration_preflight_ready", str(report.get("reason")))
            sys.exit(2)
        mark_stage(
            project,
            "duration_preflight_ready",
            {
                "measurement": report["measurement"],
                "targetRangeSec": [
                    report["target"]["acceptableMinSec"],
                    report["target"]["acceptableMaxSec"],
                ],
                "estimatedDurationSec": report["estimatedDurationSec"],
            },
        )
    else:
        mark_stage(project, "narration_ready", {"provider": provider, "voice": voice, "rate": rate})
    print(f"updated {story_path}")


if __name__ == "__main__":
    main()
