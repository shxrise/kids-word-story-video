#!/usr/bin/env python3
"""Validate content, assets, and generated timing for a word-story project."""

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from duration_control import (
    duration_input,
    duration_target,
    event_spoken_duration_sec,
    event_visual_duration_sec,
    intro_tail_sec,
    scene_timeline_duration_sec,
    story_timeline_duration_sec,
    target_visual_duration_sec,
)
from image_batch_plan import build_plan
from pipeline_state import mark_stage
from project_runtime import image_size, safe_child, sha256_json


WORD_RE = re.compile(r"[A-Za-z]+")
CHINESE_TITLE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff《》！？·]+")
CHINESE_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
OUTPUT_SIZE = (1280, 720)
IMAGE_SIZE = (1280, 720)


def norm(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--stage", choices=("content", "assets", "pre-render"), default="content")
    parser.add_argument("--no-state", action="store_true", help="Validate without changing pipeline state")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    story_path = project / "public" / "story" / "story.json"
    if not story_path.is_file():
        sys.exit(f"story file missing: {story_path}")

    story = json.loads(story_path.read_text(encoding="utf-8"))
    meta = story.get("meta", {})
    scenes = story.get("scenes", [])
    raw_targets = meta.get("pauseTargets", [])
    errors: list[str] = []
    warnings: list[str] = []
    public = project / "public"

    def public_path(relative: object, label: str) -> Path | None:
        try:
            return safe_child(public, str(relative), label)[1]
        except ValueError as exc:
            errors.append(str(exc))
            return None
    if not isinstance(raw_targets, list):
        errors.append("meta.pauseTargets must be a list")
        raw_targets = []
    targets = [norm(str(item)) for item in raw_targets]
    target_set = set(targets)

    if story.get("$schema") != "story.schema.json":
        errors.append("story.$schema must be story.schema.json")
    if not (story_path.parent / "story.schema.json").is_file():
        errors.append("public/story/story.schema.json is missing")

    if meta.get("schemaVersion") != 2:
        errors.append("meta.schemaVersion must be 2; create the story with the optimized v2 contract")
    if meta.get("ttsProvider") not in {"edge", "azure"}:
        errors.append("meta.ttsProvider must be edge or azure")
    if not str(meta.get("voice", "")).strip():
        errors.append("meta.voice is required")

    if not targets:
        errors.append("at least one target word is required")
    if len(target_set) != len(targets):
        errors.append("target words contain duplicates after normalization")
    if any(not isinstance(item, str) or not WORD_RE.fullmatch(item) for item in raw_targets):
        errors.append("every target must contain ASCII English letters only")
    if not scenes:
        errors.append("at least one scene is required")
    elif not 22 <= len(scenes) <= 25:
        warnings.append(
            f"default stories usually use 22–25 scenes; got {len(scenes)}. "
            "Keep it only when the story rhythm benefits."
        )
    scene_ids = [str(scene.get("id", "")).strip() for scene in scenes]
    duplicate_scene_ids = sorted(
        scene_id for scene_id, count in Counter(scene_ids).items() if scene_id and count > 1
    )
    if duplicate_scene_ids:
        errors.append(f"scene ids must be unique: {duplicate_scene_ids}")

    expected_meta = {
        "fps": 20,
        "imageNormalization": "stable-lanczos",
        "imageAspectTolerancePct": 1.0,
    }
    for key, expected in expected_meta.items():
        if meta.get(key) != expected:
            errors.append(f"meta.{key} must be {expected!r}, got {meta.get(key)!r}")
    try:
        raw_target_pause_sec = meta.get("targetPauseSec", -1)
        if isinstance(raw_target_pause_sec, bool):
            raise ValueError
        target_pause_sec = float(raw_target_pause_sec)
        if not math.isfinite(target_pause_sec) or target_pause_sec < 0:
            raise ValueError
    except (TypeError, ValueError):
        target_pause_sec = -1
        errors.append("meta.targetPauseSec must be a finite nonnegative number")
    try:
        configured_visual_duration = target_visual_duration_sec(meta)
        if "targetVisualDurationSec" not in meta:
            errors.append("meta.targetVisualDurationSec must be explicit")
    except ValueError as exc:
        configured_visual_duration = 1.2
        errors.append(str(exc))
    try:
        configured_intro_tail = intro_tail_sec(meta)
        if "introTailSec" not in meta:
            warnings.append("meta.introTailSec is not explicit; the configured fallback is in use")
    except ValueError as exc:
        configured_intro_tail = 0.0
        errors.append(str(exc))
    try:
        configured_duration_target = duration_target(meta)
        if "durationTarget" not in meta:
            warnings.append("meta.durationTarget is not explicit; the standard duration range is in use")
    except ValueError as exc:
        configured_duration_target = {}
        errors.append(str(exc))
    try:
        output_size = (int(meta.get("width", 0)), int(meta.get("height", 0)))
        configured_image_size = (
            int(meta.get("imageWidth", 0)),
            int(meta.get("imageHeight", 0)),
        )
    except (TypeError, ValueError):
        output_size = (0, 0)
        configured_image_size = (0, 0)
    if output_size != OUTPUT_SIZE:
        errors.append(f"output size must be 1280x720, got {output_size}")
    if configured_image_size != IMAGE_SIZE:
        errors.append(f"image size must be 1280x720, got {configured_image_size}")
    if configured_image_size[0] * 9 != configured_image_size[1] * 16:
        errors.append("scene illustrations must use an exact native 16:9 size")

    intro_title = str(meta.get("introTitle", "")).strip()
    if not intro_title:
        errors.append("meta.introTitle is required")
    elif not CHINESE_TITLE_RE.fullmatch(intro_title):
        errors.append("meta.introTitle must use Chinese text and title punctuation only")
    elif not 4 <= len(CHINESE_CHAR_RE.findall(intro_title)) <= 18:
        errors.append("meta.introTitle must be a complete 4–18 character Chinese story name")
    elif not 6 <= len(CHINESE_CHAR_RE.findall(intro_title)) <= 10:
        warnings.append("intro title is outside the preferred 6–10 Chinese-character range")
    visual_bible = story.get("visualBible", {})
    if not isinstance(visual_bible, dict):
        errors.append("visualBible must be an object created for this story")
        visual_bible = {}
    if not str(visual_bible.get("stylePrompt", "")).strip():
        errors.append("visualBible.stylePrompt is required")
    if not str(visual_bible.get("palette", "")).strip():
        errors.append("visualBible.palette is required")
    reference_rel = str(visual_bible.get("referenceImage", "")).replace("\\", "/").strip()
    if not reference_rel:
        errors.append("visualBible.referenceImage is required")
    elif not reference_rel.startswith("reference/"):
        errors.append("visualBible.referenceImage must be under public/reference/")
    else:
        public_path(reference_rel, "visualBible.referenceImage")
    characters = visual_bible.get("characters", [])
    if not isinstance(characters, list) or not characters:
        errors.append("visualBible.characters must contain this story's recurring characters")
        characters = []
    character_ids: list[str] = []
    for character in characters:
        if not isinstance(character, dict):
            errors.append("each visualBible character must be an object")
            continue
        character_id = str(character.get("id", "")).strip()
        character_ids.append(character_id)
        for field in ("id", "name", "role", "appearance"):
            if not str(character.get(field, "")).strip():
                errors.append(f"visualBible character is missing {field}")
        if not isinstance(character.get("mustKeep"), list) or not character.get("mustKeep"):
            errors.append(f"visualBible character {character_id or '?'} needs mustKeep traits")
    if len(set(character_ids)) != len(character_ids):
        errors.append("visualBible character ids must be unique")
    character_id_set = set(character_ids)

    if args.stage == "pre-render":
        intro_audio = str(meta.get("introAudio", "")).strip()
        intro_audio_path = public_path(intro_audio, "meta.introAudio") if intro_audio else None
        intro_audio_duration = float(meta.get("introAudioDurationSec", 0) or 0)
        if not intro_audio or intro_audio_path is None or not intro_audio_path.is_file():
            errors.append(f"intro title audio missing: {intro_audio_path}")
        if intro_audio_duration <= 0:
            errors.append("meta.introAudioDurationSec must be generated from title audio")
        if configured_intro_tail < 0:
            errors.append("meta.introTailSec must be nonnegative")

    all_tokens: list[str] = []
    raw_target_set = {str(item) for item in raw_targets}
    target_spelling_by_norm = {norm(str(item)): str(item) for item in raw_targets}
    for index, scene in enumerate(scenes, start=1):
        scene_id = str(scene.get("id", index))
        zh = str(scene.get("zh", ""))
        raw_tokens = [match.group(0) for match in WORD_RE.finditer(zh)]
        tokens = [norm(token) for token in raw_tokens]
        all_tokens.extend(tokens)
        extras = sorted(set(tokens) - target_set)
        if extras:
            errors.append(f"scene {scene_id} contains non-target English: {extras}")
        changed_spellings = sorted(
            {token for token in raw_tokens if norm(token) in target_set and token not in raw_target_set}
        )
        if changed_spellings:
            errors.append(
                f"scene {scene_id} changes target spelling or letter case: {changed_spellings}"
            )
        if not zh.strip():
            errors.append(f"scene {scene_id} has empty zh narration")
        chinese_chars = len(CHINESE_CHAR_RE.findall(zh))
        if chinese_chars and not 55 <= chinese_chars <= 75:
            warnings.append(
                f"scene {scene_id} has {chinese_chars} Chinese characters; 55–75 is the usual range"
            )
        image_rel = str(scene.get("image", "")).strip()
        image_path = None
        if not image_rel:
            errors.append(f"scene {scene_id} has no image path")
        elif not image_rel.replace("\\", "/").startswith("assets/"):
            errors.append(f"scene {scene_id} image must be under public/assets/")
        else:
            image_path = public_path(image_rel, f"scene {scene_id} image")
        if not str(scene.get("imagePrompt", "")).strip():
            errors.append(f"scene {scene_id} has no imagePrompt")
        elif "16:9" not in str(scene.get("imagePrompt", "")):
            errors.append(f"scene {scene_id} imagePrompt must explicitly request native 16:9")

        requirements = scene.get("visualRequirements")
        if not isinstance(requirements, dict):
            errors.append(f"scene {scene_id} requires visualRequirements")
            requirements = {}
        if not isinstance(requirements.get("mustShow"), list) or not requirements.get("mustShow"):
            errors.append(f"scene {scene_id} visualRequirements.mustShow must be a non-empty list")
        if not isinstance(requirements.get("mustNotShow"), list):
            errors.append(f"scene {scene_id} visualRequirements.mustNotShow must be a list")
        if not str(requirements.get("action", "")).strip():
            errors.append(f"scene {scene_id} visualRequirements.action is required")
        if not isinstance(requirements.get("continuity"), list):
            errors.append(f"scene {scene_id} visualRequirements.continuity must be a list")
        critical_action = requirements.get("criticalAction")
        if critical_action is not None:
            if not isinstance(critical_action, dict):
                errors.append(f"scene {scene_id} visualRequirements.criticalAction must be an object")
            else:
                action_fields = (
                    "subject", "bodyPartOrTool", "object", "contact", "relativePosition", "direction", "result"
                )
                missing_details = [
                    field for field in action_fields if not str(critical_action.get(field, "")).strip()
                ]
                if missing_details:
                    errors.append(f"scene {scene_id} critical action details missing: {missing_details}")
                forbidden = critical_action.get("forbiddenAlternatives")
                if not isinstance(forbidden, list) or any(not str(item).strip() for item in forbidden):
                    errors.append(
                        f"scene {scene_id} criticalAction.forbiddenAlternatives must be a string list"
                    )
                    forbidden_items: list = []
                else:
                    forbidden_items = forbidden
                prompt = str(scene.get("imagePrompt", ""))
                prompt_details = [str(critical_action.get(field, "")).strip() for field in action_fields]
                prompt_details.extend(str(item).strip() for item in forbidden_items)
                absent = [detail for detail in prompt_details if detail and detail not in prompt]
                if absent:
                    errors.append(
                        f"scene {scene_id} imagePrompt omits critical action details: {absent}"
                    )

        image_generation = scene.get("imageGeneration", {})
        if "imageGeneration" not in scene:
            warnings.append(
                f"scene {scene_id} has no explicit imageGeneration contract; it is treated as independent"
            )
        if not isinstance(image_generation, dict):
            errors.append(f"scene {scene_id} imageGeneration must be an object")
            image_generation = {}
        dependencies = image_generation.get("dependsOn", [])
        serial_reasons = image_generation.get("serialReasons", [])
        earlier_ids = {str(item.get("id", "")) for item in scenes[: index - 1]}
        if not isinstance(dependencies, list):
            errors.append(f"scene {scene_id} imageGeneration.dependsOn must be a list")
            dependencies = []
        elif len(dependencies) != len(set(map(str, dependencies))):
            errors.append(f"scene {scene_id} imageGeneration.dependsOn contains duplicates")
        unknown_dependencies = sorted(set(map(str, dependencies)) - earlier_ids)
        if unknown_dependencies:
            errors.append(
                f"scene {scene_id} image dependencies must refer to earlier scenes: {unknown_dependencies}"
            )
        allowed_serial_reasons = {
            "continuous-action", "prop-state", "previous-image-reference", "manual"
        }
        if not isinstance(serial_reasons, list) or any(
            reason not in allowed_serial_reasons for reason in serial_reasons
        ):
            errors.append(f"scene {scene_id} imageGeneration.serialReasons is invalid")
        elif len(serial_reasons) != len(set(serial_reasons)):
            errors.append(f"scene {scene_id} imageGeneration.serialReasons contains duplicates")
        scene_character_ids = scene.get("characterIds", [])
        if not isinstance(scene_character_ids, list):
            errors.append(f"scene {scene_id} characterIds must be a list")
            scene_character_ids = []
        unknown_characters = sorted(set(map(str, scene_character_ids)) - character_id_set)
        if unknown_characters:
            errors.append(f"scene {scene_id} references unknown characters: {unknown_characters}")

        if args.stage in ("assets", "pre-render"):
            if image_path is None or not image_path.is_file():
                errors.append(f"scene {scene_id} image missing: {image_path}")
            else:
                try:
                    actual_size = image_size(image_path)
                    if actual_size != configured_image_size:
                        errors.append(
                            f"scene {scene_id} image must be native {configured_image_size[0]}x"
                            f"{configured_image_size[1]}, got {actual_size}; do not crop or stretch"
                        )
                except ValueError as exc:
                    errors.append(f"scene {scene_id} image invalid: {exc}")
            markers = scene.get("targetMarkers", {})
            for token in set(tokens):
                if token not in markers:
                    errors.append(f"scene {scene_id} missing marker for {token}")
                    continue
                marker = markers[token]
                try:
                    x, y = float(marker["x"]), float(marker["y"])
                    if not (0 <= x <= 100 and 0 <= y <= 100):
                        errors.append(f"scene {scene_id} marker {token} outside 0–100")
                    if marker.get("source") not in {"visual-review", "tts-boundary", "scene-default"}:
                        errors.append(f"scene {scene_id} marker {token} has invalid source")
                    confidence = float(marker.get("confidence", -1))
                    if not 0 <= confidence <= 1:
                        errors.append(f"scene {scene_id} marker {token} confidence must be 0–1")
                    if not str(marker.get("reviewer", "")).strip():
                        errors.append(f"scene {scene_id} marker {token} reviewer is required")
                except (KeyError, TypeError, ValueError):
                    errors.append(f"scene {scene_id} marker {token} is invalid")

        if args.stage == "pre-render":
            audio_path = public_path(scene.get("audio", ""), f"scene {scene_id} audio")
            if audio_path is None or not audio_path.is_file():
                errors.append(f"scene {scene_id} audio missing: {audio_path}")
            if float(scene.get("audioDurationSec", 0) or 0) <= 0:
                errors.append(f"scene {scene_id} has invalid audio duration")
            highlights = scene.get("targetHighlights", [])
            actual = [norm(str(item.get("word", ""))) for item in highlights]
            if actual != tokens:
                errors.append(
                    f"scene {scene_id} highlight sequence mismatch: expected {tokens}, got {actual}"
                )
            previous_event_start = -1.0
            for item in highlights:
                try:
                    event_word = norm(str(item.get("word", "")))
                    if item.get("displayWord") != target_spelling_by_norm.get(event_word):
                        errors.append(
                            f"scene {scene_id} event {item.get('word')} does not preserve target spelling"
                        )
                    event_start = float(item.get("start", -1))
                    spoken_duration = event_spoken_duration_sec(item)
                    visual_duration = event_visual_duration_sec(item, meta)
                    recorded_visual_duration = (
                        float(item.get("visualDurationSec", 0) or 0)
                        if "visualDurationSec" in item
                        else visual_duration
                    )
                    if spoken_duration <= 0:
                        errors.append(f"scene {scene_id} event {item.get('word')} has no spoken duration")
                    if event_start < 0 or event_start + 1e-6 < previous_event_start:
                        errors.append(f"scene {scene_id} target events are not in chronological order")
                    previous_event_start = max(previous_event_start, event_start)
                    if event_start + spoken_duration > float(scene.get("audioDurationSec", 0) or 0) + 0.05:
                        errors.append(
                            f"scene {scene_id} event {item.get('word')} pronunciation exceeds narration audio"
                        )
                    if recorded_visual_duration + 1e-6 < configured_visual_duration:
                        errors.append(
                            f"scene {scene_id} event {item.get('word')} visual duration is shorter than configured"
                        )
                    if recorded_visual_duration + 1e-6 < spoken_duration:
                        errors.append(
                            f"scene {scene_id} event {item.get('word')} ends before pronunciation finishes"
                        )
                    if "spokenDurationSec" not in item or "visualDurationSec" not in item:
                        warnings.append(
                            f"scene {scene_id} event {item.get('word')} does not use explicit spoken and visual timing"
                        )
                except (TypeError, ValueError) as exc:
                    errors.append(f"scene {scene_id} event {item.get('word')} timing invalid: {exc}")
            try:
                timeline_duration = scene_timeline_duration_sec(scene, meta)
                if timeline_duration + 1e-6 < float(scene.get("audioDurationSec", 0) or 0):
                    errors.append(f"scene {scene_id} timeline is shorter than narration")
            except (TypeError, ValueError) as exc:
                errors.append(f"scene {scene_id} timeline invalid: {exc}")

    counts = Counter(all_tokens)
    for target in targets:
        if counts[target] < 2:
            errors.append(f"target {target} appears {counts[target]} times; minimum is 2")

    if args.stage in ("assets", "pre-render"):
        image_plan_path = project / "build" / "image-generation-plan.json"
        if not image_plan_path.is_file():
            errors.append(f"illustration batch plan missing: {image_plan_path}")
        else:
            try:
                image_plan = json.loads(image_plan_path.read_text(encoding="utf-8"))
                retry_ids = image_plan.get("retrySceneIds", [])
                force_serial = image_plan.get("forceSerial", False)
                preserved_ids = image_plan.get("preservedSceneIds", [])
                if (
                    not isinstance(retry_ids, list)
                    or not isinstance(preserved_ids, list)
                    or not isinstance(force_serial, bool)
                ):
                    raise ValueError("retrySceneIds/preservedSceneIds/forceSerial are invalid")
                expected_plan = build_plan(
                    story,
                    list(map(str, retry_ids)),
                    force_serial,
                    list(map(str, preserved_ids)),
                )
                if image_plan.get("inputSha256") != expected_plan.get("inputSha256"):
                    errors.append("illustration batch plan is stale")
                if image_plan.get("maxParallelScenes") != 3:
                    errors.append("illustration batch plan must cap parallel scenes at 3")
                batches = image_plan.get("batches", [])
                all_scene_ids = {str(scene.get("id", "")) for scene in scenes}
                if not isinstance(batches, list) or (
                    not batches and set(map(str, preserved_ids)) != all_scene_ids
                ):
                    errors.append("illustration batch plan must contain work or preserve every scene")
                    batches = []
                for batch in batches:
                    scene_ids = batch.get("sceneIds", []) if isinstance(batch, dict) else []
                    mode = batch.get("mode") if isinstance(batch, dict) else None
                    limit = 3 if mode == "parallel" else 1
                    if not isinstance(scene_ids, list) or not scene_ids or len(scene_ids) > limit:
                        errors.append("illustration batch plan contains an unsafe batch")
                        break
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(f"illustration batch plan invalid: {exc}")

        preflight_path = project / "build" / "duration-preflight.json"
        if preflight_path.is_file():
            try:
                preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
                if preflight.get("status") != "passed":
                    errors.append("duration preflight did not pass")
                if preflight.get("inputSha256") != sha256_json(duration_input(story)):
                    errors.append("duration preflight is stale")
            except json.JSONDecodeError as exc:
                errors.append(f"duration preflight report invalid: {exc}")
        elif "durationTarget" in meta:
            errors.append("build/duration-preflight.json is required before bulk illustration and render")
        else:
            warnings.append("duration preflight report is not present for this project contract")

    if args.stage in ("assets", "pre-render"):
        sources_path = project / "public" / "story" / "image-sources.json"
        source_entries: dict[str, dict] = {}
        if not sources_path.is_file():
            errors.append(f"image provenance manifest missing: {sources_path}")
        else:
            try:
                source_manifest = json.loads(sources_path.read_text(encoding="utf-8"))
                if not isinstance(source_manifest, dict):
                    raise ValueError("manifest root must be an object")
                entries = source_manifest.get("assets", [])
                if not isinstance(entries, list):
                    raise ValueError("assets must be a list")
                for entry in entries:
                    if not isinstance(entry, dict) or not str(entry.get("final", "")).strip():
                        errors.append("image-sources.json contains an invalid asset entry")
                        continue
                    try:
                        final_key = safe_child(
                            public, str(entry["final"]), "image manifest final path"
                        )[0]
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                    if final_key in source_entries:
                        errors.append(f"image provenance contains duplicate final entry: {final_key}")
                    source_entries[final_key] = entry
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(f"image provenance manifest invalid: {exc}")

        required_images = [str(scene.get("image", "")).replace("\\", "/") for scene in scenes]
        reference_key = str(visual_bible.get("referenceImage", "")).replace("\\", "/")
        if reference_key:
            required_images.append(reference_key)
        required_image_set = set(required_images)
        for final_key in sorted(set(source_entries) - required_image_set):
            errors.append(f"image provenance contains unreferenced final asset: {final_key}")

        allowed_final_files: set[Path] = set()
        for relative in required_image_set:
            resolved = public_path(relative, "story image path")
            if resolved is not None:
                allowed_final_files.add(resolved)
        for folder_name in ("assets", "reference"):
            folder = project / "public" / folder_name
            if folder.is_dir():
                for image_path in folder.rglob("*"):
                    if image_path.is_file() and image_path.resolve() not in allowed_final_files:
                        extra_rel = image_path.relative_to(public).as_posix()
                        errors.append(f"unreferenced final image file: {extra_rel}")

        allowed_raw_files: set[Path] = set()
        for entry in source_entries.values():
            raw_rel = str(entry.get("raw", "")).strip()
            if raw_rel:
                resolved = public_path(raw_rel, "image manifest raw path")
                if resolved is not None:
                    allowed_raw_files.add(resolved)
        raw_folder = public / "raw"
        if raw_folder.is_dir():
            for raw_path in raw_folder.rglob("*"):
                if raw_path.is_file() and raw_path.resolve() not in allowed_raw_files:
                    extra_rel = raw_path.relative_to(public).as_posix()
                    errors.append(f"unreferenced raw image file: {extra_rel}")

        for final_key in required_images:
            entry = source_entries.get(final_key)
            if not entry:
                errors.append(f"image provenance missing for {final_key}")
                continue
            raw_rel = str(entry.get("raw", "")).strip()
            raw_path = public_path(raw_rel, f"raw source for {final_key}") if raw_rel else None
            final_path = public_path(final_key, f"final image for {final_key}")
            if not raw_rel or raw_path is None or not raw_path.is_file():
                errors.append(f"raw source image missing for {final_key}: {raw_rel}")
            else:
                if str(entry.get("sourceSha256", "")).upper() != file_sha256(raw_path):
                    errors.append(f"raw source image hash mismatch for {final_key}")
                try:
                    raw_size = image_size(raw_path)
                    recorded_size = (int(entry.get("sourceWidth", 0)), int(entry.get("sourceHeight", 0)))
                    if raw_size != recorded_size:
                        errors.append(f"raw source image size record mismatch for {final_key}")
                except (ValueError, TypeError):
                    errors.append(f"raw source image dimensions invalid for {final_key}")
            if final_path is not None and final_path.is_file() and str(
                entry.get("finalSha256", "")
            ).upper() != file_sha256(final_path):
                errors.append(f"normalized image hash mismatch for {final_key}")
            try:
                aspect_error = float(entry.get("aspectErrorPct", 999))
                if aspect_error > 1.0:
                    errors.append(f"source image for {final_key} exceeds 1.0% aspect tolerance")
            except (TypeError, ValueError):
                errors.append(f"source image for {final_key} has invalid aspectErrorPct")
            if not str(entry.get("sourceSha256", "")).strip() or not str(
                entry.get("finalSha256", "")
            ).strip():
                errors.append(f"image hashes missing for {final_key}")

        reference = str(visual_bible.get("referenceImage", "")).strip()
        reference_path = public_path(reference, "visualBible.referenceImage") if reference else None
        if not reference or reference_path is None or not reference_path.is_file():
            errors.append(f"story-specific character reference image missing: {reference_path}")
        else:
            try:
                actual_reference_size = image_size(reference_path)
                if actual_reference_size != configured_image_size:
                    errors.append(
                        f"character reference must be {configured_image_size[0]}x"
                        f"{configured_image_size[1]}, got {actual_reference_size}"
                    )
            except ValueError as exc:
                errors.append(f"character reference image invalid: {exc}")

        reviews_path = project / "public" / "story" / "visual-reviews.json"
        if not reviews_path.is_file():
            errors.append(f"visual semantic review manifest missing: {reviews_path}")
        else:
            try:
                reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
                review_items = reviews.get("items", {})
                for item_id in ["reference", *[str(scene.get("id", "")) for scene in scenes]]:
                    review = review_items.get(item_id)
                    if not isinstance(review, dict) or review.get("status") not in {"passed", "accepted-minor"}:
                        errors.append(f"visual semantic review not accepted for {item_id}")
                        continue
                    if review.get("status") == "accepted-minor" and not review.get("issues"):
                        errors.append(f"accepted-minor visual review has no documented deviation for {item_id}")
                    if review.get("status") == "accepted-minor":
                        history = review.get("history", []) if isinstance(review.get("history"), list) else []
                        max_retries = int(reviews.get("policy", {}).get("maxSemanticRetries", 2))
                        retries = sum(entry.get("status") == "retry-required" for entry in history)
                        rejected = any(entry.get("status") == "rejected" for entry in history)
                        candidates = {
                            entry.get("imageSha256")
                            for entry in history
                            if entry.get("status") in {"retry-required", "rejected"}
                        }
                        if retries < max_retries or not rejected or review.get("imageSha256") not in candidates:
                            errors.append(f"accepted-minor retry evidence is incomplete for {item_id}")
                    reviewed_rel = str(review.get("image", "")).replace("\\", "/")
                    expected_rel = reference_key if item_id == "reference" else str(
                        next(scene for scene in scenes if str(scene.get("id", "")) == item_id).get("image", "")
                    ).replace("\\", "/")
                    reviewed_path = public_path(
                        reviewed_rel, f"visual review image for {item_id}"
                    )
                    if (
                        reviewed_rel != expected_rel
                        or reviewed_path is None
                        or not reviewed_path.is_file()
                    ):
                        errors.append(f"visual review image mismatch for {item_id}")
                    elif str(review.get("imageSha256", "")).upper() != file_sha256(reviewed_path):
                        errors.append(f"visual review is stale for {item_id}")
                    if review.get("reviewMethod") not in {"human", "vision-model"}:
                        errors.append(f"visual review method invalid for {item_id}")
                    if not str(review.get("reviewer", "")).strip():
                        errors.append(f"visual review reviewer missing for {item_id}")
                    expected_requirements = (
                        {
                            "mustShow": [f"{item.get('name')}: {item.get('appearance')}" for item in characters],
                            "mustNotShow": ["文字", "字母", "数字", "Logo", "水印"],
                            "action": "角色参考图清楚展示所有主要角色的固定外观",
                            "continuity": [trait for item in characters for trait in item.get("mustKeep", [])],
                        }
                        if item_id == "reference"
                        else next(scene for scene in scenes if str(scene.get("id", "")) == item_id).get("visualRequirements", {})
                    )
                    if review.get("requirementsSha256") != sha256_json(expected_requirements):
                        errors.append(f"visual review requirements are stale for {item_id}")
            except (json.JSONDecodeError, StopIteration) as exc:
                errors.append(f"visual semantic review manifest invalid: {exc}")

    summary = {
        "stage": args.stage,
        "scenes": len(scenes),
        "targets": len(targets),
        "englishOccurrences": len(all_tokens),
        "durationTarget": configured_duration_target,
        "timelineDurationSec": (
            round(story_timeline_duration_sec(story), 3)
            if args.stage == "pre-render" and not errors
            else None
        ),
        "counts": {str(raw): counts[norm(str(raw))] for raw in raw_targets},
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        sys.exit(1)
    if args.no_state:
        return
    if args.stage == "content":
        mark_stage(project, "story_validated", {"validator": "validate_story.py", "stage": "content"})
    elif args.stage == "assets":
        mark_stage(project, "images_ready", {"validator": "validate_story.py", "stage": "assets"})


if __name__ == "__main__":
    main()
