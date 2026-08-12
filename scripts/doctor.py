#!/usr/bin/env python3
"""Discover, persist, check, and safely repair project-local dependencies."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

from project_runtime import (
    discover_toolchain,
    project_python,
    run_text,
    save_toolchain,
)


MIN_PYTHON = (3, 10)
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
WARN_FREE_BYTES = 8 * 1024 * 1024 * 1024


def version(program: str | None, *args: str) -> str | None:
    if not program:
        return None
    result = run_text(program, *args)
    if result.returncode != 0:
        return None
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0] if lines else None


def module_available(python: str | None, module: str) -> bool:
    return bool(python and run_text(python, "-c", f"import {module}").returncode == 0)


def repair_project(
    project: Path,
    python: str,
    pnpm: str | None,
    tts_provider: str,
    actions: list[str],
    errors: list[str],
) -> None:
    py = project_python(project)
    if not py:
        result = run_text(python, "-m", "venv", str(project / ".venv"))
        if result.returncode != 0:
            errors.append(f"failed to create project .venv: {result.stderr.strip()}")
            return
        actions.append("created project .venv")
        py = project_python(project)
    if not py:
        errors.append("project .venv Python was not created")
        return

    requirements = [project / "requirements.txt"]
    if tts_provider == "azure":
        requirements.append(project / "requirements-azure.txt")
    for requirement in requirements:
        if not requirement.is_file():
            errors.append(f"requirements file missing: {requirement}")
            continue
        result = run_text(
            py,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirement),
        )
        if result.returncode != 0:
            errors.append(f"Python dependency repair failed for {requirement.name}: {result.stderr.strip()}")
        else:
            actions.append(f"installed {requirement.name}")

    if not (project / "package.json").is_file() or not (project / "pnpm-lock.yaml").is_file():
        errors.append("package.json or pnpm-lock.yaml is missing")
    elif not pnpm:
        errors.append("pnpm not found; pass --pnpm from the Codex workspace runtime")
    else:
        result = run_text(pnpm, "install", "--frozen-lockfile", cwd=project)
        if result.returncode != 0:
            errors.append(f"Node dependency repair failed: {result.stderr.strip()}")
        else:
            actions.append("installed Node dependencies from pnpm-lock.yaml")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", help="Existing generated project directory")
    parser.add_argument("--repair", action="store_true", help="Repair project-local dependencies only")
    parser.add_argument("--python")
    parser.add_argument("--node")
    parser.add_argument("--pnpm")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--browser")
    parser.add_argument("--tts-provider", choices=("edge", "azure"), default="edge")
    args = parser.parse_args()

    project = Path(args.project).resolve() if args.project else None
    errors: list[str] = []
    warnings: list[str] = []
    actions: list[str] = []
    if args.repair and project is None:
        errors.append("--repair requires --project")
    if project is not None and not project.is_dir():
        errors.append(f"project directory missing: {project}")

    tools = discover_toolchain(
        project,
        python=args.python,
        node=args.node,
        pnpm=args.pnpm,
        ffmpeg=args.ffmpeg,
        browser=args.browser,
    )
    python = tools.get("python")
    python_version = version(python, "--version")
    if not python or not python_version:
        errors.append("Python 3.10+ not found")
    else:
        matched = re.search(r"(\d+)\.(\d+)", python_version)
        if not matched or tuple(map(int, matched.groups())) < MIN_PYTHON:
            errors.append(f"Python 3.10+ is required, got {python_version}")
    if not tools.get("node"):
        errors.append("Node.js not found; pass --node from the Codex workspace runtime")
    if not tools.get("pnpm"):
        errors.append("pnpm not found; pass --pnpm from the Codex workspace runtime")

    if args.repair and project and project.is_dir() and python:
        repair_project(project, python, tools.get("pnpm"), args.tts_provider, actions, errors)
        tools = discover_toolchain(
            project,
            python=args.python,
            node=args.node,
            pnpm=args.pnpm,
            ffmpeg=args.ffmpeg,
            browser=args.browser,
        )

    runtime_python = tools.get("projectPython") or python
    provider_module = "edge_tts" if args.tts_provider == "edge" else "azure.cognitiveservices.speech"
    tts_ok = module_available(runtime_python, provider_module)
    if not tts_ok:
        message = f"TTS provider module unavailable: {provider_module}"
        (errors if project else warnings).append(message)
    if args.tts_provider == "azure":
        if not (os.environ.get("AZURE_SPEECH_KEY") or os.environ.get("SPEECH_KEY")):
            errors.append("Azure TTS requires AZURE_SPEECH_KEY (or SPEECH_KEY)")
        if not (os.environ.get("AZURE_SPEECH_REGION") or os.environ.get("SPEECH_REGION")):
            errors.append("Azure TTS requires AZURE_SPEECH_REGION (or SPEECH_REGION)")
    if not tools.get("ffmpeg"):
        errors.append("FFmpeg unavailable; project-local imageio-ffmpeg should provide it after repair")
    if not tools.get("browser"):
        warnings.append("Chrome/Edge not found; Remotion may need its own browser binary")

    disk_root = project or Path.cwd()
    free_bytes = shutil.disk_usage(disk_root).free
    if free_bytes < MIN_FREE_BYTES:
        errors.append("less than 2 GB free disk space")
    elif free_bytes < WARN_FREE_BYTES:
        warnings.append("less than 8 GB free disk space; long or segmented renders may run out of space")

    if project and project.is_dir():
        save_toolchain(project, tools)
    report = {
        "ok": not errors,
        "schemaVersion": 2,
        "project": str(project) if project else None,
        "toolchain": tools,
        "versions": {
            "python": python_version,
            "node": version(tools.get("node"), "--version"),
            "pnpm": version(tools.get("pnpm"), "--version"),
        },
        "ttsProvider": args.tts_provider,
        "ttsProviderReady": tts_ok,
        "freeDiskGB": round(free_bytes / (1024**3), 2),
        "actions": actions,
        "warnings": warnings,
        "errors": errors,
        "systemModified": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
