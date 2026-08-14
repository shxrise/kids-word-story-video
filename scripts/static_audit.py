#!/usr/bin/env python3
"""Cross-platform static policy audit without shell quoting or grep dependencies."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from project_runtime import atomic_json


RULES = {
    "crop-cover": re.compile(r"objectFit\s*:\s*['\"]cover['\"]"),
    "legacy-widescreen-remap": re.compile(r"markerYForWidescreen"),
    "three-two-art": re.compile(
        r"(?<![\d:])(?:native\s*)?3\s*:\s*2(?!\d)", re.IGNORECASE
    ),
    "gif-media": re.compile(r"\.gif\b", re.IGNORECASE),
    "video-generation": re.compile(r"(?:文生视频|图生视频|text[- ]to[- ]video|image[- ]to[- ]video)", re.IGNORECASE),
}
TEXT_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".json", ".css"}
SKIP_DIRS = {"node_modules", ".venv", ".git", "out", "build", "qa"}


def files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--skill", help="Also audit the Skill source directory")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    roots = [project]
    if args.skill:
        roots.append(Path(args.skill).resolve())
    findings = []
    for root in roots:
        for path in files(root):
            text = path.read_text(encoding="utf-8", errors="replace")
            for rule, pattern in RULES.items():
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append({"rule": rule, "file": str(path), "line": line, "match": match.group(0)})
    report = {"schemaVersion": 1, "status": "passed" if not findings else "failed", "roots": list(map(str, roots)), "findings": findings}
    atomic_json(project / "qa" / "static-audit.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
