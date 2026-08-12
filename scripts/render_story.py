#!/usr/bin/env python3
"""Render a story with a planned single-or-segmented Remotion strategy."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pipeline_state import fail_stage, load_state, mark_stage
from project_runtime import (
    command_args,
    discover_toolchain,
    fingerprint_files,
    sha256_json,
    toolchain_env,
)
from validate_mp4 import validate_video, write_report


SINGLE_RENDER_MAX_FRAMES = 9000
SEGMENT_FRAMES = 3000


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def run_logged(command: list[str], cwd: Path, log_path: Path, env: dict[str, str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {' '.join(command)}\n")
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert proc.stdout is not None
        last_bucket = -1
        for line in proc.stdout:
            log.write(line)
            match = re.search(r"(?:Rendered|Rendering|rendered|rendering)[^0-9]*(\d+)\s*/\s*(\d+)", line)
            if match and int(match.group(2)) > 0:
                bucket = int(int(match.group(1)) / int(match.group(2)) * 20)
                if bucket > last_bucket:
                    last_bucket = bucket
                    print(f"render progress: {min(bucket * 5, 100)}%", flush=True)
            elif not re.search(r"\b\d+\s*/\s*\d+\b", line):
                print(line, end="")
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"command failed with exit code {code}; see {log_path}")


def find_ffmpeg(project: Path) -> str:
    ffmpeg = discover_toolchain(project).get("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg unavailable")
    return str(ffmpeg)


def expected_frames(story: dict) -> int:
    fps = int(story["meta"]["fps"])
    return math.ceil(float(story["meta"].get("introAudioDurationSec", 0)) * fps) + sum(
        math.ceil(float(scene.get("audioDurationSec", 0)) * fps) for scene in story["scenes"]
    )


def require_visual_qa(project: Path) -> None:
    state = load_state(project)
    if state["stages"]["visual_qa_ready"]["status"] != "completed":
        raise RuntimeError("pipeline stage visual_qa_ready is not completed; refuse to render")


def segment_plan(total: int, fps: int, segment_frames: int, input_hash: str) -> dict:
    segments = []
    for index, start in enumerate(range(0, total, segment_frames), start=1):
        end = min(total - 1, start + segment_frames - 1)
        segments.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "frames": end - start + 1,
                "durationSec": (end - start + 1) / fps,
                "file": f"build/segments/segment-{index:02d}.mp4",
                "status": "pending",
            }
        )
    return {
        "schemaVersion": 1,
        "strategy": "segmented",
        "renderInputSha256": input_hash,
        "fps": fps,
        "totalFrames": total,
        "segmentFrames": segment_frames,
        "segments": segments,
    }


def render_command(pnpm: str, output: Path, crf: int, concurrency: int, frame_range: str | None = None) -> list[str]:
    args = [
        "exec", "remotion", "render", "StoryVideo", str(output),
        "--codec=h264", f"--crf={crf}", f"--concurrency={concurrency}", "--overwrite",
    ]
    if frame_range:
        args.append(f"--frames={frame_range}")
    return command_args(pnpm, *args)


def segment_is_valid(ffmpeg: str, path: Path, expected: int) -> bool:
    if not path.is_file():
        return False
    null_device = "NUL" if os.name == "nt" else "/dev/null"
    proc = subprocess.run(
        [
            ffmpeg, "-v", "error", "-progress", "pipe:1", "-nostats",
            "-i", str(path), "-map", "0:v:0", "-map", "0:a:0",
            "-f", "null", null_device,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    frames = [int(value) for value in re.findall(r"(?m)^frame=(\d+)$", proc.stdout)]
    return proc.returncode == 0 and bool(frames) and frames[-1] == expected


def preserve_previous(official: Path) -> None:
    if not official.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = official.with_name(f"story.previous-{stamp}.mp4")
    os.replace(official, backup)


def render_input(project: Path, story: dict) -> tuple[str, list[dict]]:
    public = project / "public"
    files = [
        project / "public" / "story" / "story.json",
        project / "qa" / "manifest.json",
        project / "package.json",
        project / "pnpm-lock.yaml",
        project / "remotion.config.ts",
    ]
    files.extend((project / "src").glob("**/*"))
    files.append(public / str(story.get("meta", {}).get("introAudio", "")))
    for scene in story.get("scenes", []):
        files.extend([
            public / str(scene.get("image", "")),
            public / str(scene.get("audio", "")),
        ])
    for asset in story.get("sfxCatalog", {}).values():
        if isinstance(asset, dict):
            files.append(public / str(asset.get("src", "")))
    return fingerprint_files(project, [path for path in files if str(path) and path.is_file()])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--pnpm")
    parser.add_argument("--node")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--browser")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--single-render-max-frames", type=int, default=SINGLE_RENDER_MAX_FRAMES, help=argparse.SUPPRESS)
    parser.add_argument("--segment-frames", type=int, default=SEGMENT_FRAMES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    if not project.is_dir():
        sys.exit(f"project missing: {project}")
    try:
        tools = discover_toolchain(
            project, node=args.node, pnpm=args.pnpm, ffmpeg=args.ffmpeg, browser=args.browser
        )
        if not tools.get("pnpm") or not tools.get("node") or not tools.get("ffmpeg"):
            raise RuntimeError("Node.js, pnpm, and FFmpeg are required; run doctor.py with workspace runtime paths")
        require_visual_qa(project)
        story = json.loads((project / "public" / "story" / "story.json").read_text(encoding="utf-8"))
        fps = int(story["meta"]["fps"])
        if (int(story["meta"]["width"]), int(story["meta"]["height"]), fps) != (1280, 720, 20):
            raise RuntimeError("render_story.py only accepts the fixed 1280x720, 20fps profile")
        total = expected_frames(story)
        out = project / "out"
        build = project / "build"
        out.mkdir(parents=True, exist_ok=True)
        build.mkdir(parents=True, exist_ok=True)
        official = out / "story.mp4"
        temp_final = out / "story.rendering.mp4"
        temp_final.unlink(missing_ok=True)
        log_path = build / "render.log"
        env = toolchain_env(tools)
        render_input_hash, render_evidence = render_input(project, story)

        if args.single_render_max_frames <= 0 or args.segment_frames <= 0:
            raise RuntimeError("render thresholds must be positive")
        if total <= args.single_render_max_frames:
            plan = {
                "schemaVersion": 1,
                "strategy": "single",
                "renderInputSha256": render_input_hash,
                "evidence": render_evidence,
                "thresholdFrames": args.single_render_max_frames,
                "totalFrames": total,
                "fps": fps,
            }
            atomic_json(build / "render-plan.json", plan)
            run_logged(render_command(str(tools["pnpm"]), temp_final, 18, args.concurrency), project, log_path, env)
        else:
            ffmpeg = str(tools["ffmpeg"])
            plan_path = build / "render-plan.json"
            plan = segment_plan(total, fps, args.segment_frames, render_input_hash)
            plan["evidence"] = render_evidence
            if plan_path.is_file():
                existing = json.loads(plan_path.read_text(encoding="utf-8"))
                if (
                    existing.get("strategy") == "segmented"
                    and existing.get("totalFrames") == total
                    and existing.get("segmentFrames") == args.segment_frames
                    and existing.get("fps") == fps
                    and existing.get("renderInputSha256") == render_input_hash
                ):
                    for current, old in zip(plan["segments"], existing.get("segments", [])):
                        old_path = project / old.get("file", "")
                        if old.get("status") == "completed" and segment_is_valid(
                            ffmpeg, old_path, int(current["frames"])
                        ):
                            current["status"] = "completed"
            atomic_json(plan_path, plan)
            for segment in plan["segments"]:
                path = project / segment["file"]
                path.parent.mkdir(parents=True, exist_ok=True)
                if segment["status"] == "completed" and path.is_file():
                    print(f"resume: keeping completed {path.name}")
                    continue
                run_logged(
                    render_command(str(tools["pnpm"]), path, 1, args.concurrency, f"{segment['start']}-{segment['end']}"),
                    project,
                    log_path,
                    env,
                )
                if not segment_is_valid(ffmpeg, path, int(segment["frames"])):
                    raise RuntimeError(f"segment validation failed: {path}")
                segment["status"] = "completed"
                atomic_json(plan_path, plan)

            inputs: list[str] = []
            filters: list[str] = []
            concat_inputs: list[str] = []
            for i, segment in enumerate(plan["segments"]):
                inputs.extend(["-i", str(project / segment["file"])])
                frames = int(segment["frames"])
                duration = frames / fps
                filters.append(f"[{i}:v]trim=end_frame={frames},setpts=N/({fps}*TB)[v{i}]")
                filters.append(f"[{i}:a]atrim=duration={duration:.9f},asetpts=N/SR/TB[a{i}]")
                concat_inputs.append(f"[v{i}][a{i}]")
            filters.append(f"{''.join(concat_inputs)}concat=n={len(plan['segments'])}:v=1:a=1[outv][outa]")
            command = [
                ffmpeg, "-hide_banner", *inputs, "-filter_complex", ";".join(filters),
                "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps), "-frames:v", str(total),
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total / fps:.9f}",
                "-movflags", "+faststart", "-y", str(temp_final),
            ]
            run_logged(command, project, log_path, env)

        # Remotion MP4s may retain one AAC tail packet. Trim the container to the
        # exact frame-derived duration without re-encoding either stream.
        ffmpeg = find_ffmpeg(project)
        trimmed = out / "story.trimmed.mp4"
        trimmed.unlink(missing_ok=True)
        run_logged(
            [
                ffmpeg, "-v", "error", "-y", "-i", str(temp_final),
                "-t", f"{total / fps:.9f}", "-c", "copy", "-movflags", "+faststart", str(trimmed),
            ],
            project,
            log_path,
            env,
        )
        os.replace(trimmed, temp_final)

        report, errors, _ = validate_video(project, temp_final, decode=True)
        if errors:
            raise RuntimeError("rendered temporary video failed validation: " + "; ".join(errors))
        preserve_previous(official)
        os.replace(temp_final, official)
        report["video"] = str(official.resolve())
        report["bytes"] = official.stat().st_size
        write_report(project, report)
        mark_stage(project, "rendered", {"strategy": plan["strategy"], "frames": total})
        mark_stage(project, "mp4_validated", {"sha256": report["sha256"], "frames": report["decodedFrames"]})
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        try:
            if project.is_dir():
                fail_stage(project, "rendered", str(exc))
        except (ValueError, OSError, json.JSONDecodeError):
            pass
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
