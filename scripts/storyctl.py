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

from duration_control import (
    DEFAULT_DURATION_TARGET,
    DEFAULT_INTRO_TAIL_SEC,
    DEFAULT_TARGET_VISUAL_DURATION_SEC,
    duration_target,
    finite_number,
)
from project_runtime import atomic_json


FEMALE_VOICE = "zh-CN-XiaoxiaoNeural"
WORD_RE = re.compile(r"[A-Za-z]+")
CHINESE_TITLE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff《》！？·]+")
CHINESE_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
TARGET_RE = re.compile(r"[A-Za-z]+")
SERIAL_REASONS = ("continuous-action", "prop-state", "previous-image-reference", "manual")


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


def validate_intro_title(title: str) -> str:
    value = title.strip()
    if not CHINESE_TITLE_RE.fullmatch(value):
        raise ValueError("intro title must use Chinese text and title punctuation only, with no letters or digits")
    chinese_length = len(CHINESE_CHAR_RE.findall(value))
    if not 4 <= chinese_length <= 18:
        raise ValueError("intro title must be a complete Chinese story name of 4–18 characters; 6–10 is preferred")
    return value


def add_action_contract_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--critical-action", action="store_true")
    parser.add_argument("--action-subject")
    parser.add_argument("--body-part-or-tool")
    parser.add_argument("--action-object")
    parser.add_argument("--contact")
    parser.add_argument("--relative-position")
    parser.add_argument("--direction")
    parser.add_argument("--result")
    parser.add_argument("--forbid-alternative", action="append", default=[])


def critical_action_from_args(args: argparse.Namespace) -> dict | None:
    fields = {
        "subject": args.action_subject,
        "bodyPartOrTool": args.body_part_or_tool,
        "object": args.action_object,
        "contact": args.contact,
        "relativePosition": args.relative_position,
        "direction": args.direction,
        "result": args.result,
    }
    provided = args.critical_action or any(value is not None for value in fields.values()) or bool(
        args.forbid_alternative
    )
    if not provided:
        return None
    missing = [key for key, value in fields.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"critical action is missing required details: {missing}")
    return {
        key: str(value).strip() for key, value in fields.items()
    } | {"forbiddenAlternatives": [item.strip() for item in args.forbid_alternative if item.strip()]}


def action_prompt_clause(action: dict) -> str:
    forbidden = action.get("forbiddenAlternatives", [])
    suffix = f"；不得替代为：{'、'.join(forbidden)}" if forbidden else ""
    return (
        f"关键动作合同：{action['subject']}使用{action['bodyPartOrTool']}作用于{action['object']}；"
        f"接触方式：{action['contact']}；相对位置：{action['relativePosition']}；"
        f"运动方向：{action['direction']}；动作结果：{action['result']}{suffix}。"
    )


def without_action_prompt_clause(prompt: str) -> str:
    marker = "关键动作合同："
    return prompt.split(marker, 1)[0].rstrip("。 ") if marker in prompt else prompt.rstrip()


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
    add_scene.add_argument("--depends-on", action="append", default=[])
    add_scene.add_argument("--serial-reason", action="append", choices=SERIAL_REASONS, default=[])
    add_action_contract_args(add_scene)

    marker = sub.add_parser("set-marker")
    marker.add_argument("scene")
    marker.add_argument("word")
    marker.add_argument("--x", type=float, required=True)
    marker.add_argument("--y", type=float, required=True)
    marker.add_argument("--source", choices=("visual-review", "tts-boundary", "scene-default"), default="visual-review")
    marker.add_argument("--confidence", type=float, default=1.0)
    marker.add_argument("--reviewer", required=True)

    requirements = sub.add_parser("set-visual-requirements")
    requirements.add_argument("scene")
    requirements.add_argument("--must-show", action="append", default=[])
    requirements.add_argument("--must-not-show", action="append", default=[])
    requirements.add_argument("--action", required=True)
    requirements.add_argument("--continuity", action="append", default=[])
    add_action_contract_args(requirements)

    adjust = sub.add_parser("adjust-scene")
    adjust.add_argument("scene")
    adjust.add_argument("--zh")
    adjust.add_argument("--prompt")
    adjust.add_argument("--action")
    adjust.add_argument("--replace-must-show", nargs=2, action="append", metavar=("OLD", "NEW"), default=[])
    adjust.add_argument("--replace-must-not-show", nargs=2, action="append", metavar=("OLD", "NEW"), default=[])
    adjust.add_argument("--replace-continuity", nargs=2, action="append", metavar=("OLD", "NEW"), default=[])
    adjust.add_argument("--reason", required=True)

    sub.add_parser("summary")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    path, story = load(project)
    try:
        if args.command == "init-meta":
            targets = [item.strip() for item in args.targets if item.strip()]
            if not targets or any(not TARGET_RE.fullmatch(item) for item in targets):
                raise ValueError("targets must contain ASCII English letters only")
            if len(targets) != len(set(item.lower() for item in targets)):
                raise ValueError("targets must be unique")
            story.setdefault("meta", {}).update({
                "schemaVersion": 2,
                "introTitle": validate_intro_title(args.title),
                "pauseTargets": targets,
                "voice": args.voice,
                "rate": args.rate,
                "ttsProvider": args.tts_provider,
            })
            story["meta"].setdefault("targetPauseSec", 0.0)
            story["meta"].setdefault(
                "targetVisualDurationSec", DEFAULT_TARGET_VISUAL_DURATION_SEC
            )
            story["meta"].setdefault("introTailSec", DEFAULT_INTRO_TAIL_SEC)
            story["meta"].setdefault("durationTarget", dict(DEFAULT_DURATION_TARGET))
        elif args.command == "set-meta":
            if args.key in {"width", "height", "imageWidth", "imageHeight", "fps"}:
                raise ValueError("fixed output profile fields cannot be edited")
            value = json_value(args.value)
            if args.key == "targetPauseSec":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("targetPauseSec must be a finite nonnegative number")
                value = float(value)
            elif args.key == "targetVisualDurationSec":
                value = finite_number(value, "targetVisualDurationSec", minimum=0.05)
            elif args.key == "introTailSec":
                value = finite_number(value, "introTailSec")
            elif args.key == "durationTarget":
                value = duration_target({"durationTarget": value})
            elif args.key == "introTitle":
                value = validate_intro_title(str(value))
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
            dependencies = list(dict.fromkeys(args.depends_on))
            known_scene_ids = {str(item.get("id")) for item in scenes}
            unknown_dependencies = sorted(set(dependencies) - known_scene_ids)
            if unknown_dependencies:
                raise ValueError(f"image dependencies must refer to earlier scenes: {unknown_dependencies}")
            critical_action = critical_action_from_args(args)
            prompt = without_action_prompt_clause(args.prompt.strip())
            if critical_action:
                prompt = f"{prompt.rstrip('。 ')}。{action_prompt_clause(critical_action)}"
            visual_requirements = {
                "mustShow": args.must_show, "mustNotShow": args.must_not_show,
                "action": args.action, "continuity": args.continuity,
            }
            if critical_action:
                visual_requirements["criticalAction"] = critical_action
            scenes.append({
                "id": args.id, "title": args.title, "zh": args.zh,
                "image": args.image.replace("\\", "/"), "imagePrompt": prompt,
                "characterIds": args.character,
                "visualRequirements": visual_requirements,
                "imageGeneration": {
                    "dependsOn": dependencies,
                    "serialReasons": list(dict.fromkeys(args.serial_reason)),
                },
                "targetMarkers": {},
            })
        elif args.command == "set-marker":
            if not (0 <= args.x <= 100 and 0 <= args.y <= 100 and 0 <= args.confidence <= 1):
                raise ValueError("marker x/y must be 0..100 and confidence must be 0..1")
            scene = scene_by_id(story, args.scene)
            scene.setdefault("targetMarkers", {})[args.word.lower()] = {
                "x": args.x, "y": args.y,
                "source": args.source, "confidence": args.confidence, "reviewer": args.reviewer,
            }
        elif args.command == "set-visual-requirements":
            critical_action = critical_action_from_args(args)
            visual_requirements = {
                "mustShow": args.must_show,
                "mustNotShow": args.must_not_show,
                "action": args.action,
                "continuity": args.continuity,
            }
            if critical_action:
                visual_requirements["criticalAction"] = critical_action
            scene = scene_by_id(story, args.scene)
            scene["visualRequirements"] = visual_requirements
            prompt = without_action_prompt_clause(str(scene.get("imagePrompt", "")))
            if critical_action:
                scene["imagePrompt"] = (
                    f"{prompt.rstrip('。 ')}。{action_prompt_clause(critical_action)}"
                )
            else:
                scene["imagePrompt"] = prompt
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
                for key in (
                    "audio", "audioDurationSec", "zhChars", "targetHighlights",
                    "visualTailSec", "ttsAudioInputHash", "ttsTimingInputHash",
                ):
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
        else:
            summary = {
                "schemaVersion": story.get("meta", {}).get("schemaVersion"),
                "title": story.get("meta", {}).get("introTitle"),
                "voice": story.get("meta", {}).get("voice"),
                "ttsProvider": story.get("meta", {}).get("ttsProvider"),
                "targetPauseSec": story.get("meta", {}).get("targetPauseSec"),
                "targetVisualDurationSec": story.get("meta", {}).get("targetVisualDurationSec"),
                "introTailSec": story.get("meta", {}).get("introTailSec"),
                "durationTarget": story.get("meta", {}).get("durationTarget"),
                "targets": story.get("meta", {}).get("pauseTargets", []),
                "scenes": len(story.get("scenes", [])),
                "criticalActionScenes": sum(
                    bool(item.get("visualRequirements", {}).get("criticalAction"))
                    for item in story.get("scenes", [])
                ),
                "serialIllustrationScenes": sum(
                    bool(item.get("imageGeneration", {}).get("dependsOn"))
                    or bool(item.get("imageGeneration", {}).get("serialReasons"))
                    for item in story.get("scenes", [])
                ),
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
