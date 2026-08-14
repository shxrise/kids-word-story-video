#!/usr/bin/env python3
"""Archive a generated source image and normalize it to stable 1280x720."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from project_runtime import atomic_json, discover_toolchain, image_size, safe_child, sha256_file


TARGET_WIDTH = 1280
TARGET_HEIGHT = 720
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT
DEFAULT_TOLERANCE_PCT = 1.0


def find_ffmpeg(project: Path) -> str:
    ffmpeg = discover_toolchain(project).get("ffmpeg")
    if not ffmpeg:
        sys.exit("FFmpeg unavailable; run doctor.py --project <project> --repair")
    return str(ffmpeg)


def safe_public_path(public: Path, relative: str) -> tuple[str, Path]:
    return safe_child(public, relative, "public asset path")


def destination_for_scene(project: Path, scene_id: str) -> str:
    story_path = project / "public" / "story" / "story.json"
    try:
        story = json.loads(story_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"story contract is missing: {story_path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"story contract is invalid JSON: {exc}")

    if scene_id == "reference":
        destination = str(story.get("visualBible", {}).get("referenceImage", "")).strip()
        if not destination:
            raise ValueError("story.visualBible.referenceImage is missing")
        expected_prefix = "reference/"
    else:
        matches = [
            scene for scene in story.get("scenes", []) if str(scene.get("id", "")) == scene_id
        ]
        if len(matches) != 1:
            raise ValueError(f"scene ID must identify exactly one story scene: {scene_id}")
        destination = str(matches[0].get("image", "")).strip()
        if not destination:
            raise ValueError(f"scene {scene_id} has no image filename in story.json")
        expected_prefix = "assets/"

    normalized = destination.replace("\\", "/").lstrip("/")
    if not normalized.startswith(expected_prefix):
        raise ValueError(
            f"story image path for {scene_id} must be under public/{expected_prefix}: {destination}"
        )
    if Path(normalized).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError(f"story image path has an unsupported extension: {destination}")
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("source")
    parser.add_argument(
        "scene_id",
        help="Scene ID from story.json; use the reserved ID 'reference' for the character reference",
    )
    parser.add_argument("--tolerance-pct", type=float, default=DEFAULT_TOLERANCE_PCT)
    args = parser.parse_args()

    project = Path(args.project).resolve()
    public = project / "public"
    source = Path(args.source).resolve()
    if not public.is_dir() or not source.is_file():
        sys.exit("project public directory or source image is missing")
    try:
        destination_rel, destination = safe_public_path(
            public, destination_for_scene(project, args.scene_id)
        )
        width, height = image_size(source)
    except ValueError as exc:
        sys.exit(str(exc))

    aspect_error_pct = abs((width / height) / TARGET_RATIO - 1) * 100
    if aspect_error_pct > args.tolerance_pct:
        sys.exit(
            f"source aspect ratio differs from 16:9 by {aspect_error_pct:.4f}%, "
            f"exceeding {args.tolerance_pct:.4f}%; reject and regenerate"
        )

    source_hash = sha256_file(source)
    raw_ext = source.suffix.lower() if source.suffix.lower() in {".png", ".jpg", ".jpeg"} else ".png"
    raw_rel = f"raw/{Path(destination_rel).stem}-{source_hash[:12]}{raw_ext}"
    _, raw_path = safe_public_path(public, raw_rel)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if not raw_path.exists():
        shutil.copy2(source, raw_path)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.stem + ".normalizing" + destination.suffix)
    if (width, height) == (TARGET_WIDTH, TARGET_HEIGHT):
        shutil.copy2(source, temp)
        action = "copy"
    else:
        ffmpeg = find_ffmpeg(project)
        proc = subprocess.run(
            [
                ffmpeg, "-v", "error", "-y", "-i", str(source),
                "-vf", f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:flags=lanczos",
                "-frames:v", "1", str(temp),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            temp.unlink(missing_ok=True)
            sys.exit(f"FFmpeg image normalization failed: {proc.stderr.strip()}")
        action = "lanczos-scale"
    os.replace(temp, destination)

    manifest_path = public / "story" / "image-sources.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schemaVersion": 1,
            "policy": "stable-lanczos",
            "target": {"width": TARGET_WIDTH, "height": TARGET_HEIGHT},
            "aspectTolerancePct": args.tolerance_pct,
            "assets": [],
        }
    entry = {
        "final": destination_rel,
        "raw": raw_rel,
        "sourceWidth": width,
        "sourceHeight": height,
        "aspectErrorPct": round(aspect_error_pct, 6),
        "scaleX": round(TARGET_WIDTH / width, 8),
        "scaleY": round(TARGET_HEIGHT / height, 8),
        "action": action,
        "sourceSha256": source_hash,
        "finalSha256": sha256_file(destination),
        "normalizedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    old_entries = [item for item in manifest.get("assets", []) if item.get("final") == destination_rel]
    assets = [item for item in manifest.get("assets", []) if item.get("final") != destination_rel]
    assets.append(entry)
    manifest["assets"] = sorted(assets, key=lambda item: item["final"])
    atomic_json(manifest_path, manifest)
    referenced_raw = {str(item.get("raw", "")) for item in manifest["assets"]}
    for old in old_entries:
        old_raw = str(old.get("raw", ""))
        if old_raw and old_raw not in referenced_raw:
            try:
                _, old_raw_path = safe_public_path(public, old_raw)
                old_raw_path.unlink(missing_ok=True)
            except ValueError:
                pass
    print(json.dumps(entry, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
