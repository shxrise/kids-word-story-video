#!/usr/bin/env python3
"""Create a standalone word-story video project from this skill's template."""

import argparse
import shutil
import sys
from pathlib import Path

from pipeline_state import mark_stage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Absolute output directory")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    template = skill_root / "assets" / "remotion-template"
    output = Path(args.output).expanduser().resolve()

    if not template.is_dir():
        sys.exit(f"template missing: {template}")
    if output.exists():
        sys.exit(f"refusing to overwrite existing path: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, output)
    for relative in (
        "public/assets",
        "public/audio",
        "public/reference",
        "public/raw",
        "public/sfx",
        "build",
        "out",
        "qa",
        "scripts",
    ):
        (output / relative).mkdir(parents=True, exist_ok=True)

    print(f"created standalone project: {output}")
    print(f"story file: {output / 'public/story/story.json'}")
    mark_stage(output, "initialized", {"createdBy": "new_project.py", "contract": "v2"})
    print("next: run scripts/doctor.py --project <project> --repair with this Skill")


if __name__ == "__main__":
    main()
