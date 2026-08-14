#!/usr/bin/env python3
"""Content-addressed v2 pipeline state for a kids word story video project."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from duration_control import duration_input
from project_runtime import atomic_json, fingerprint_files, safe_child, sha256_file, sha256_json


STAGES = [
    "initialized",
    "story_validated",
    "duration_preflight_ready",
    "image_probe_passed",
    "images_ready",
    "narration_ready",
    "visual_qa_ready",
    "rendered",
    "mp4_validated",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def state_path(project: Path) -> Path:
    return project / "build" / "state.json"


def stage_record() -> dict:
    return {
        "status": "pending",
        "updatedAt": None,
        "fingerprint": None,
        "evidence": [],
        "details": {},
    }


def default_state(project: Path) -> dict:
    return {
        "schemaVersion": 2,
        "project": str(project),
        "updatedAt": now_iso(),
        "stages": {stage: stage_record() for stage in STAGES},
        "reviews": {"subjectiveAudio": {"status": "pending", "updatedAt": None, "details": {}}},
        "delivery": {"status": "not-delivered", "updatedAt": None, "details": {}},
        "lastFailure": None,
    }


def load_story(project: Path) -> dict:
    path = project / "public" / "story" / "story.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def content_projection(story: dict) -> dict:
    meta = story.get("meta", {})
    meta_keys = (
        "schemaVersion", "category", "series", "width", "height", "imageWidth", "imageHeight",
        "fps", "imageNormalization", "imageAspectTolerancePct", "voice", "rate", "ttsProvider",
        "targetPauseSec", "targetVisualDurationSec", "introTailSec", "durationTarget",
        "introTitle", "pauseTargets", "theme",
    )
    scenes = []
    for scene in story.get("scenes", []):
        scenes.append({key: copy.deepcopy(scene.get(key)) for key in (
            "id", "title", "zh", "image", "imagePrompt", "characterIds",
            "visualRequirements", "imageGeneration"
        )})
    return {
        "meta": {key: copy.deepcopy(meta.get(key)) for key in meta_keys},
        "visualBible": copy.deepcopy(story.get("visualBible")),
        "scenes": scenes,
    }


def image_projection(story: dict) -> dict:
    return {
        "content": content_projection(story),
        "markers": [
            {"id": scene.get("id"), "targetMarkers": copy.deepcopy(scene.get("targetMarkers", {}))}
            for scene in story.get("scenes", [])
        ],
    }


def narration_projection(story: dict) -> dict:
    return {
        "provider": story.get("meta", {}).get("ttsProvider"),
        "voice": story.get("meta", {}).get("voice"),
        "rate": story.get("meta", {}).get("rate"),
        "intro": {key: story.get("meta", {}).get(key) for key in (
            "introTitle", "introAudio", "introAudioDurationSec", "introTailSec", "introTtsInputHash"
        )},
        "scenes": [
            {key: copy.deepcopy(scene.get(key)) for key in (
                "id", "zh", "audio", "audioDurationSec", "ttsAudioInputHash", "ttsTimingInputHash",
                "targetHighlights", "zhChars", "visualTailSec",
            )}
            for scene in story.get("scenes", [])
        ],
    }


def referenced_files(project: Path, relatives: list[str]) -> list[Path]:
    public = project / "public"
    paths: list[Path] = []
    for item in relatives:
        if not item:
            continue
        try:
            paths.append(safe_child(public, item, "story public path")[1])
        except ValueError:
            paths.append(public / "__invalid_path__" / sha256_json(item))
    return paths


def stage_fingerprint(project: Path, stage: str) -> tuple[str, list[dict]]:
    story = load_story(project)
    if stage == "initialized":
        files = [project / name for name in ("package.json", "pnpm-lock.yaml", "requirements.txt", "tsconfig.json")]
        return fingerprint_files(project, files)
    if stage == "story_validated":
        projection = content_projection(story)
        return sha256_json(projection), [{"kind": "story-content", "sha256": sha256_json(projection)}]
    if stage == "duration_preflight_ready":
        report = project / "build" / "duration-preflight.json"
        file_hash, evidence = fingerprint_files(project, [report])
        projection_hash = sha256_json(duration_input(story))
        return sha256_json({"projection": projection_hash, "files": file_hash}), [
            {"kind": "duration-preflight-input", "sha256": projection_hash}, *evidence
        ]
    if stage == "image_probe_passed":
        return fingerprint_files(project, [project / "build" / "image-probe.json"])
    if stage == "images_ready":
        relatives = [str(story.get("visualBible", {}).get("referenceImage", ""))]
        relatives.extend(str(scene.get("image", "")) for scene in story.get("scenes", []))
        files = referenced_files(project, relatives) + [
            project / "public" / "story" / "image-sources.json",
            project / "public" / "story" / "visual-reviews.json",
            project / "build" / "image-generation-plan.json",
        ]
        file_hash, evidence = fingerprint_files(project, files)
        projection_hash = sha256_json(image_projection(story))
        return sha256_json({"projection": projection_hash, "files": file_hash}), [
            {"kind": "image-contract", "sha256": projection_hash}, *evidence
        ]
    if stage == "narration_ready":
        relatives = [str(story.get("meta", {}).get("introAudio", ""))]
        relatives.extend(str(scene.get("audio", "")) for scene in story.get("scenes", []))
        file_hash, evidence = fingerprint_files(project, referenced_files(project, relatives))
        projection_hash = sha256_json(narration_projection(story))
        return sha256_json({"projection": projection_hash, "files": file_hash}), [
            {"kind": "narration-contract", "sha256": projection_hash}, *evidence
        ]
    if stage == "visual_qa_ready":
        manifest = project / "qa" / "manifest.json"
        files = [project / "public" / "story" / "story.json", manifest, project / "qa" / "static-audit.json"]
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            files.extend(project / str(item.get("file", "")) for key in ("targets", "states") for item in data.get(key, []))
        return fingerprint_files(project, files)
    if stage == "rendered":
        return fingerprint_files(project, [
            project / "public" / "story" / "story.json",
            project / "build" / "render-plan.json",
            project / "out" / "story.mp4",
        ])
    if stage == "mp4_validated":
        video = project / "out" / "story.mp4"
        report = project / "build" / "report.json"
        evidence = []
        for path in (video, report):
            evidence.append(
                {"path": str(path.relative_to(project)).replace("\\", "/"), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                if path.is_file() else {"path": str(path.relative_to(project)).replace("\\", "/"), "missing": True}
            )
        # The report contains the video hash, so its own hash is evidence but not part of the stable stage key.
        video_hash = sha256_file(video) if video.is_file() else "MISSING"
        report_video_hash = "MISSING"
        if report.is_file():
            try:
                report_video_hash = str(json.loads(report.read_text(encoding="utf-8")).get("sha256", "MISSING"))
            except json.JSONDecodeError:
                report_video_hash = "INVALID"
        report_hash = sha256_file(report) if report.is_file() else "MISSING"
        return sha256_json({
            "video": video_hash,
            "reportVideo": report_video_hash,
            "reportFile": report_hash,
        }), evidence
    raise ValueError(f"unknown stage: {stage}")


def load_state(project: Path, audit: bool = True) -> dict:
    path = state_path(project)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schemaVersion") != 2:
            raise ValueError("state.json schemaVersion must be 2")
        stages = data.setdefault("stages", {})
        state_changed = False
        for stage in STAGES:
            if stage not in stages:
                stages[stage] = stage_record()
                state_changed = True
        if state_changed:
            data["updatedAt"] = now_iso()
            atomic_json(path, data)
    else:
        data = default_state(project)
        atomic_json(path, data)
    if audit:
        audit_state(project, data)
    return data


def reset_downstream(data: dict, index: int) -> None:
    for downstream in STAGES[index + 1:]:
        data["stages"][downstream] = stage_record()


def audit_state(project: Path, data: dict) -> None:
    changed = False
    for index, stage in enumerate(STAGES):
        record = data["stages"][stage]
        if record.get("status") != "completed":
            continue
        current, _ = stage_fingerprint(project, stage)
        if current != record.get("fingerprint"):
            record["status"] = "stale"
            record.setdefault("details", {})["staleReason"] = "current inputs or outputs no longer match recorded fingerprint"
            reset_downstream(data, index)
            changed = True
            break
    if changed:
        data["updatedAt"] = now_iso()
        atomic_json(state_path(project), data)


def next_stage(data: dict) -> str | None:
    return next((stage for stage in STAGES if data["stages"][stage]["status"] != "completed"), None)


def mark_stage(project: Path, stage: str, details: dict | None = None) -> dict:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    data = load_state(project)
    index = STAGES.index(stage)
    missing = [item for item in STAGES[:index] if data["stages"][item]["status"] != "completed"]
    if missing:
        raise ValueError(f"cannot complete {stage}; prerequisite stages pending or stale: {missing}")
    if stage == "image_probe_passed":
        probe_path = project / "build" / "image-probe.json"
        probe = json.loads(probe_path.read_text(encoding="utf-8")) if probe_path.is_file() else {}
        if probe.get("accepted") is not True:
            raise ValueError("cannot complete image_probe_passed; probe image did not pass aspect policy")
    if stage == "duration_preflight_ready":
        report_path = project / "build" / "duration-preflight.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        if report.get("status") != "passed":
            raise ValueError("cannot complete duration_preflight_ready; actual TTS duration gate did not pass")
        expected_input = sha256_json(duration_input(load_story(project)))
        if report.get("inputSha256") != expected_input:
            raise ValueError("cannot complete duration_preflight_ready; duration report is stale")
    if stage == "visual_qa_ready":
        if not str((details or {}).get("reviewer", "")).strip():
            raise ValueError("visual_qa_ready requires --detail reviewer=<name-or-agent>")
        if (details or {}).get("method") not in {"human", "vision-model"}:
            raise ValueError("visual_qa_ready requires --detail method=human|vision-model")
        audit_path = project / "qa" / "static-audit.json"
        audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else {}
        if audit.get("status") != "passed":
            raise ValueError("visual_qa_ready requires a passed qa/static-audit.json")
    fingerprint, evidence = stage_fingerprint(project, stage)
    if any(item.get("missing") for item in evidence):
        missing_paths = [item["path"] for item in evidence if item.get("missing")]
        raise ValueError(f"cannot complete {stage}; required evidence missing: {missing_paths}")
    reset_downstream(data, index)
    data["stages"][stage] = {
        "status": "completed",
        "updatedAt": now_iso(),
        "fingerprint": fingerprint,
        "evidence": evidence,
        "details": details or {},
    }
    data["updatedAt"] = now_iso()
    data["lastFailure"] = None
    atomic_json(state_path(project), data)
    return data


def fail_stage(project: Path, stage: str, message: str) -> dict:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    data = load_state(project)
    index = STAGES.index(stage)
    reset_downstream(data, index)
    data["stages"][stage] = stage_record()
    data["stages"][stage].update({"status": "failed", "updatedAt": now_iso(), "details": {"message": message}})
    data["lastFailure"] = {"stage": stage, "message": message, "at": now_iso()}
    data["updatedAt"] = now_iso()
    atomic_json(state_path(project), data)
    return data


def set_review(project: Path, status: str, details: dict) -> dict:
    data = load_state(project)
    data["reviews"]["subjectiveAudio"] = {"status": status, "updatedAt": now_iso(), "details": details}
    data["updatedAt"] = now_iso()
    atomic_json(state_path(project), data)
    return data


def set_delivery(project: Path, status: str, details: dict) -> dict:
    data = load_state(project)
    if status == "completed" and data["stages"]["mp4_validated"]["status"] != "completed":
        raise ValueError("cannot mark delivery completed before mp4_validated")
    data["delivery"] = {"status": status, "updatedAt": now_iso(), "details": details}
    data["updatedAt"] = now_iso()
    atomic_json(state_path(project), data)
    return data


def detail_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--details", default="{}", help="Optional JSON object")
    parser.add_argument("--detail", action="append", default=[], metavar="KEY=VALUE")


def parse_details(args: argparse.Namespace) -> dict:
    details = json.loads(args.details)
    if not isinstance(details, dict):
        raise ValueError("--details must be a JSON object")
    for item in args.detail:
        if "=" not in item:
            raise ValueError("--detail must use KEY=VALUE")
        key, value = item.split("=", 1)
        if not key.strip():
            raise ValueError("--detail key must not be empty")
        details[key.strip()] = value
    return details


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    complete = sub.add_parser("complete")
    complete.add_argument("stage", choices=STAGES)
    detail_args(complete)
    failed = sub.add_parser("fail")
    failed.add_argument("stage", choices=STAGES)
    failed.add_argument("message")
    review = sub.add_parser("review-audio")
    review.add_argument("status", choices=("pending", "approved", "rejected"))
    detail_args(review)
    delivery = sub.add_parser("delivery")
    delivery.add_argument("status", choices=("not-delivered", "completed"))
    detail_args(delivery)
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        sys.exit(f"project directory missing: {project}")
    try:
        if args.command == "complete":
            data = mark_stage(project, args.stage, parse_details(args))
        elif args.command == "fail":
            data = fail_stage(project, args.stage, args.message)
        elif args.command == "review-audio":
            data = set_review(project, args.status, parse_details(args))
        elif args.command == "delivery":
            data = set_delivery(project, args.status, parse_details(args))
        else:
            data = load_state(project)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        sys.exit(str(exc))
    print(json.dumps({
        "project": str(project),
        "schemaVersion": data["schemaVersion"],
        "nextStage": next_stage(data),
        "lastFailure": data.get("lastFailure"),
        "reviews": data["reviews"],
        "delivery": data["delivery"],
        "stages": data["stages"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
