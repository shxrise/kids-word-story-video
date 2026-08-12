#!/usr/bin/env python3
"""Validate content, assets, and generated timing for a word-story project."""

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter
from pathlib import Path

from pipeline_state import mark_stage
from project_runtime import sha256_json


WORD_RE = re.compile(r"[A-Za-z]+")
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


def image_size(path: Path) -> tuple[int, int]:
    """Read PNG or JPEG dimensions without adding a Pillow dependency."""
    with path.open("rb") as handle:
        header = handle.read(24)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return struct.unpack(">II", header[16:24])
        if header[:2] != b"\xff\xd8":
            raise ValueError("only PNG and JPEG illustrations are supported")
        handle.seek(2)
        while True:
            marker_start = handle.read(1)
            if not marker_start:
                break
            if marker_start != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if not marker or marker in {b"\xd8", b"\xd9"}:
                continue
            length_raw = handle.read(2)
            if len(length_raw) != 2:
                break
            length = struct.unpack(">H", length_raw)[0]
            if marker[0] in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                data = handle.read(5)
                if len(data) != 5:
                    break
                height, width = struct.unpack(">HH", data[1:5])
                return width, height
            handle.seek(max(0, length - 2), 1)
    raise ValueError("could not read image dimensions")


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
    targets = [norm(str(item)) for item in raw_targets]
    target_set = set(targets)
    errors: list[str] = []
    warnings: list[str] = []

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
    if any(not item for item in targets):
        errors.append("every target must contain English letters")
    if not scenes:
        errors.append("at least one scene is required")
    elif not 18 <= len(scenes) <= 25:
        warnings.append(
            f"scene count is usually 18–25; got {len(scenes)}. "
            "Keep it only when the story rhythm benefits."
        )

    expected_meta = {
        "fps": 20,
        "highlightThroughPause": True,
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

    sfx_density = str(meta.get("sfxDensity", "standard"))
    if sfx_density not in {"off", "light", "standard", "rich"}:
        errors.append("meta.sfxDensity must be off, light, standard, or rich")
    intro_title = str(meta.get("introTitle", "")).strip()
    if not intro_title:
        errors.append("meta.introTitle is required")
    elif re.search(r"[A-Za-z0-9]", intro_title):
        errors.append("meta.introTitle must be entirely Chinese with no English letters or digits")
    if "introDurationSec" in meta and "introAudioDurationSec" not in meta:
        errors.append("meta.introDurationSec must not be preset; generate it from title audio")

    visual_bible = story.get("visualBible", {})
    if not isinstance(visual_bible, dict):
        errors.append("visualBible must be an object created for this story")
        visual_bible = {}
    if not str(visual_bible.get("stylePrompt", "")).strip():
        errors.append("visualBible.stylePrompt is required")
    if not str(visual_bible.get("palette", "")).strip():
        errors.append("visualBible.palette is required")
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

    sfx_catalog = story.get("sfxCatalog", {})
    if not isinstance(sfx_catalog, dict):
        errors.append("sfxCatalog must be an object")
        sfx_catalog = {}
    for asset_id, asset in sfx_catalog.items():
        if not isinstance(asset, dict):
            errors.append(f"sfxCatalog.{asset_id} must be an object")
            continue
        for field in ("src", "license", "source"):
            if not str(asset.get(field, "")).strip():
                errors.append(f"sfxCatalog.{asset_id}.{field} is required")

    local_sfx_ids = {
        str(asset_id)
        for asset_id, asset in sfx_catalog.items()
        if isinstance(asset, dict) and str(asset.get("license", "")).strip() == "本地生成"
    }
    if local_sfx_ids:
        recipes_path = project / "public" / "story" / "sfx-recipes.json"
        if not recipes_path.is_file():
            errors.append("local generated sound effects require public/story/sfx-recipes.json")
        else:
            try:
                recipes_data = json.loads(recipes_path.read_text(encoding="utf-8"))
                recipe_ids = {
                    str(item.get("id", ""))
                    for item in recipes_data.get("assets", [])
                    if isinstance(item, dict)
                }
                missing_recipes = sorted(local_sfx_ids - recipe_ids)
                if missing_recipes:
                    errors.append(f"local sound effect recipes missing: {missing_recipes}")
            except json.JSONDecodeError as exc:
                errors.append(f"sfx-recipes.json invalid: {exc}")

    if args.stage == "pre-render":
        intro_audio = str(meta.get("introAudio", "")).strip()
        intro_audio_path = project / "public" / intro_audio
        intro_audio_duration = float(meta.get("introAudioDurationSec", 0) or 0)
        intro_duration = float(meta.get("introDurationSec", 0) or 0)
        if not intro_audio or not intro_audio_path.is_file():
            errors.append(f"intro title audio missing: {intro_audio_path}")
        if intro_audio_duration <= 0:
            errors.append("meta.introAudioDurationSec must be generated from title audio")
        if intro_duration <= 0:
            errors.append("meta.introDurationSec must be generated from title audio")
        elif abs(intro_duration - intro_audio_duration) > 1 / max(float(meta.get("fps", 30)), 1):
            errors.append("intro duration must match the actual title audio duration")

    all_tokens: list[str] = []
    total_sfx = 0
    used_sfx: set[str] = set()
    for index, scene in enumerate(scenes, start=1):
        scene_id = str(scene.get("id", index))
        zh = str(scene.get("zh", ""))
        tokens = [norm(match.group(0)) for match in WORD_RE.finditer(zh)]
        all_tokens.extend(tokens)
        extras = sorted(set(tokens) - target_set)
        if extras:
            errors.append(f"scene {scene_id} contains non-target English: {extras}")
        if not zh.strip():
            errors.append(f"scene {scene_id} has empty zh narration")
        if not str(scene.get("image", "")).strip():
            errors.append(f"scene {scene_id} has no image path")
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

        scene_character_ids = scene.get("characterIds", [])
        if not isinstance(scene_character_ids, list):
            errors.append(f"scene {scene_id} characterIds must be a list")
            scene_character_ids = []
        unknown_characters = sorted(set(map(str, scene_character_ids)) - character_id_set)
        if unknown_characters:
            errors.append(f"scene {scene_id} references unknown characters: {unknown_characters}")

        cues = scene.get("sfx", [])
        if not isinstance(cues, list):
            errors.append(f"scene {scene_id} sfx must be a list")
            cues = []
        if len(cues) > 2:
            errors.append(f"scene {scene_id} has {len(cues)} sound effects; maximum is 2")
        total_sfx += len(cues)
        for cue_index, cue in enumerate(cues, start=1):
            if not isinstance(cue, dict):
                errors.append(f"scene {scene_id} sfx {cue_index} must be an object")
                continue
            asset_id = str(cue.get("assetId", "")).strip()
            used_sfx.add(asset_id)
            if asset_id not in sfx_catalog:
                errors.append(f"scene {scene_id} sfx {cue_index} uses unknown asset {asset_id!r}")
            try:
                start = float(cue.get("startSec", -1))
                duration = float(cue.get("durationSec", 0))
                volume = float(cue.get("volume", 0))
                fade_in = float(cue.get("fadeInSec", 0.06))
                fade_out = float(cue.get("fadeOutSec", 0.12))
                if start < 0 or duration <= 0:
                    errors.append(f"scene {scene_id} sfx {cue_index} has invalid timing")
                if not 0 < volume <= 0.28:
                    errors.append(f"scene {scene_id} sfx {cue_index} volume must be >0 and <=0.28")
                if fade_in < 0.10 or fade_out < 0.15:
                    errors.append(
                        f"scene {scene_id} sfx {cue_index} fades must be at least "
                        "0.10s in and 0.15s out for 20fps mixing"
                    )
                if args.stage == "pre-render":
                    scene_duration = float(scene.get("audioDurationSec", 0) or 0)
                    if start + duration > scene_duration + 0.05:
                        errors.append(f"scene {scene_id} sfx {cue_index} exceeds scene duration")
            except (TypeError, ValueError):
                errors.append(f"scene {scene_id} sfx {cue_index} has nonnumeric values")

        if args.stage in ("assets", "pre-render"):
            image_path = project / "public" / str(scene.get("image", ""))
            if not image_path.is_file():
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

            for cue in cues:
                asset = sfx_catalog.get(str(cue.get("assetId", "")), {}) if isinstance(cue, dict) else {}
                src = str(asset.get("src", "")).strip() if isinstance(asset, dict) else ""
                if src and not (project / "public" / src).is_file():
                    errors.append(f"scene {scene_id} sound effect missing: {project / 'public' / src}")

        if args.stage == "pre-render":
            audio_path = project / "public" / str(scene.get("audio", ""))
            if not audio_path.is_file():
                errors.append(f"scene {scene_id} audio missing: {audio_path}")
            if float(scene.get("audioDurationSec", 0) or 0) <= 0:
                errors.append(f"scene {scene_id} has invalid audio duration")
            highlights = scene.get("targetHighlights", [])
            actual = [norm(str(item.get("word", ""))) for item in highlights]
            if actual != tokens:
                errors.append(
                    f"scene {scene_id} highlight sequence mismatch: expected {tokens}, got {actual}"
                )
            for item in highlights:
                if float(item.get("duration", 0) or 0) <= max(0, target_pause_sec):
                    errors.append(
                        f"scene {scene_id} event {item.get('word')} does not include spoken duration"
                        " plus the configured optional pause"
                    )

    counts = Counter(all_tokens)
    for target in targets:
        if counts[target] < 2:
            errors.append(f"target {target} appears {counts[target]} times; minimum is 2")

    if args.stage in ("assets", "pre-render"):
        sources_path = project / "public" / "story" / "image-sources.json"
        source_entries: dict[str, dict] = {}
        if not sources_path.is_file():
            errors.append(f"image provenance manifest missing: {sources_path}")
        else:
            try:
                source_manifest = json.loads(sources_path.read_text(encoding="utf-8"))
                entries = source_manifest.get("assets", [])
                if not isinstance(entries, list):
                    raise ValueError("assets must be a list")
                for entry in entries:
                    if not isinstance(entry, dict) or not str(entry.get("final", "")).strip():
                        errors.append("image-sources.json contains an invalid asset entry")
                        continue
                    final_key = str(entry["final"]).replace("\\", "/")
                    source_entries[final_key] = entry
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(f"image provenance manifest invalid: {exc}")

        required_images = [str(scene.get("image", "")).replace("\\", "/") for scene in scenes]
        reference_key = str(visual_bible.get("referenceImage", "")).replace("\\", "/")
        if reference_key:
            required_images.append(reference_key)
        for final_key in required_images:
            entry = source_entries.get(final_key)
            if not entry:
                errors.append(f"image provenance missing for {final_key}")
                continue
            raw_rel = str(entry.get("raw", "")).strip()
            raw_path = project / "public" / raw_rel
            final_path = project / "public" / final_key
            if not raw_rel or not raw_path.is_file():
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
            if final_path.is_file() and str(entry.get("finalSha256", "")).upper() != file_sha256(final_path):
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
        reference_path = project / "public" / reference
        if not reference or not reference_path.is_file():
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
                    reviewed_path = project / "public" / reviewed_rel
                    if reviewed_rel != expected_rel or not reviewed_path.is_file():
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

    if args.stage == "pre-render":
        if sfx_density == "off" and total_sfx:
            errors.append("meta.sfxDensity is off but sound effects are present")
        if sfx_density != "off" and total_sfx < max(1, len(scenes) // 2):
            warnings.append(
                f"only {total_sfx} sound effects across {len(scenes)} scenes; "
                "quiet scenes are allowed, but confirm the selected density"
            )
        unused_sfx = sorted(set(sfx_catalog) - used_sfx)
        if unused_sfx:
            warnings.append(f"unused sound assets: {unused_sfx}")

    summary = {
        "stage": args.stage,
        "scenes": len(scenes),
        "targets": len(targets),
        "englishOccurrences": len(all_tokens),
        "soundEffects": total_sfx,
        "counts": {target: counts[target] for target in targets},
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
