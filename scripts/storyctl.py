#!/usr/bin/env python3
"""Small, atomic edits for story.json so agents do not hand-patch repeated JSON."""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import math
import re
import sys
from pathlib import Path

from project_runtime import atomic_json


FEMALE_VOICE = "zh-CN-XiaoxiaoNeural"
WORD_RE = re.compile(r"[A-Za-z]+")


def story_path(project: Path) -> Path:
    return project / "public" / "story" / "story.json"


def load(project: Path) -> tuple[Path, dict]:
    path = story_path(project)
    if not path.is_file():
        sys.exit(f"story file missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return path, data


def scene_by_id(story: dict, scene_id: str) -> dict:
    scene = next((item for item in story.get("scenes", []) if str(item.get("id")) == scene_id), None)
    if not scene:
        raise ValueError(f"unknown scene id: {scene_id}")
    return scene


def json_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def normalized_target_sequence(text: str, targets: set[str]) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text) if token.lower() in targets]


def require_minor_change(label: str, old: str, new: str, ratio: float, delta_fraction: float) -> None:
    if not new.strip():
        raise ValueError(f"{label} cannot be empty")
    allowed_delta = max(10, math.ceil(max(1, len(old)) * delta_fraction))
    if abs(len(new) - len(old)) > allowed_delta or SequenceMatcher(None, old, new).ratio() < ratio:
        raise ValueError(f"{label} change is too large; make only a local, minor adjustment")


def semantic_retries_exhausted(project: Path, scene_id: str) -> bool:
    path = project / "public" / "story" / "visual-reviews.json"
    if not path.is_file():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    item = data.get("items", {}).get(scene_id, {})
    history = item.get("history", []) if isinstance(item.get("history"), list) else []
    retries = sum(entry.get("status") == "retry-required" for entry in history)
    rejected = any(entry.get("status") == "rejected" for entry in history)
    return retries >= int(data.get("policy", {}).get("maxSemanticRetries", 2)) and rejected


def replace_minor_requirement(requirements: dict, field: str, old: str, new: str) -> None:
    values = requirements.get(field, [])
    if not isinstance(values, list) or old not in values:
        raise ValueError(f"{field} entry to replace was not found: {old}")
    require_minor_change(field, old, new, 0.55, 0.35)
    values[values.index(old)] = new


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-meta")
    init.add_argument("--title", required=True)
    init.add_argument("--targets", nargs="+", required=True)
    init.add_argument("--voice", default=FEMALE_VOICE)
    init.add_argument("--rate", default="-15%")
    init.add_argument("--tts-provider", choices=("edge", "azure"), default="edge")

    meta = sub.add_parser("set-meta")
    meta.add_argument("key")
    meta.add_argument("value")

    bible = sub.add_parser("set-visual-bible")
    bible.add_argument("--style", required=True)
    bible.add_argument("--palette", required=True)
    bible.add_argument("--reference", default="reference/characters.png")

    character = sub.add_parser("add-character")
    character.add_argument("id")
    character.add_argument("--name", required=True)
    character.add_argument("--role", required=True)
    character.add_argument("--appearance", required=True)
    character.add_argument("--must-keep", action="append", required=True)

    add_scene = sub.add_parser("add-scene")
    add_scene.add_argument("id")
    add_scene.add_argument("--title", required=True)
    add_scene.add_argument("--zh", required=True)
    add_scene.add_argument("--image", required=True)
    add_scene.add_argument("--prompt", required=True)
    add_scene.add_argument("--character", action="append", default=[])
    add_scene.add_argument("--must-show", action="append", required=True)
    add_scene.add_argument("--must-not-show", action="append", default=[])
    add_scene.add_argument("--action", required=True)
    add_scene.add_argument("--continuity", action="append", default=[])

    marker = sub.add_parser("set-marker")
    marker.add_argument("scene")
    marker.add_argument("word")
    marker.add_argument("--x", type=float, required=True)
    marker.add_argument("--y", type=float, required=True)
    marker.add_argument("--size", type=float, default=140)
    marker.add_argument("--source", choices=("visual-review", "tts-boundary", "scene-default"), default="visual-review")
    marker.add_argument("--confidence", type=float, default=1.0)
    marker.add_argument("--reviewer", required=True)

    requirements = sub.add_parser("set-visual-requirements")
    requirements.add_argument("scene")
    requirements.add_argument("--must-show", action="append", default=[])
    requirements.add_argument("--must-not-show", action="append", default=[])
    requirements.add_argument("--action", required=True)
    requirements.add_argument("--continuity", action="append", default=[])

    adjust = sub.add_parser("adjust-scene")
    adjust.add_argument("scene")
    adjust.add_argument("--zh")
    adjust.add_argument("--prompt")
    adjust.add_argument("--action")
    adjust.add_argument("--replace-must-show", nargs=2, action="append", metavar=("OLD", "NEW"), default=[])
    adjust.add_argument("--replace-must-not-show", nargs=2, action="append", metavar=("OLD", "NEW"), default=[])
    adjust.add_argument("--replace-continuity", nargs=2, action="append", metavar=("OLD", "NEW"), default=[])
    adjust.add_argument("--reason", required=True)

    sfx = sub.add_parser("add-sfx")
    sfx.add_argument("scene")
    sfx.add_argument("asset_id")
    sfx.add_argument("--start", type=float, required=True)
    sfx.add_argument("--duration", type=float, required=True)
    sfx.add_argument("--volume", type=float, required=True)
    sfx.add_argument("--fade-in", type=float, default=0.12)
    sfx.add_argument("--fade-out", type=float, default=0.18)
    sfx.add_argument("--purpose", required=True)

    sub.add_parser("summary")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    path, story = load(project)
    try:
        if args.command == "init-meta":
            targets = [item.strip() for item in args.targets if item.strip()]
            if len(targets) != len(set(item.lower() for item in targets)):
                raise ValueError("targets must be unique")
            story.setdefault("meta", {}).update({
                "schemaVersion": 2,
                "introTitle": args.title,
                "pauseTargets": targets,
                "voice": args.voice,
                "rate": args.rate,
                "ttsProvider": args.tts_provider,
            })
            story["meta"].setdefault("targetPauseSec", 0.0)
        elif args.command == "set-meta":
            if args.key in {"width", "height", "imageWidth", "imageHeight", "fps"}:
                raise ValueError("fixed output profile fields cannot be edited")
            value = json_value(args.value)
            if args.key == "targetPauseSec":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("targetPauseSec must be a finite nonnegative number")
                value = float(value)
            story.setdefault("meta", {})[args.key] = value
        elif args.command == "set-visual-bible":
            story["visualBible"] = {
                "stylePrompt": args.style,
                "palette": args.palette,
                "characters": story.get("visualBible", {}).get("characters", []),
                "referenceImage": args.reference.replace("\\", "/"),
            }
        elif args.command == "add-character":
            characters = story.setdefault("visualBible", {}).setdefault("characters", [])
            if any(str(item.get("id")) == args.id for item in characters):
                raise ValueError(f"duplicate character id: {args.id}")
            characters.append({
                "id": args.id, "name": args.name, "role": args.role,
                "appearance": args.appearance, "mustKeep": args.must_keep,
            })
        elif args.command == "add-scene":
            scenes = story.setdefault("scenes", [])
            if any(str(item.get("id")) == args.id for item in scenes):
                raise ValueError(f"duplicate scene id: {args.id}")
            known = {str(item.get("id")) for item in story.get("visualBible", {}).get("characters", [])}
            unknown = sorted(set(args.character) - known)
            if unknown:
                raise ValueError(f"unknown character ids: {unknown}")
            scenes.append({
                "id": args.id, "title": args.title, "zh": args.zh, "en": "",
                "image": args.image.replace("\\", "/"), "imagePrompt": args.prompt,
                "characterIds": args.character,
                "visualRequirements": {
                    "mustShow": args.must_show, "mustNotShow": args.must_not_show,
                    "action": args.action, "continuity": args.continuity,
                },
                "targetMarkers": {}, "sfx": [],
            })
        elif args.command == "set-marker":
            if not (0 <= args.x <= 100 and 0 <= args.y <= 100 and 0 <= args.confidence <= 1):
                raise ValueError("marker x/y must be 0..100 and confidence must be 0..1")
            scene = scene_by_id(story, args.scene)
            scene.setdefault("targetMarkers", {})[args.word.lower()] = {
                "x": args.x, "y": args.y, "size": args.size,
                "source": args.source, "confidence": args.confidence, "reviewer": args.reviewer,
            }
        elif args.command == "set-visual-requirements":
            scene_by_id(story, args.scene)["visualRequirements"] = {
                "mustShow": args.must_show,
                "mustNotShow": args.must_not_show,
                "action": args.action,
                "continuity": args.continuity,
            }
        elif args.command == "adjust-scene":
            if not semantic_retries_exhausted(project, args.scene):
                raise ValueError("adjust-scene is allowed only after the initial image and two semantic retries are exhausted")
            if not any(value is not None for value in (args.zh, args.prompt, args.action)) and not any(
                (args.replace_must_show, args.replace_must_not_show, args.replace_continuity)
            ):
                raise ValueError("adjust-scene requires at least one of --zh, --prompt, or --action")
            if not args.reason.strip():
                raise ValueError("adjust-scene requires a specific reason")
            scene = scene_by_id(story, args.scene)
            if scene.get("minorVisualAdjustments"):
                raise ValueError("only one minor visual/story adjustment is allowed per scene")
            changed = []
            if args.zh is not None and args.zh != scene.get("zh", ""):
                old_zh = str(scene.get("zh", ""))
                require_minor_change("narration", old_zh, args.zh, 0.72, 0.25)
                targets = {str(item).lower() for item in story.get("meta", {}).get("pauseTargets", [])}
                if normalized_target_sequence(old_zh, targets) != normalized_target_sequence(args.zh, targets):
                    raise ValueError("narration adjustment must preserve the target-word sequence exactly")
                scene["zh"] = args.zh
                for key in ("audio", "audioDurationSec", "zhChars", "enChars", "targetHighlights", "ttsInputHash"):
                    scene.pop(key, None)
                changed.append("zh")
            if args.action is not None and args.action != scene.get("visualRequirements", {}).get("action", ""):
                old_action = str(scene.get("visualRequirements", {}).get("action", ""))
                require_minor_change("action", old_action, args.action, 0.55, 0.35)
                scene.setdefault("visualRequirements", {})["action"] = args.action
                changed.append("visualRequirements.action")
            if args.prompt is not None and args.prompt != scene.get("imagePrompt", ""):
                if "16:9" not in args.prompt:
                    raise ValueError("adjusted image prompt must retain native 16:9")
                require_minor_change("image prompt", str(scene.get("imagePrompt", "")), args.prompt, 0.40, 0.45)
                scene["imagePrompt"] = args.prompt
                changed.append("imagePrompt")
            requirements = scene.setdefault("visualRequirements", {})
            for field, replacements in (
                ("mustShow", args.replace_must_show),
                ("mustNotShow", args.replace_must_not_show),
                ("continuity", args.replace_continuity),
            ):
                if len(replacements) > 1:
                    raise ValueError(f"only one {field} entry may be adjusted per scene")
                for old, new in replacements:
                    replace_minor_requirement(requirements, field, old, new)
                    changed.append(f"visualRequirements.{field}")
            if not changed:
                raise ValueError("adjust-scene did not change any value")
            scene.setdefault("minorVisualAdjustments", []).append({
                "reason": args.reason.strip(),
                "changedFields": changed,
            })
        elif args.command == "add-sfx":
            scene = scene_by_id(story, args.scene)
            cues = scene.setdefault("sfx", [])
            if len(cues) >= 2:
                raise ValueError(f"scene {args.scene} already has the maximum of two sound effects")
            cues.append({
                "assetId": args.asset_id, "startSec": args.start, "durationSec": args.duration,
                "volume": args.volume, "fadeInSec": args.fade_in, "fadeOutSec": args.fade_out,
                "purpose": args.purpose,
            })
        else:
            summary = {
                "schemaVersion": story.get("meta", {}).get("schemaVersion"),
                "title": story.get("meta", {}).get("introTitle"),
                "voice": story.get("meta", {}).get("voice"),
                "ttsProvider": story.get("meta", {}).get("ttsProvider"),
                "targets": story.get("meta", {}).get("pauseTargets", []),
                "scenes": len(story.get("scenes", [])),
                "visualRequirementsReady": sum(bool(item.get("visualRequirements")) for item in story.get("scenes", [])),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return
    except ValueError as exc:
        sys.exit(str(exc))
    atomic_json(path, story)
    print(json.dumps({"updated": str(path), "command": args.command}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
