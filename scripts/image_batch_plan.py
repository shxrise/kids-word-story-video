#!/usr/bin/env python3
"""Plan safe illustration batches while preserving explicit scene dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from project_runtime import atomic_json, sha256_json


MAX_PARALLEL_SCENES = 3
SERIAL_REASONS = {
    "continuous-action",
    "prop-state",
    "previous-image-reference",
    "manual",
}


def load_story(project: Path) -> dict:
    path = project / "public" / "story" / "story.json"
    if not path.is_file():
        raise ValueError(f"story file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def scene_contract(scene: dict) -> tuple[list[str], list[str]]:
    generation = scene.get("imageGeneration", {})
    if generation is None:
        generation = {}
    if not isinstance(generation, dict):
        raise ValueError(f"scene {scene.get('id')} imageGeneration must be an object")
    dependencies = generation.get("dependsOn", [])
    reasons = generation.get("serialReasons", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) and item.strip() for item in dependencies
    ):
        raise ValueError(f"scene {scene.get('id')} imageGeneration.dependsOn must be a string list")
    if not isinstance(reasons, list) or any(
        not isinstance(item, str) or item not in SERIAL_REASONS for item in reasons
    ):
        raise ValueError(f"scene {scene.get('id')} imageGeneration.serialReasons contains an unknown reason")
    return list(dict.fromkeys(map(str, dependencies))), list(dict.fromkeys(map(str, reasons)))


def passed_scene_ids(project: Path) -> list[str]:
    path = project / "public" / "story" / "visual-reviews.json"
    if not path.is_file():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8")).get("items", {})
    except json.JSONDecodeError:
        return []
    if not isinstance(items, dict):
        return []
    return sorted(
        str(scene_id)
        for scene_id, item in items.items()
        if isinstance(item, dict) and item.get("status") in {"passed", "accepted-minor"}
    )


def build_plan(
    story: dict, retry_ids: list[str], force_serial: bool, preserved_ids: list[str] | None = None
) -> dict:
    scenes = story.get("scenes", [])
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("story must contain scenes before illustration planning")
    scene_ids = [str(scene.get("id", "")).strip() for scene in scenes]
    if any(not item for item in scene_ids) or len(set(scene_ids)) != len(scene_ids):
        raise ValueError("scene ids must be non-empty and unique")
    order = {scene_id: index for index, scene_id in enumerate(scene_ids)}
    contracts: dict[str, tuple[list[str], list[str]]] = {}
    for scene in scenes:
        scene_id = str(scene["id"])
        dependencies, reasons = scene_contract(scene)
        unknown = sorted(set(dependencies) - set(scene_ids))
        if unknown:
            raise ValueError(f"scene {scene_id} has unknown image dependencies: {unknown}")
        future = [item for item in dependencies if order[item] >= order[scene_id]]
        if future:
            raise ValueError(f"scene {scene_id} image dependencies must be earlier scenes: {future}")
        contracts[scene_id] = dependencies, reasons

    retry = list(dict.fromkeys(retry_ids))
    preserved = [
        item for item in dict.fromkeys(preserved_ids or []) if item not in set(retry)
    ]
    unknown_preserved = sorted(set(preserved) - set(scene_ids))
    if unknown_preserved:
        raise ValueError(f"unknown preserved scene ids: {unknown_preserved}")
    if retry:
        unknown_retry = sorted(set(retry) - set(scene_ids))
        if unknown_retry:
            raise ValueError(f"unknown retry scene ids: {unknown_retry}")
        selected = [item for item in scene_ids if item in set(retry)]
        batches = [
            {
                "mode": "serial-retry",
                "sceneIds": [scene_id],
                "reason": "retry-or-affected-follow-up",
            }
            for scene_id in selected
        ]
        mode = "retry-serial"
    else:
        batches: list[dict] = []
        parallel: list[str] = []

        def flush_parallel() -> None:
            nonlocal parallel
            if parallel:
                batches.append({"mode": "parallel", "sceneIds": parallel, "reason": "independent-scenes"})
                parallel = []

        for scene_id in [item for item in scene_ids if item not in set(preserved)]:
            dependencies, reasons = contracts[scene_id]
            if force_serial or dependencies or reasons:
                flush_parallel()
                reason = "forced-serial" if force_serial else ",".join(reasons) or "scene-dependency"
                batches.append({"mode": "serial", "sceneIds": [scene_id], "reason": reason})
            else:
                parallel.append(scene_id)
                if len(parallel) == MAX_PARALLEL_SCENES:
                    flush_parallel()
        flush_parallel()
        mode = "forced-serial" if force_serial else "default"

    source = {
        "sceneOrder": scene_ids,
        "contracts": {
            scene_id: {"dependsOn": contracts[scene_id][0], "serialReasons": contracts[scene_id][1]}
            for scene_id in scene_ids
        },
        "retrySceneIds": retry,
        "forceSerial": force_serial,
        "preservedSceneIds": preserved,
    }
    return {
        "schemaVersion": 1,
        "mode": mode,
        "maxParallelScenes": MAX_PARALLEL_SCENES,
        "preserveExistingPassedImages": True,
        "referenceAndProbeImages": "serial-before-scene-batches",
        "retrySceneIds": retry,
        "forceSerial": force_serial,
        "preservedSceneIds": preserved,
        "inputSha256": sha256_json(source),
        "batches": batches,
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--retry-scene", action="append", default=[])
    parser.add_argument(
        "--force-serial",
        action="store_true",
        help="Use after rate limits, image confusion, or a measurable continuity/quality drop",
    )
    args = parser.parse_args()
    project = Path(args.project).resolve()
    if not project.is_dir():
        sys.exit(f"project directory missing: {project}")
    try:
        story = load_story(project)
        scene_ids = {str(scene.get("id", "")) for scene in story.get("scenes", [])}
        preserved = [scene_id for scene_id in passed_scene_ids(project) if scene_id in scene_ids]
        plan = build_plan(
            story, args.retry_scene, args.force_serial, preserved
        )
        path = project / "build" / "image-generation-plan.json"
        if path.is_file():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                if previous.get("inputSha256") == plan.get("inputSha256") and previous.get("createdAt"):
                    plan["createdAt"] = previous["createdAt"]
            except json.JSONDecodeError:
                pass
        atomic_json(path, plan)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        sys.exit(str(exc))
    print(json.dumps({**plan, "path": str(path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
