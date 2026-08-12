#!/usr/bin/env python3
"""Regression tests for configurable pauses and bounded visual fallback."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def run(script: str, *args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != expect:
        raise AssertionError(
            f"{script} returned {proc.returncode}, expected {expect}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def story(project: Path) -> dict:
    return json.loads((project / "public" / "story" / "story.json").read_text(encoding="utf-8"))


def test_pause_logic() -> None:
    tts = load_module("tts_generate_self_test", SCRIPTS / "tts_generate.py")
    qa = load_module("qa_keyframes_self_test", SCRIPTS / "qa_keyframes.py")
    words = [
        {"text": "apple", "start": 0.2, "end": 0.7},
        {"text": "apple", "start": 1.0, "end": 1.4},
    ]
    shifted_zero, highlights_zero, points_zero = tts.apply_target_pauses(
        words, {"apple"}, 0.0, 1.0, True
    )
    assert shifted_zero == words
    assert [item["duration"] for item in highlights_zero] == [0.5, 0.4]
    assert points_zero == [0.7, 1.4]

    shifted_pause, highlights_pause, _ = tts.apply_target_pauses(
        words, {"apple"}, 0.3, 1.0, True
    )
    assert shifted_pause[1]["start"] == 1.3
    assert [item["duration"] for item in highlights_pause] == [0.8, 0.7]

    base_story = {
        "meta": {"fps": 20, "introAudioDurationSec": 1.0, "targetPauseSec": 0.0},
        "scenes": [{
            "id": "01", "audioDurationSec": 2.0,
            "targetHighlights": [{"word": "apple", "start": 0.2, "duration": 0.5}],
        }],
    }
    _, _, states_zero = qa.build_jobs(base_story, "test")
    assert "word-pause" not in {item["name"] for item in states_zero}
    base_story["meta"]["targetPauseSec"] = 0.3
    base_story["scenes"][0]["targetHighlights"][0]["duration"] = 0.8
    _, _, states_pause = qa.build_jobs(base_story, "test")
    assert "word-pause" in {item["name"] for item in states_pause}


def test_project_defaults_and_visual_fallback(root: Path) -> None:
    project = root / "project"
    run("new_project.py", "--output", project)
    assert story(project)["meta"]["targetPauseSec"] == 0.0
    scene_source = (project / "src" / "Scene.tsx").read_text(encoding="utf-8")
    assert "fontSize: 36" in scene_source

    run("storyctl.py", project, "set-meta", "targetPauseSec", "0.3")
    assert story(project)["meta"]["targetPauseSec"] == 0.3
    rejected_pause = run(
        "storyctl.py", project, "set-meta", "targetPauseSec", "-0.1", expect=1
    )
    assert "nonnegative" in rejected_pause.stderr
    run("storyctl.py", project, "set-meta", "targetPauseSec", "0")

    run("storyctl.py", project, "init-meta", "--title", "苹果小路", "--targets", "apple")
    run(
        "storyctl.py", project, "set-visual-bible", "--style", "native 16:9 watercolor",
        "--palette", "warm", "--reference", "reference/characters.png",
    )
    run(
        "storyctl.py", project, "add-character", "hero", "--name", "小熊", "--role", "主角",
        "--appearance", "棕色小熊", "--must-keep", "红围巾",
    )
    run(
        "storyctl.py", project, "add-scene", "01", "--title", "拿苹果",
        "--zh", "小熊看见 apple，轻轻拿起 apple。", "--image", "assets/scene-01.png",
        "--prompt", "native 16:9 小熊拿苹果 no text", "--character", "hero",
        "--must-show", "小熊和苹果", "--action", "小熊轻轻拿起苹果",
    )
    run("validate_story.py", project, "--stage", "content", "--no-state")
    run("storyctl.py", project, "set-meta", "targetPauseSec", "0.3")
    run("validate_story.py", project, "--stage", "content", "--no-state")
    run("storyctl.py", project, "set-meta", "targetPauseSec", "0")

    sources = [SKILL / "SKILL.md", SKILL / "references" / "confirmation-card.md", SKILL / "references" / "story-contract.md"]
    reference = project / "public" / "reference" / "characters.png"
    candidate = project / "public" / "assets" / "scene-01.png"
    shutil.copyfile(sources[0], reference)
    shutil.copyfile(sources[0], candidate)
    run("visual_review.py", project, "init")
    early_accept = run(
        "visual_review.py", project, "record", "01", "--status", "accepted-minor",
        "--reviewer", "test", "--method", "vision-model", "--confidence", "0.8",
        "--issue", "轻微偏差", expect=1,
    )
    assert "requires the initial image plus two" in early_accept.stderr

    for index, source in enumerate(sources):
        shutil.copyfile(source, candidate)
        result = run(
            "visual_review.py", project, "record", "01", "--status", "retry-required",
            "--reviewer", "test", "--method", "vision-model", "--confidence", "0.6",
            "--issue", f"candidate {index + 1} deviation",
        )
    assert json.loads(result.stdout)["items"]["01"]["status"] == "rejected"

    accepted = run(
        "visual_review.py", project, "record", "01", "--status", "accepted-minor",
        "--reviewer", "test", "--method", "vision-model", "--confidence", "0.78",
        "--issue", "手掌接触点受透视影响但目标词与核心动作清楚",
    )
    assert json.loads(accepted.stdout)["items"]["01"]["status"] == "accepted-minor"

    large_change = run(
        "storyctl.py", project, "adjust-scene", "01", "--zh", "apple apple",
        "--reason", "匹配最佳候选", expect=1,
    )
    assert "too large" in large_change.stderr
    run(
        "storyctl.py", project, "adjust-scene", "01",
        "--zh", "小熊看见 apple，慢慢拿起 apple。",
        "--action", "小熊慢慢拿起苹果", "--reason", "匹配最佳候选中的动作速度",
        "--replace-must-show", "小熊和苹果", "小熊靠近苹果",
    )
    updated = story(project)["scenes"][0]
    assert updated["zh"] == "小熊看见 apple，慢慢拿起 apple。"
    assert updated["minorVisualAdjustments"][0]["changedFields"] == [
        "zh", "visualRequirements.action", "visualRequirements.mustShow"
    ]


def main() -> None:
    test_pause_logic()
    with tempfile.TemporaryDirectory(prefix="kids-word-story-video-self-test-") as temp:
        test_project_defaults_and_visual_fallback(Path(temp))
    print("self-test passed")


if __name__ == "__main__":
    main()
