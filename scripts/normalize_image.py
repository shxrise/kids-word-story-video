#!/usr/bin/env python3
"""Archive a generated source image and normalize it to stable 1280x720."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from project_runtime import discover_toolchain


TARGET_WIDTH = 1280
TARGET_HEIGHT = 720
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT
DEFAULT_TOLERANCE_PCT = 1.0


def image_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return struct.unpack(">II", header[16:24])
        if header[:2] != b"\xff\xd8":
            raise ValueError("only PNG and JPEG source images are supported")
        handle.seek(2)
        while True:
            start = handle.read(1)
            if not start:
                break
            if start != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            length_raw = handle.read(2)
            if len(length_raw) != 2:
                break
            length = struct.unpack(">H", length_raw)[0]
            if marker and marker[0] in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                data = handle.read(5)
                height, width = struct.unpack(">HH", data[1:5])
                return width, height
            handle.seek(max(0, length - 2), 1)
    raise ValueError(f"could not read image dimensions: {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def find_ffmpeg(project: Path) -> str:
    ffmpeg = discover_toolchain(project).get("ffmpeg")
    if not ffmpeg:
        sys.exit("FFmpeg unavailable; run doctor.py --project <project> --repair")
    return str(ffmpeg)


def safe_public_path(public: Path, relative: str) -> tuple[str, Path]:
    normalized = relative.replace("\\", "/").lstrip("/")
    resolved = (public / normalized).resolve()
    try:
        resolved.relative_to(public.resolve())
    except ValueError:
        raise ValueError(f"path escapes project public directory: {relative}")
    return normalized, resolved


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("source")
    parser.add_argument("destination", help="Path relative to project public/, e.g. assets/scene-01.png")
    parser.add_argument("--tolerance-pct", type=float, default=DEFAULT_TOLERANCE_PCT)
    args = parser.parse_args()

    project = Path(args.project).resolve()
    public = project / "public"
    source = Path(args.source).resolve()
    if not public.is_dir() or not source.is_file():
        sys.exit("project public directory or source image is missing")
    try:
        destination_rel, destination = safe_public_path(public, args.destination)
        width, height = image_size(source)
    except ValueError as exc:
        sys.exit(str(exc))

    aspect_error_pct = abs((width / height) / TARGET_RATIO - 1) * 100
    if aspect_error_pct > args.tolerance_pct:
        sys.exit(
            f"source aspect ratio differs from 16:9 by {aspect_error_pct:.4f}%, "
            f"exceeding {args.tolerance_pct:.4f}%; reject and regenerate"
        )

    source_hash = sha256(source)
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
        "finalSha256": sha256(destination),
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
