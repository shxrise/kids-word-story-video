#!/usr/bin/env python3
"""Run the project TypeScript compiler with the saved absolute Node executable."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from project_runtime import load_toolchain, utf8_env


def typecheck_command(project: Path) -> list[str]:
    toolchain = load_toolchain(project)
    saved_node = str(toolchain.get("node", "")).strip()
    if not saved_node:
        raise ValueError(
            "saved Node path is missing; run doctor.py --project <project> --repair"
        )
    node = Path(saved_node)
    if not node.is_absolute() or not node.is_file():
        raise ValueError(f"saved Node path is not an absolute executable file: {saved_node}")

    tsc = project / "node_modules" / "typescript" / "bin" / "tsc"
    if not tsc.is_file():
        raise ValueError(
            "TypeScript compiler is missing; run doctor.py --project <project> --repair"
        )
    return [str(node.resolve()), str(tsc.resolve()), "--noEmit"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        sys.exit(f"project directory is missing: {project}")
    try:
        command = typecheck_command(project)
    except ValueError as exc:
        sys.exit(str(exc))

    proc = subprocess.run(
        command,
        cwd=project,
        env=utf8_env(os.environ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 0:
        sys.exit(proc.returncode)
    print(
        json.dumps(
            {"status": "passed", "node": command[0], "typescript": command[1]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
