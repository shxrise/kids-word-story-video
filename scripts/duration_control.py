#!/usr/bin/env python3
"""Shared duration defaults, timeline math, and the pre-illustration TTS gate."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from project_runtime import atomic_json, sha256_json


DEFAULT_DURATION_TARGET = {
    "targetSec": 330.0,
    "idealMinSec": 300.0,
    "idealMaxSec": 360.0,
    "acceptableMinSec": 285.0,
    "acceptableMaxSec": 375.0,
    "maxCreativeAdjustments": 2,
}
DEFAULT_INTRO_TAIL_SEC = 0.6
DEFAULT_TARGET_VISUAL_DURATION_SEC = 1.2


def finite_number(value: object, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number >= {minimum}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number >= {minimum}") from exc
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{label} must be a finite number >= {minimum}")
    return number


def duration_target(meta: dict) -> dict:
    raw = meta.get("durationTarget")
    if raw is None:
        return dict(DEFAULT_DURATION_TARGET)
    if not isinstance(raw, dict):
        raise ValueError("meta.durationTarget must be an object")
    result = {
        key: finite_number(raw.get(key), f"meta.durationTarget.{key}", minimum=1.0)
        for key in (
            "targetSec",
            "idealMinSec",
            "idealMaxSec",
            "acceptableMinSec",
            "acceptableMaxSec",
        )
    }
    adjustments = raw.get("maxCreativeAdjustments")
    if isinstance(adjustments, bool) or not isinstance(adjustments, int) or adjustments < 0:
        raise ValueError("meta.durationTarget.maxCreativeAdjustments must be a nonnegative integer")
    result["maxCreativeAdjustments"] = adjustments
    if not (
        result["acceptableMinSec"]
        <= result["idealMinSec"]
        <= result["targetSec"]
        <= result["idealMaxSec"]
        <= result["acceptableMaxSec"]
    ):
        raise ValueError(
            "duration target must satisfy acceptableMin <= idealMin <= target <= idealMax <= acceptableMax"
        )
    return result


def intro_tail_sec(meta: dict) -> float:
    return finite_number(meta.get("introTailSec", 0.0), "meta.introTailSec")


def target_visual_duration_sec(meta: dict) -> float:
    return finite_number(
        meta.get("targetVisualDurationSec", DEFAULT_TARGET_VISUAL_DURATION_SEC),
        "meta.targetVisualDurationSec",
        minimum=0.05,
    )


def event_spoken_duration_sec(event: dict) -> float:
    return finite_number(
        event.get("spokenDurationSec", 0), "event.spokenDurationSec"
    )


def event_visual_duration_sec(event: dict, meta: dict) -> float:
    spoken = event_spoken_duration_sec(event)
    configured = target_visual_duration_sec(meta)
    if "visualDurationSec" in event:
        recorded = finite_number(event.get("visualDurationSec"), "event.visualDurationSec", minimum=0.001)
        return max(recorded, spoken, configured)
    return max(spoken, configured)


def intro_timeline_duration_sec(meta: dict) -> float:
    audio = finite_number(meta.get("introAudioDurationSec", 0) or 0, "meta.introAudioDurationSec")
    return audio + intro_tail_sec(meta)


def scene_timeline_duration_sec(scene: dict, meta: dict) -> float:
    audio = finite_number(scene.get("audioDurationSec", 0) or 0, "scene.audioDurationSec")
    visual_end = 0.0
    for event in scene.get("targetHighlights", []) or []:
        if not isinstance(event, dict):
            continue
        start = finite_number(event.get("start", 0), "event.start")
        visual_end = max(visual_end, start + event_visual_duration_sec(event, meta))
    return max(audio, visual_end)


def story_timeline_duration_sec(story: dict) -> float:
    meta = story.get("meta", {})
    return intro_timeline_duration_sec(meta) + sum(
        scene_timeline_duration_sec(scene, meta) for scene in story.get("scenes", [])
    )


def expected_frames(story: dict) -> int:
    meta = story.get("meta", {})
    fps = int(meta.get("fps", 20))
    return math.ceil(intro_timeline_duration_sec(meta) * fps) + sum(
        math.ceil(scene_timeline_duration_sec(scene, meta) * fps)
        for scene in story.get("scenes", [])
    )


def duration_input(story: dict) -> dict:
    meta = story.get("meta", {})
    return {
        "durationTarget": duration_target(meta),
        "introTitle": meta.get("introTitle"),
        "introAudioDurationSec": meta.get("introAudioDurationSec"),
        "introTailSec": intro_tail_sec(meta),
        "targetPauseSec": meta.get("targetPauseSec"),
        "targetVisualDurationSec": target_visual_duration_sec(meta),
        "scenes": [
            {
                "id": scene.get("id"),
                "zh": scene.get("zh"),
                "audioDurationSec": scene.get("audioDurationSec"),
                "ttsAudioInputHash": scene.get("ttsAudioInputHash"),
                "ttsTimingInputHash": scene.get("ttsTimingInputHash"),
                "targetHighlights": scene.get("targetHighlights", []),
            }
            for scene in story.get("scenes", [])
        ],
    }


def evaluate_duration(story: dict) -> dict:
    target = duration_target(story.get("meta", {}))
    measured = round(story_timeline_duration_sec(story), 3)
    in_acceptable = target["acceptableMinSec"] <= measured <= target["acceptableMaxSec"]
    in_ideal = target["idealMinSec"] <= measured <= target["idealMaxSec"]
    if measured < target["acceptableMinSec"]:
        reason = "story is too short; expand meaningful plot before bulk illustration"
    elif measured > target["acceptableMaxSec"]:
        reason = "story is too long; remove redundant narration before bulk illustration"
    else:
        reason = None
    return {
        "status": "passed" if in_acceptable else "rejected",
        "measurement": "actual-tts-timeline",
        "target": target,
        "estimatedDurationSec": measured,
        "withinIdealRange": in_ideal,
        "withinAcceptableRange": in_acceptable,
        "reason": reason,
        "inputSha256": sha256_json(duration_input(story)),
    }


def record_duration_preflight(project: Path, story: dict) -> dict:
    path = project / "build" / "duration-preflight.json"
    previous = {}
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    result = evaluate_duration(story)
    history = previous.get("history", []) if isinstance(previous.get("history"), list) else []
    if previous.get("target") != result["target"]:
        history = []
    if not any(item.get("inputSha256") == result["inputSha256"] for item in history):
        history.append(
            {
                **result,
                "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
    rejected_attempts = sum(item.get("status") == "rejected" for item in history)
    max_adjustments = int(result["target"]["maxCreativeAdjustments"])
    if result["status"] == "rejected" and rejected_attempts >= max_adjustments + 1:
        result["status"] = "rejected-adjustment-limit"
        result["reason"] = "duration preflight creative-adjustment budget is exhausted"
    report = {
        "schemaVersion": 1,
        **result,
        "attempts": len(history),
        "rejectedAttempts": rejected_attempts,
        "history": history,
        "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    atomic_json(path, report)
    return report
