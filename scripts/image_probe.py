#!/usr/bin/env python3
"""Record the generator's first test image dimensions before bulk generation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from normalize_image import TARGET_RATIO, image_size, sha256
from project_runtime import atomic_json
from pipeline_state import mark_stage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("source")
    parser.add_argument("--tolerance-pct", type=float, default=1.0)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    source = Path(args.source).resolve()
    if not project.is_dir() or not source.is_file():
        sys.exit("project or probe image is missing")
    width, height = image_size(source)
    error = abs((width / height) / TARGET_RATIO - 1) * 100
    report = {
        "schemaVersion": 1,
        "source": str(source),
        "sourceSha256": sha256(source),
        "width": width,
        "height": height,
        "aspectErrorPct": round(error, 6),
        "tolerancePct": args.tolerance_pct,
        "accepted": error <= args.tolerance_pct,
        "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    atomic_json(project / "build" / "image-probe.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["accepted"]:
        sys.exit(2)
    mark_stage(project, "image_probe_passed", {"sourceSha256": report["sourceSha256"]})


if __name__ == "__main__":
    main()
