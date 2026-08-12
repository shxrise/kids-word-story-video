#!/usr/bin/env python3
"""Validate the final MP4 and write a machine-readable delivery report."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from pipeline_state import mark_stage, set_review
from project_runtime import discover_toolchain, sha256_file


WORD_RE = re.compile(r"[A-Za-z]+")


def find_ffmpeg(project: Path) -> str:
    ffmpeg = discover_toolchain(project).get("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg unavailable; run doctor.py --project <project> --repair")
    return str(ffmpeg)


def expected_frames(story: dict) -> int:
    fps = int(story["meta"]["fps"])
    total = math.ceil(float(story["meta"].get("introAudioDurationSec", 0)) * fps)
    return total + sum(math.ceil(float(scene.get("audioDurationSec", 0)) * fps) for scene in story["scenes"])


def run_text(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def decode_frame_count(ffmpeg: str, video: Path) -> tuple[int | None, str | None]:
    null_device = "NUL" if os.name == "nt" else "/dev/null"
    proc = run_text(
        [
            ffmpeg, "-v", "error", "-progress", "pipe:1", "-nostats",
            "-i", str(video), "-map", "0:v:0", "-map", "0:a:0",
            "-f", "null", null_device,
        ]
    )
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()
    frames = [int(value) for value in re.findall(r"(?m)^frame=(\d+)$", proc.stdout)]
    return (frames[-1] if frames else None), None


def audio_analysis(ffmpeg: str, video: Path) -> dict:
    null_device = "NUL" if os.name == "nt" else "/dev/null"
    loudness_proc = run_text(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(video), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", null_device]
    )
    loudness_text = loudness_proc.stderr
    integrated = re.findall(r"(?m)^\s*I:\s*(-?[0-9.]+) LUFS", loudness_text)
    lra = re.findall(r"(?m)^\s*LRA:\s*([0-9.]+) LU", loudness_text)
    peaks = re.findall(r"(?m)^\s*Peak:\s*(-?[0-9.]+) dBFS", loudness_text)

    silence_proc = run_text(
        [ffmpeg, "-hide_banner", "-nostats", "-i", str(video), "-map", "0:a:0", "-af", "silencedetect=n=-50dB:d=2", "-f", "null", null_device]
    )
    silence_events = [line.strip() for line in silence_proc.stderr.splitlines() if "silence_start" in line or "silence_end" in line]
    return {
        "integratedLufs": float(integrated[-1]) if integrated else None,
        "loudnessRangeLu": float(lra[-1]) if lra else None,
        "truePeakDbfs": float(peaks[-1]) if peaks else None,
        "silenceOver2Sec": silence_events,
    }


def validate_video(project: Path, video: Path, decode: bool = True) -> tuple[dict, list[str], list[str]]:
    story_path = project / "public" / "story" / "story.json"
    if not story_path.is_file() or not video.is_file():
        raise RuntimeError("story.json or video is missing")
    story = json.loads(story_path.read_text(encoding="utf-8"))
    ffmpeg = find_ffmpeg(project)
    errors: list[str] = []
    warnings: list[str] = []
    fps = int(story["meta"].get("fps", 0))
    width = int(story["meta"].get("width", 0))
    height = int(story["meta"].get("height", 0))
    expected = expected_frames(story)
    expected_sec = expected / max(fps, 1)

    info_proc = run_text([ffmpeg, "-hide_banner", "-i", str(video)])
    info = info_proc.stderr
    lines = info.splitlines()
    video_lines = [line for line in lines if "Stream #" in line and "Video:" in line]
    audio_lines = [line for line in lines if "Stream #" in line and "Audio:" in line]
    if len(video_lines) != 1:
        errors.append(f"expected exactly one video stream, got {len(video_lines)}")
    if len(audio_lines) != 1:
        errors.append(f"expected exactly one audio stream, got {len(audio_lines)}")
    video_line = video_lines[0] if video_lines else ""
    audio_line = audio_lines[0] if audio_lines else ""
    if "Video: h264" not in video_line:
        errors.append("video codec must be H.264")
    if "Audio: aac" not in audio_line:
        errors.append("audio codec must be AAC")
    if f"{width}x{height}" not in video_line:
        errors.append(f"video resolution must be {width}x{height}")
    fps_values = re.findall(r"([0-9.]+) fps", video_line)
    actual_fps = float(fps_values[0]) if fps_values else None
    if actual_fps is None or abs(actual_fps - fps) > 0.001:
        errors.append(f"video fps must be {fps}, got {actual_fps}")

    duration_match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info)
    actual_duration = None
    if duration_match:
        actual_duration = int(duration_match.group(1)) * 3600 + int(duration_match.group(2)) * 60 + float(duration_match.group(3))
        # FFmpeg's human-readable duration is rounded to centiseconds.
        if abs(actual_duration - expected_sec) > 1 / max(fps, 1) + 0.011:
            errors.append(
                f"container duration {actual_duration:.3f}s differs from expected "
                f"{expected_sec:.3f}s by more than one frame"
            )
    else:
        errors.append("could not read container duration")

    decoded_frames = None
    if decode:
        decoded_frames, decode_error = decode_frame_count(ffmpeg, video)
        if decode_error:
            errors.append(f"full decode failed: {decode_error}")
        elif decoded_frames != expected:
            errors.append(f"decoded frame count must be {expected}, got {decoded_frames}")

    audio = audio_analysis(ffmpeg, video)
    if audio["truePeakDbfs"] is not None and audio["truePeakDbfs"] >= -0.1:
        errors.append(f"audio true peak is too high: {audio['truePeakDbfs']} dBFS")
    if audio["silenceOver2Sec"]:
        warnings.append("audio contains silence events longer than 2 seconds; inspect them")

    tokens = [match.group(0).lower() for scene in story["scenes"] for match in WORD_RE.finditer(str(scene.get("zh", "")))]
    counts = Counter(tokens)
    sfx_count = sum(len(scene.get("sfx", [])) for scene in story["scenes"])
    image_manifest_path = project / "public" / "story" / "image-sources.json"
    image_manifest = json.loads(image_manifest_path.read_text(encoding="utf-8")) if image_manifest_path.is_file() else {"assets": []}
    normalized_assets = image_manifest.get("assets", [])
    visual_reviews_path = project / "public" / "story" / "visual-reviews.json"
    visual_reviews = json.loads(visual_reviews_path.read_text(encoding="utf-8")) if visual_reviews_path.is_file() else {"items": {}}
    qa_manifest_path = project / "qa" / "manifest.json"
    render_plan_path = project / "build" / "render-plan.json"
    report = {
        "schemaVersion": 2,
        "status": "passed" if not errors else "failed",
        "video": str(video.resolve()),
        "storyData": str(story_path.resolve()),
        "bytes": video.stat().st_size,
        "sha256": sha256_file(video),
        "durationSec": actual_duration,
        "expectedDurationSec": expected_sec,
        "width": width,
        "height": height,
        "fps": actual_fps,
        "expectedFrames": expected,
        "decodedFrames": decoded_frames,
        "videoCodec": "h264" if "Video: h264" in video_line else None,
        "audioCodec": "aac" if "Audio: aac" in audio_line else None,
        "scenes": len(story["scenes"]),
        "targets": len(story["meta"].get("pauseTargets", [])),
        "targetOccurrences": len(tokens),
        "targetCounts": {str(word).lower(): counts[str(word).lower()] for word in story["meta"].get("pauseTargets", [])},
        "soundEffects": sfx_count,
        "tts": {
            "provider": story["meta"].get("ttsProvider"),
            "voice": story["meta"].get("voice"),
            "rate": story["meta"].get("rate"),
        },
        "visualSemanticReviews": {
            "manifest": str(visual_reviews_path.resolve()),
            "passed": sum(item.get("status") in {"passed", "accepted-minor"} for item in visual_reviews.get("items", {}).values()),
            "acceptedMinor": sum(item.get("status") == "accepted-minor" for item in visual_reviews.get("items", {}).values()),
            "total": len(visual_reviews.get("items", {})),
        },
        "qaManifest": str(qa_manifest_path.resolve()),
        "renderPlan": str(render_plan_path.resolve()),
        "imageNormalization": {
            "policy": image_manifest.get("policy"),
            "aspectTolerancePct": image_manifest.get("aspectTolerancePct"),
            "assetCount": len(normalized_assets),
            "maxAspectErrorPct": max((float(item.get("aspectErrorPct", 0)) for item in normalized_assets), default=0),
        },
        "audioAnalysis": audio,
        "subjectiveAudio": "pending-human",
        "oldProjectOverwritten": False,
        "warnings": warnings,
        "errors": errors,
    }
    return report, errors, warnings


def write_report(project: Path, report: dict) -> None:
    build = project / "build"
    build.mkdir(parents=True, exist_ok=True)
    json_path = build / "report.json"
    temp = json_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, json_path)
    md = (
        "# 成片验收报告\n\n"
        f"- 状态：{report['status']}\n"
        f"- 视频：`{report['video']}`\n"
        f"- 时长：{report['durationSec']} 秒\n"
        f"- 规格：{report['width']}×{report['height']}、{report['fps']}fps\n"
        f"- 帧数：{report['decodedFrames']} / {report['expectedFrames']}\n"
        f"- 编码：{report['videoCodec']} + {report['audioCodec']}\n"
        f"- 文件字节：{report['bytes']}\n"
        f"- SHA-256：`{report['sha256']}`\n"
        f"- 场景：{report['scenes']}；目标词事件：{report['targetOccurrences']}；音效：{report['soundEffects']}\n"
        f"- 主观试听：{report['subjectiveAudio']}\n"
    )
    (build / "report.md").write_text(md, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--video", help="Video path; defaults to out/story.mp4")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--subjective-audio-approved", action="store_true")
    parser.add_argument(
        "--accept-external-video",
        action="store_true",
        help="Explicitly accept an externally replaced out/story.mp4 as the rendered artifact",
    )
    args = parser.parse_args()
    project = Path(args.project).resolve()
    video = Path(args.video).resolve() if args.video else project / "out" / "story.mp4"
    try:
        report, errors, _ = validate_video(project, video, decode=True)
        if args.subjective_audio_approved:
            report["subjectiveAudio"] = "approved"
        if not errors:
            try:
                if not args.no_report:
                    if args.accept_external_video:
                        mark_stage(project, "rendered", {"source": "external-video-explicitly-accepted"})
                    write_report(project, report)
                    mark_stage(project, "mp4_validated", {"sha256": report["sha256"], "frames": report["decodedFrames"]})
                    if args.subjective_audio_approved:
                        set_review(project, "approved", {"source": "explicit approval"})
            except ValueError as exc:
                errors.append(str(exc))
        report["errors"] = errors
        report["status"] = "passed" if not errors else "failed"
        if not args.no_report and errors:
            write_report(project, report)
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        sys.exit(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
