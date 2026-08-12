#!/usr/bin/env python3
"""Record evidence-backed visual semantic reviews for reference and scene images."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from project_runtime import atomic_json, sha256_file, sha256_json


ACCEPTED_STATUSES = ("passed", "accepted-minor")
STATUSES = ("pending", *ACCEPTED_STATUSES, "retry-required", "rejected")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def review_path(project: Path) -> Path:
    return project / "public" / "story" / "visual-reviews.json"


def public_file(project: Path, relative: str) -> Path:
    public = (project / "public").resolve()
    path = (public / relative.replace("\\", "/").lstrip("/")).resolve()
    try:
        path.relative_to(public)
    except ValueError as exc:
        raise ValueError(f"visual path escapes public/: {relative}") from exc
    return path


def expected_items(project: Path, story: dict) -> dict:
    visual = story.get("visualBible", {})
    items = {
        "reference": {
            "image": visual.get("referenceImage"),
            "requirements": {
                "mustShow": [f"{item.get('name')}: {item.get('appearance')}" for item in visual.get("characters", [])],
                "mustNotShow": ["文字", "字母", "数字", "Logo", "水印"],
                "action": "角色参考图清楚展示所有主要角色的固定外观",
                "continuity": [trait for item in visual.get("characters", []) for trait in item.get("mustKeep", [])],
            },
        }
    }
    for scene in story.get("scenes", []):
        items[str(scene.get("id"))] = {
            "image": scene.get("image"),
            "requirements": scene.get("visualRequirements", {}),
        }
    return items


def initialize(project: Path, story: dict) -> dict:
    path = review_path(project)
    old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    records = {}
    for item_id, expected in expected_items(project, story).items():
        image = public_file(project, str(expected.get("image", "")))
        image_hash = sha256_file(image) if image.is_file() else None
        requirement_hash = sha256_json(expected.get("requirements", {}))
        previous = old.get("items", {}).get(item_id, {})
        history = previous.get("history", []) if isinstance(previous.get("history"), list) else []
        reusable = (
            previous.get("imageSha256") == image_hash
            and previous.get("requirementsSha256") == requirement_hash
            and previous.get("status") in ACCEPTED_STATUSES
        )
        records[item_id] = previous if reusable else {
            "status": "pending", "image": expected.get("image"), "imageSha256": image_hash,
            "requirements": expected.get("requirements", {}), "requirementsSha256": requirement_hash,
            "reviewer": None, "reviewMethod": None, "confidence": None, "observed": [], "issues": [],
            "updatedAt": None, "history": history,
        }
    data = {"schemaVersion": 1, "policy": {"maxSemanticRetries": 2}, "items": records}
    atomic_json(path, data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    record = sub.add_parser("record")
    record.add_argument("item", help="scene id or reference")
    record.add_argument("--status", choices=STATUSES[1:], required=True)
    record.add_argument("--reviewer", required=True)
    record.add_argument("--method", choices=("human", "vision-model"), required=True)
    record.add_argument("--confidence", type=float, required=True)
    record.add_argument("--observed", action="append", default=[])
    record.add_argument("--issue", action="append", default=[])
    sub.add_parser("status")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    story_path = project / "public" / "story" / "story.json"
    if not story_path.is_file():
        sys.exit(f"story file missing: {story_path}")
    story = json.loads(story_path.read_text(encoding="utf-8"))
    data = initialize(project, story)
    if args.command == "record":
        if args.item not in data["items"]:
            sys.exit(f"unknown visual review item: {args.item}")
        if not 0 <= args.confidence <= 1:
            sys.exit("confidence must be between 0 and 1")
        item = data["items"][args.item]
        if not item.get("imageSha256"):
            sys.exit(f"image is missing for visual review item {args.item}")
        if args.status == "passed" and args.issue:
            sys.exit("a passed visual review cannot contain issues")
        retry_count = sum(entry.get("status") == "retry-required" for entry in item.get("history", []))
        attempted_hashes = {
            entry.get("imageSha256")
            for entry in item.get("history", [])
            if entry.get("status") in {"retry-required", "rejected"}
        }
        if args.status == "retry-required" and item.get("imageSha256") in attempted_hashes:
            sys.exit("semantic retry requires a newly generated candidate image")
        rejected_after_retries = any(
            entry.get("status") == "rejected" for entry in item.get("history", [])
        )
        if args.status == "accepted-minor":
            if retry_count < int(data["policy"]["maxSemanticRetries"]) or not rejected_after_retries:
                sys.exit("accepted-minor requires the initial image plus two exhausted semantic retries")
            if not args.issue:
                sys.exit("accepted-minor requires at least one specific minor-deviation issue")
            if item.get("imageSha256") not in attempted_hashes:
                sys.exit("accepted-minor must select one of the three already reviewed candidate images")
        status = args.status
        if status == "retry-required" and retry_count >= int(data["policy"]["maxSemanticRetries"]):
            status = "rejected"
            args.issue.append("semantic retry budget exhausted")
        attempt = {
            "status": status, "imageSha256": item.get("imageSha256"), "reviewer": args.reviewer,
            "reviewMethod": args.method, "confidence": args.confidence, "observed": args.observed,
            "issues": args.issue, "reviewedAt": now_iso(),
        }
        item.setdefault("history", []).append(attempt)
        item.update({
            "status": status, "reviewer": args.reviewer, "reviewMethod": args.method,
            "confidence": args.confidence, "observed": args.observed, "issues": args.issue,
            "updatedAt": now_iso(),
        })
        if status == "retry-required":
            requirements = item.get("requirements", {})
            item["retryPrompt"] = (
                "重新生成同一幕，保持原故事和角色设定。必须满足："
                + "；".join(map(str, requirements.get("mustShow", [])))
                + "。必须排除："
                + "；".join(map(str, requirements.get("mustNotShow", [])))
                + "。修正已发现问题："
                + "；".join(args.issue)
            )
        else:
            item.pop("retryPrompt", None)
        atomic_json(review_path(project), data)
    summary = {
        "path": str(review_path(project)),
        "counts": {status: sum(item.get("status") == status for item in data["items"].values()) for status in STATUSES},
        "items": data["items"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.command == "status" and any(
        item.get("status") not in ACCEPTED_STATUSES for item in data["items"].values()
    ):
        sys.exit(2)


if __name__ == "__main__":
    main()
