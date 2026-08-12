#!/usr/bin/env python3
"""Shared runtime discovery, UTF-8 subprocess, atomic JSON, and hashing helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


TOOLCHAIN_SCHEMA_VERSION = 1


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


configure_utf8_console()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sha256_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def command_args(program: str, *args: str) -> list[str]:
    if os.name == "nt" and Path(program).suffix.lower() in {".cmd", ".bat"}:
        return [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline([program, *args]),
        ]
    return [program, *args]


def utf8_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_text(
    program: str,
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command_args(program, *args),
        cwd=cwd,
        env=utf8_env(env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _valid_file(value: str | os.PathLike[str] | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return str(path.resolve()) if path.is_file() else None


def _which(command: str) -> str | None:
    found = shutil.which(command)
    return str(Path(found).resolve()) if found else None


def project_python(project: Path) -> str | None:
    relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return _valid_file(project / ".venv" / relative)


def ffmpeg_from_python(python: str | None) -> str | None:
    if not python:
        return None
    result = run_text(
        python,
        "-c",
        "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return _valid_file(result.stdout.strip().splitlines()[-1])


def find_browser(configured: str | None = None) -> str | None:
    candidates = [
        configured,
        os.environ.get("REMOTION_BROWSER_EXECUTABLE"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    return next((path for item in candidates if (path := _valid_file(item))), None)


def toolchain_path(project: Path) -> Path:
    return project / "build" / "toolchain.json"


def load_toolchain(project: Path | None) -> dict:
    if project is None or not toolchain_path(project).is_file():
        return {}
    try:
        data = json.loads(toolchain_path(project).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def discover_toolchain(project: Path | None = None, **overrides: str | None) -> dict:
    saved = load_toolchain(project)

    def choose(name: str, env_name: str, command: str) -> str | None:
        return (
            _valid_file(overrides.get(name))
            or _valid_file(os.environ.get(env_name))
            or _valid_file(saved.get(name))
            or _which(command)
        )

    python = choose("python", "PYTHON", "python") or str(Path(sys.executable).resolve())
    project_py = project_python(project) if project else None
    node = choose("node", "NODE", "node")
    pnpm = choose("pnpm", "PNPM", "pnpm")
    ffmpeg = choose("ffmpeg", "FFMPEG", "ffmpeg") or ffmpeg_from_python(project_py or python)
    browser = find_browser(overrides.get("browser") or saved.get("browser"))
    return {
        "schemaVersion": TOOLCHAIN_SCHEMA_VERSION,
        "python": python,
        "projectPython": project_py,
        "node": node,
        "pnpm": pnpm,
        "ffmpeg": ffmpeg,
        "browser": browser,
    }


def save_toolchain(project: Path, toolchain: dict) -> None:
    stable = {
        "schemaVersion": TOOLCHAIN_SCHEMA_VERSION,
        "python": toolchain.get("python"),
        "projectPython": toolchain.get("projectPython"),
        "node": toolchain.get("node"),
        "pnpm": toolchain.get("pnpm"),
        "ffmpeg": toolchain.get("ffmpeg"),
        "browser": toolchain.get("browser"),
    }
    atomic_json(toolchain_path(project), stable)


def toolchain_env(toolchain: dict, base: dict[str, str] | None = None) -> dict[str, str]:
    env = utf8_env(base)
    for key, env_name in (
        ("node", "NODE"),
        ("pnpm", "PNPM"),
        ("ffmpeg", "FFMPEG"),
        ("browser", "REMOTION_BROWSER_EXECUTABLE"),
    ):
        value = _valid_file(toolchain.get(key))
        if value:
            env[env_name] = value
    path_dirs: list[str] = []
    for key in ("node", "pnpm", "ffmpeg"):
        value = _valid_file(toolchain.get(key))
        if value:
            parent = str(Path(value).parent)
            if parent not in path_dirs:
                path_dirs.append(parent)
    if path_dirs:
        env["PATH"] = os.pathsep.join(path_dirs + [env.get("PATH", "")])
    return env


def fingerprint_files(project: Path, paths: Iterable[Path]) -> tuple[str, list[dict]]:
    entries: list[dict] = []
    root = project.resolve()
    for path in sorted({item.resolve() for item in paths}, key=lambda item: str(item).lower()):
        try:
            relative = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            relative = str(path)
        if path.is_file():
            entries.append({"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
        else:
            entries.append({"path": relative, "missing": True})
    return sha256_json(entries), entries
