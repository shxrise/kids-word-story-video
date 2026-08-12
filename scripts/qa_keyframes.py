#!/usr/bin/env python3
"""Plan and batch-render resumable QA keyframes with one Remotion bundle/browser."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from project_runtime import (
    atomic_json,
    command_args,
    discover_toolchain,
    fingerprint_files,
    sha256_file,
    sha256_json,
    toolchain_env,
)


def qa_inputs(project: Path, story: dict) -> tuple[str, list[dict]]:
    files = [
        project / "public" / "story" / "story.json",
        project / "scripts" / "render-qa.mjs",
        project / "package.json",
        project / "pnpm-lock.yaml",
        project / "remotion.config.ts",
    ]
    files.extend((project / "src").glob("**/*"))
    files.extend(
        project / "public" / str(scene.get("image", ""))
        for scene in story.get("scenes", [])
        if scene.get("image")
    )
    return fingerprint_files(project, [item for item in files if item.is_file()])


def build_jobs(story: dict, qa_input_hash: str) -> tuple[list[dict], list[dict], list[dict]]:
    fps = int(story["meta"]["fps"])
    pause_sec = max(0.0, float(story["meta"].get("targetPauseSec", 0)))
    intro_frames = math.ceil(float(story["meta"].get("introAudioDurationSec", 0)) * fps)
    offset = intro_frames
    targets: list[dict] = []
    states: list[dict] = [
        {"name": "intro-mid", "frame": max(0, intro_frames // 2)},
        {"name": "body-first", "frame": intro_frames},
    ]
    example_added = False
    for scene in story["scenes"]:
        highlights = scene.get("targetHighlights", [])
        if highlights:
            first = highlights[0]
            first_start = float(first["start"])
            first_duration = float(first["duration"])
            spoken_sample = first_start + min(0.08, max(0.001, first_duration / 2))
            targets.append({
                "scene": str(scene["id"]),
                "word": first["word"],
                "frame": offset + max(0, round(spoken_sample * fps)),
            })
            if not example_added:
                spoken_end = first_start + max(0, first_duration - pause_sec)
                states.append(
                    {"name": "word-spoken", "frame": offset + round(spoken_sample * fps)}
                )
                if pause_sec > 0:
                    states.append(
                        {"name": "word-pause", "frame": offset + round((spoken_end + pause_sec / 2) * fps)}
                    )
                states.append(
                    {"name": "word-after", "frame": offset + math.ceil((first_start + first_duration) * fps) + 1}
                )
                example_added = True
        offset += math.ceil(float(scene.get("audioDurationSec", 0)) * fps)

    jobs: list[dict] = []
    for index, item in enumerate(targets, start=1):
        item["file"] = f"qa/keyframes/target-{index:03d}.png"
        job_id = f"target-{index:03d}"
        job_hash = sha256_json({"input": qa_input_hash, "frame": item["frame"], "file": item["file"]})
        jobs.append({"id": job_id, "frame": item["frame"], "file": item["file"], "jobSha256": job_hash})
    for item in states:
        item["file"] = f"qa/keyframes/state-{item['name']}.png"
        job_id = f"state-{item['name']}"
        job_hash = sha256_json({"input": qa_input_hash, "frame": item["frame"], "file": item["file"]})
        jobs.append({"id": job_id, "frame": item["frame"], "file": item["file"], "jobSha256": job_hash})
    return jobs, targets, states


def contact_sheet(project: Path, targets: list[dict], ffmpeg: str, env: dict[str, str]) -> None:
    if not targets:
        return
    columns = 4
    rows = math.ceil(len(targets) / columns)
    source = project / "qa" / "keyframes" / "target-%03d.png"
    output = project / "qa" / "target-contact-sheet.png"
    result = subprocess.run(
        [
            ffmpeg, "-v", "error", "-y", "-framerate", "1", "-start_number", "1", "-i", str(source),
            "-vf", f"scale=320:180,tile={columns}x{rows}:padding=4:margin=4", "-frames:v", "1", str(output),
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"contact sheet failed: {result.stderr.strip()}")


def all_jobs_reusable(project: Path, progress_path: Path, input_hash: str, jobs: list[dict]) -> bool:
    if not progress_path.is_file():
        return False
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if progress.get("qaInputSha256") != input_hash:
        return False
    for job in jobs:
        saved = progress.get("completed", {}).get(job["id"], {})
        output = project / job["file"]
        if (
            saved.get("jobSha256") != job["jobSha256"]
            or not output.is_file()
            or saved.get("fileSha256") != sha256_file(output)
        ):
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--node")
    parser.add_argument("--pnpm")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--browser")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    story_path = project / "public" / "story" / "story.json"
    runner = project / "scripts" / "render-qa.mjs"
    if not story_path.is_file() or not runner.is_file():
        sys.exit("story.json or project scripts/render-qa.mjs is missing")
    story = json.loads(story_path.read_text(encoding="utf-8"))
    tools = discover_toolchain(
        project, node=args.node, pnpm=args.pnpm, ffmpeg=args.ffmpeg, browser=args.browser
    )
    if not tools.get("node") or not tools.get("ffmpeg"):
        sys.exit("Node.js and FFmpeg are required; run doctor.py with workspace runtime paths")
    env = toolchain_env(tools)
    input_hash, evidence = qa_inputs(project, story)
    jobs, targets, states = build_jobs(story, input_hash)
    work_path = project / "qa" / "work.json"
    progress_path = project / "qa" / "progress.json"
    work = {"schemaVersion": 1, "qaInputSha256": input_hash, "evidence": evidence, "jobs": jobs}
    atomic_json(work_path, work)
    (project / "qa" / "keyframes").mkdir(parents=True, exist_ok=True)
    if all_jobs_reusable(project, progress_path, input_hash, jobs):
        print(f"[qa] reuse all {len(jobs)} completed frames; bundle skipped")
    else:
        result = subprocess.run(
            command_args(str(tools["node"]), str(runner), str(project), str(work_path), str(progress_path)),
            cwd=project,
            env=env,
        )
        if result.returncode != 0:
            sys.exit(f"batch QA renderer failed with exit code {result.returncode}; rerun to resume completed frames")
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    for job in jobs:
        saved = progress.get("completed", {}).get(job["id"], {})
        output = project / job["file"]
        if saved.get("jobSha256") != job["jobSha256"] or not output.is_file():
            sys.exit(f"QA output incomplete: {job['id']}")
        if saved.get("fileSha256") != sha256_file(output):
            sys.exit(f"QA output hash mismatch: {job['id']}")
    contact_sheet(project, targets, str(tools["ffmpeg"]), env)
    manifest = {
        "schemaVersion": 2,
        "qaInputSha256": input_hash,
        "fps": int(story["meta"]["fps"]),
        "introFrames": math.ceil(float(story["meta"].get("introAudioDurationSec", 0)) * int(story["meta"]["fps"])),
        "targets": targets,
        "states": states,
        "renderedJobs": len(jobs),
        "batchRenderer": "single-bundle-single-browser",
    }
    atomic_json(project / "qa" / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
