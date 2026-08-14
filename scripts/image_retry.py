#!/usr/bin/env python3
"""Create and record the one allowed aspect-ratio retry prompt for an illustration."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from project_runtime import atomic_json, image_size, sha256_file


TARGET_RATIO = 16 / 9
TOLERANCE_PCT = 1.0
COMMON_WRONG_RATIOS = ["1:1", "4:3", "3:2", "5:4", "16:10", "9:16", "3:4", "2:3"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ratio_label(width: int, height: int) -> str:
    divisor = math.gcd(width, height)
    exact = f"{width // divisor}:{height // divisor}"
    approximate = Fraction(width / height).limit_denominator(20)
    simple = f"{approximate.numerator}:{approximate.denominator}"
    return exact if exact == simple else f"{exact}（约{simple}）"


def retry_prompt(base: str, width: int, height: int) -> str:
    detected = ratio_label(width, height)
    excluded = ", ".join(dict.fromkeys([detected, *COMMON_WRONG_RATIOS]))
    return (
        f"{base.strip()}\n\n"
        "第二次且最后一次比例纠正：请从宽银幕横向构图的角度重新设计整幅画面，"
        "画布必须是原生16:9横屏（宽高比1.777777…），主体、环境和留白都要自然延伸到左右两侧，"
        "不要先生成其他比例再裁切、补边或加黑边。"
        f"上一次实际输出为{width}×{height}，比例{detected}，必须排除。"
        f"同时排除这些常见非16:9比例：{excluded}。"
        "仅输出一张无文字、无字母、无数字、无Logo、无水印的完整16:9儿童绘本插画。"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("scene_id")
    parser.add_argument("source")
    parser.add_argument("--prompt", help="Override the scene imagePrompt")
    parser.add_argument("--tolerance-pct", type=float, default=TOLERANCE_PCT)
    args = parser.parse_args()

    project = Path(args.project).resolve()
    source = Path(args.source).resolve()
    story_path = project / "public" / "story" / "story.json"
    if not story_path.is_file() or not source.is_file():
        sys.exit("story.json or rejected source image is missing")
    story = json.loads(story_path.read_text(encoding="utf-8"))
    scene = next((item for item in story.get("scenes", []) if str(item.get("id")) == args.scene_id), None)
    prompt = args.prompt or (str(scene.get("imagePrompt", "")).strip() if scene else "")
    if not prompt:
        sys.exit(f"unknown scene/item {args.scene_id}; pass --prompt for reference or probe images")

    width, height = image_size(source)
    error_pct = abs((width / height) / TARGET_RATIO - 1) * 100
    if error_pct <= args.tolerance_pct:
        sys.exit(
            f"source aspect error is {error_pct:.4f}%, within tolerance; normalize it instead of retrying"
        )

    attempts_path = project / "build" / "image-attempts.json"
    if attempts_path.is_file():
        data = json.loads(attempts_path.read_text(encoding="utf-8"))
    else:
        data = {"schemaVersion": 1, "maxAspectRetries": 1, "scenes": {}}
    records = data.setdefault("scenes", {}).setdefault(args.scene_id, [])
    aspect_rejections = [item for item in records if item.get("reason") == "aspect-ratio"]
    allowed = len(aspect_rejections) == 0
    record = {
        "attempt": len(records) + 1,
        "reason": "aspect-ratio",
        "source": str(source),
        "sourceSha256": sha256_file(source),
        "width": width,
        "height": height,
        "aspectErrorPct": round(error_pct, 6),
        "recordedAt": now_iso(),
        "retryAllowed": allowed,
    }
    records.append(record)
    atomic_json(attempts_path, data)

    output = dict(record)
    output["retryPrompt"] = retry_prompt(prompt, width, height) if allowed else None
    output["nextAction"] = (
        "generate-once-with-retryPrompt"
        if allowed
        else "stop-and-report-second-aspect-failure"
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not allowed:
        sys.exit(2)


if __name__ == "__main__":
    main()
