#!/usr/bin/env python3
"""Grouped regression tests for timing, projects, assets, duration, and rendering."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


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
        [sys.executable, "-B", str(SCRIPTS / script), *map(str, args)],
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
    duration = load_module("duration_control_self_test", SCRIPTS / "duration_control.py")
    words = [
        {"text": "apple", "start": 0.2, "end": 0.7},
        {"text": "apple", "start": 1.0, "end": 1.4},
    ]
    shifted_zero, highlights_zero, points_zero = tts.apply_target_pauses(
        words, {"apple": "apple"}, 0.0, 1.2
    )
    assert shifted_zero == words
    assert [item["spokenDurationSec"] for item in highlights_zero] == [0.5, 0.4]
    assert [item["visualDurationSec"] for item in highlights_zero] == [1.2, 1.2]
    assert [item["displayWord"] for item in highlights_zero] == ["apple", "apple"]
    assert points_zero == []

    shifted_pause, highlights_pause, pause_points = tts.apply_target_pauses(
        words, {"apple": "apple"}, 0.3, 1.2
    )
    assert shifted_pause[1]["start"] == 1.3
    assert [item["spokenDurationSec"] for item in highlights_pause] == [0.5, 0.4]
    assert [item["visualDurationSec"] for item in highlights_pause] == [1.2, 1.2]
    assert pause_points == [0.7, 1.4]
    _, uppercase_highlights, _ = tts.apply_target_pauses(
        words[:1], {"apple": "Apple"}, 0.0, 1.2
    )
    assert uppercase_highlights[0]["word"] == "apple"
    assert uppercase_highlights[0]["displayWord"] == "Apple"

    assert duration.event_spoken_duration_sec(
        {"spokenDurationSec": 0.25, "visualDurationSec": 1.2}
    ) == 0.25
    assert duration.event_spoken_duration_sec({}) == 0.0
    assert duration.event_visual_duration_sec(
        {"visualDurationSec": 0.8},
        {"targetPauseSec": 0.3, "targetVisualDurationSec": 1.2},
    ) == 1.2
    with tempfile.TemporaryDirectory(prefix="kids-word-zero-pause-") as temp:
        source = Path(temp) / "source.mp3"
        destination = Path(temp) / "destination.mp3"
        source.write_bytes(b"no-silence-inserted")
        tts.insert_silence_after_words(
            "definitely-missing-ffmpeg", source, destination, [0.2], 0.0
        )
        assert destination.read_bytes() == b"no-silence-inserted"

    base_story = {
        "meta": {
            "fps": 20,
            "introAudioDurationSec": 1.0,
            "introTailSec": 0.6,
            "targetPauseSec": 0.0,
            "targetVisualDurationSec": 1.2,
        },
        "scenes": [{
            "id": "01", "audioDurationSec": 2.0,
            "targetHighlights": [{
                "word": "apple", "start": 0.2,
                "spokenDurationSec": 0.5, "visualDurationSec": 1.2,
            }],
        }],
    }
    _, _, states_zero = qa.build_jobs(base_story, "test")
    names_zero = {item["name"] for item in states_zero}
    assert "word-pause" not in names_zero
    assert "word-visual-mid" in names_zero
    body_first = next(item["frame"] for item in states_zero if item["name"] == "body-first")
    word_after = next(item["frame"] for item in states_zero if item["name"] == "word-after")
    assert body_first == 32
    assert word_after - (body_first + round(0.2 * 20)) >= 24
    base_story["meta"]["targetPauseSec"] = 0.3
    _, _, states_pause = qa.build_jobs(base_story, "test")
    assert "word-pause" in {item["name"] for item in states_pause}


def test_saved_node_typecheck_command(root: Path) -> None:
    runtime = load_module("project_runtime_typecheck_self_test", SCRIPTS / "project_runtime.py")
    typecheck = load_module("qa_typecheck_self_test", SCRIPTS / "qa_typecheck.py")
    project = root / "node-typecheck"
    node = project / "runtime" / "node.exe"
    tsc = project / "node_modules" / "typescript" / "bin" / "tsc"
    node.parent.mkdir(parents=True)
    tsc.parent.mkdir(parents=True)
    node.write_bytes(b"test")
    tsc.write_text("require('../lib/tsc.js');\n", encoding="utf-8")
    runtime.atomic_json(project / "build" / "toolchain.json", {"node": str(node.resolve())})
    command = typecheck.typecheck_command(project)
    assert command == [str(node.resolve()), str(tsc.resolve()), "--noEmit"]

    runtime.atomic_json(project / "build" / "toolchain.json", {"node": "node"})
    try:
        typecheck.typecheck_command(project)
    except ValueError as exc:
        assert "absolute executable file" in str(exc)
    else:
        raise AssertionError("relative Node path must not fall back to PATH")


def test_project_defaults_and_visual_timing(root: Path) -> None:
    confirmation = (SKILL / "references" / "confirmation-card.md").read_text(encoding="utf-8")
    assert "目标词：" + "<数量>" not in confirmation
    assert "至少约1.2秒" in confirmation
    project = root / "project"
    run("new_project.py", "--output", project)
    defaults = story(project)["meta"]
    state_data = json.loads((project / "build" / "state.json").read_text(encoding="utf-8"))
    assert list(state_data["stages"])[2] == "duration_preflight_ready"
    assert defaults["targetPauseSec"] == 0.0
    assert defaults["targetVisualDurationSec"] == 1.2
    assert defaults["introTailSec"] == 0.6
    assert defaults["durationTarget"] == {
        "targetSec": 330.0,
        "idealMinSec": 300.0,
        "idealMaxSec": 360.0,
        "acceptableMinSec": 285.0,
        "acceptableMaxSec": 375.0,
        "maxCreativeAdjustments": 2,
    }
    scene_source = (project / "src" / "Scene.tsx").read_text(encoding="utf-8")
    assert "fontSize: 36" in scene_source
    assert "[1, 1.05, 1]" in scene_source
    assert "activeByWord" in scene_source and "collisionOffsetY" in scene_source
    assert "{event.displayWord}" in scene_source

    run("storyctl.py", project, "set-meta", "targetPauseSec", "0.3")
    assert story(project)["meta"]["targetPauseSec"] == 0.3
    rejected_pause = run(
        "storyctl.py", project, "set-meta", "targetPauseSec", "-0.1", expect=1
    )
    assert "nonnegative" in rejected_pause.stderr
    run("storyctl.py", project, "set-meta", "targetPauseSec", "0")

    run("storyctl.py", project, "init-meta", "--title", "苹果小路", "--targets", "apple")
    run("storyctl.py", project, "set-meta", "introTitle", "《月亮邮差》")
    assert story(project)["meta"]["introTitle"] == "《月亮邮差》"
    run("storyctl.py", project, "set-meta", "introTitle", "苹果小路")
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
        "--critical-action", "--action-subject", "小熊", "--body-part-or-tool", "右前爪",
        "--action-object", "苹果", "--contact", "爪垫贴住苹果侧面",
        "--relative-position", "小熊在苹果左侧", "--direction", "由下向上",
        "--result", "苹果离开地面进入爪中", "--forbid-alternative", "只指向苹果",
    )
    authored = story(project)["scenes"][0]
    assert authored["visualRequirements"]["criticalAction"]["bodyPartOrTool"] == "右前爪"
    assert "爪垫贴住苹果侧面" in authored["imagePrompt"]
    run("validate_story.py", project, "--stage", "content", "--no-state")

    omitted_action_detail = story(project)
    original_prompt = omitted_action_detail["scenes"][0]["imagePrompt"]
    omitted_action_detail["scenes"][0]["imagePrompt"] = original_prompt.replace("爪垫贴住苹果侧面", "")
    (project / "public" / "story" / "story.json").write_text(
        json.dumps(omitted_action_detail, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    action_error = run("validate_story.py", project, "--stage", "content", "--no-state", expect=1)
    assert "omits critical action details" in action_error.stdout
    omitted_action_detail["scenes"][0]["imagePrompt"] = original_prompt
    (project / "public" / "story" / "story.json").write_text(
        json.dumps(omitted_action_detail, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    changed_case = story(project)
    original_zh = changed_case["scenes"][0]["zh"]
    changed_case["scenes"][0]["zh"] = original_zh.replace("apple", "Apple", 1)
    (project / "public" / "story" / "story.json").write_text(
        json.dumps(changed_case, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    spelling_error = run("validate_story.py", project, "--stage", "content", "--no-state", expect=1)
    assert "changes target spelling or letter case" in spelling_error.stdout
    changed_case["scenes"][0]["zh"] = original_zh
    (project / "public" / "story" / "story.json").write_text(
        json.dumps(changed_case, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    duplicate_ids = story(project)
    duplicate_ids["scenes"].append(dict(duplicate_ids["scenes"][0]))
    (project / "public" / "story" / "story.json").write_text(
        json.dumps(duplicate_ids, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    duplicate_error = run("validate_story.py", project, "--stage", "content", "--no-state", expect=1)
    assert "scene ids must be unique" in duplicate_error.stdout
    duplicate_ids["scenes"].pop()
    (project / "public" / "story" / "story.json").write_text(
        json.dumps(duplicate_ids, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    escaped_path = story(project)
    original_image = escaped_path["scenes"][0]["image"]
    escaped_path["scenes"][0]["image"] = "assets/../../outside.png"
    (project / "public" / "story" / "story.json").write_text(
        json.dumps(escaped_path, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    path_error = run("validate_story.py", project, "--stage", "content", "--no-state", expect=1)
    assert "escapes" in path_error.stdout
    escaped_path["scenes"][0]["image"] = original_image
    (project / "public" / "story" / "story.json").write_text(
        json.dumps(escaped_path, ensure_ascii=False, indent=2), encoding="utf-8"
    )
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


def test_static_audit_ratios(root: Path) -> None:
    project = root / "static-audit"
    (project / "src").mkdir(parents=True)
    source = project / "src" / "timing.ts"
    source.write_text("export const timestamp = '13:26';\n", encoding="utf-8")
    passed = run("static_audit.py", project)
    assert json.loads(passed.stdout)["status"] == "passed"
    source.write_text("export const forbidden = 'native 3:2';\n", encoding="utf-8")
    failed = run("static_audit.py", project, expect=1)
    findings = json.loads(failed.stdout)["findings"]
    assert any(item["rule"] == "three-two-art" for item in findings)


def fake_png(path: Path, width: int = 1280, height: int = 720) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)
    )


def test_chinese_path_and_missing_manifest(root: Path) -> None:
    runtime = load_module("project_runtime_self_test", SCRIPTS / "project_runtime.py")
    project = root / "中文目录" / "故事项目"
    run("new_project.py", "--output", project)
    run("storyctl.py", project, "init-meta", "--title", "小熊寻找红苹果", "--targets", "apple")
    run(
        "storyctl.py", project, "set-visual-bible", "--style", "native 16:9 watercolor",
        "--palette", "warm", "--reference", "reference/characters.png",
    )
    run(
        "storyctl.py", project, "add-character", "hero", "--name", "小熊", "--role", "主角",
        "--appearance", "棕色小熊", "--must-keep", "红围巾",
    )
    run(
        "storyctl.py", project, "add-scene", "01", "--title", "找到苹果",
        "--zh", "小熊绕过长长的小路，在树下看见 apple，又把 apple 轻轻放进篮子。",
        "--image", "assets/red-apple.png", "--prompt", "native 16:9 小熊拿苹果 no text",
        "--character", "hero", "--must-show", "小熊和苹果", "--action", "小熊拿起苹果",
    )
    run(
        "storyctl.py", project, "set-marker", "01", "apple", "--x", "55", "--y", "50",
        "--reviewer", "self-test",
    )
    assert "size" not in story(project)["scenes"][0]["targetMarkers"]["apple"]
    note = project / "构建日志.md"
    note.write_text("中文路径与 UTF-8 内容完整。\n", encoding="utf-8")
    assert note.read_text(encoding="utf-8") == "中文路径与 UTF-8 内容完整。\n"

    source = root / "中文源图.png"
    fake_png(source)
    run("normalize_image.py", project, source, "reference")
    run("normalize_image.py", project, source, "01")
    run("image_batch_plan.py", project)
    manifest_path = project / "public" / "story" / "image-sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["assets"]) == 2
    assert {item["final"] for item in manifest["assets"]} == {
        "reference/characters.png", "assets/red-apple.png"
    }
    assert not manifest_path.with_suffix(".json.tmp").exists()

    unknown_scene = run("normalize_image.py", project, source, "assets/rogue.png", expect=1)
    assert "scene ID must identify exactly one story scene" in unknown_scene.stderr

    run("visual_review.py", project, "init")
    for item in ("reference", "01"):
        run(
            "visual_review.py", project, "record", item, "--status", "passed",
            "--reviewer", "self-test", "--method", "vision-model", "--confidence", "1",
            "--observed", "合同内容清楚可见",
        )

    manifest["assets"] = [
        item for item in manifest["assets"] if item["final"] != "assets/red-apple.png"
    ]
    runtime.atomic_json(manifest_path, manifest)
    failed = run("validate_story.py", project, "--stage", "assets", "--no-state", expect=1)
    result = json.loads(failed.stdout)
    assert "image provenance missing for assets/red-apple.png" in result["errors"]

    run("normalize_image.py", project, source, "01")
    extra = project / "public" / "assets" / "unused.png"
    fake_png(extra)
    failed = run("validate_story.py", project, "--stage", "assets", "--no-state", expect=1)
    result = json.loads(failed.stdout)
    assert "unreferenced final image file: assets/unused.png" in result["errors"]
    extra.unlink()

    orphan_raw = project / "public" / "raw" / "orphan.png"
    fake_png(orphan_raw)
    failed = run("validate_story.py", project, "--stage", "assets", "--no-state", expect=1)
    result = json.loads(failed.stdout)
    assert "unreferenced raw image file: raw/orphan.png" in result["errors"]
    orphan_raw.unlink()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    extra_entry = dict(manifest["assets"][0])
    extra_entry["final"] = "assets/not-in-story.png"
    manifest["assets"].append(extra_entry)
    runtime.atomic_json(manifest_path, manifest)
    failed = run("validate_story.py", project, "--stage", "assets", "--no-state", expect=1)
    result = json.loads(failed.stdout)
    assert (
        "image provenance contains unreferenced final asset: assets/not-in-story.png"
        in result["errors"]
    )


def test_duration_gate_blocks_four_minutes(root: Path) -> None:
    duration = load_module("duration_control_gate_self_test", SCRIPTS / "duration_control.py")
    state = load_module("pipeline_state_gate_self_test", SCRIPTS / "pipeline_state.py")
    project = root / "duration-gate"
    run("new_project.py", "--output", project)
    data = story(project)
    data["meta"]["introAudioDurationSec"] = 0.4
    data["scenes"] = [
        {"id": f"{index:02d}", "zh": "自然剧情", "audioDurationSec": 10.0, "targetHighlights": []}
        for index in range(1, 25)
    ]
    result = duration.evaluate_duration(data)
    assert result["status"] == "rejected"
    assert 240 < result["estimatedDurationSec"] < 242
    for scene in data["scenes"]:
        scene["audioDurationSec"] = 13.7
    accepted = duration.evaluate_duration(data)
    assert accepted["status"] == "passed"
    assert accepted["withinIdealRange"] is True

    state.mark_stage(project, "story_validated", {"selfTest": True})
    probe_path = project / "build" / "image-probe.json"
    runtime = load_module("project_runtime_gate_self_test", SCRIPTS / "project_runtime.py")
    runtime.atomic_json(probe_path, {"accepted": True})
    try:
        state.mark_stage(project, "image_probe_passed", {"selfTest": True})
    except ValueError as exc:
        assert "duration_preflight_ready" in str(exc)
    else:
        raise AssertionError("four-minute story entered the illustration stage without duration preflight")


def test_image_batch_planning_and_critical_action() -> None:
    planner = load_module("image_batch_plan_self_test", SCRIPTS / "image_batch_plan.py")
    story_data = {
        "scenes": [
            {"id": "01", "imageGeneration": {"dependsOn": [], "serialReasons": []}},
            {"id": "02", "imageGeneration": {"dependsOn": [], "serialReasons": []}},
            {"id": "03", "imageGeneration": {"dependsOn": [], "serialReasons": []}},
            {"id": "04", "imageGeneration": {"dependsOn": [], "serialReasons": []}},
            {
                "id": "05",
                "imageGeneration": {
                    "dependsOn": ["04"],
                    "serialReasons": ["prop-state"],
                },
            },
            {"id": "06", "imageGeneration": {"dependsOn": [], "serialReasons": []}},
        ]
    }
    plan = planner.build_plan(story_data, [], False)
    assert plan["maxParallelScenes"] == 3
    assert plan["batches"][0]["sceneIds"] == ["01", "02", "03"]
    assert next(batch for batch in plan["batches"] if "05" in batch["sceneIds"])["mode"] == "serial"
    retry = planner.build_plan(story_data, ["05", "06"], False, ["01", "05"])
    assert retry["preserveExistingPassedImages"] is True
    assert retry["preservedSceneIds"] == ["01"]
    assert all(batch["mode"] == "serial-retry" and len(batch["sceneIds"]) == 1 for batch in retry["batches"])
    forced = planner.build_plan(story_data, [], True)
    assert all(batch["mode"] == "serial" and len(batch["sceneIds"]) == 1 for batch in forced["batches"])
    preserved = planner.build_plan(story_data, [], True, ["01", "02"])
    assert preserved["preservedSceneIds"] == ["01", "02"]
    assert not ({"01", "02"} & {item for batch in preserved["batches"] for item in batch["sceneIds"]})
    invalid_dependencies = {"scenes": [
        {"id": "01", "imageGeneration": {"dependsOn": ["02"], "serialReasons": []}},
        {"id": "02", "imageGeneration": {"dependsOn": [], "serialReasons": []}},
    ]}
    try:
        planner.build_plan(invalid_dependencies, [], False)
    except ValueError as exc:
        assert "must be earlier scenes" in str(exc)
    else:
        raise AssertionError("future image dependency was accepted")

    storyctl = load_module("storyctl_action_self_test", SCRIPTS / "storyctl.py")
    args = SimpleNamespace(
        critical_action=True,
        action_subject="小熊",
        body_part_or_tool="右前爪",
        action_object="杯子",
        contact="爪垫贴住杯柄",
        relative_position="小熊在杯子左侧",
        direction="向右上方",
        result="杯子被提离桌面",
        forbid_alternative=["只碰杯沿"],
    )
    action = storyctl.critical_action_from_args(args)
    assert action is not None
    clause = storyctl.action_prompt_clause(action)
    for value in ("小熊", "右前爪", "杯子", "爪垫贴住杯柄", "小熊在杯子左侧", "向右上方", "杯子被提离桌面", "只碰杯沿"):
        assert value in clause
    args.result = None
    try:
        storyctl.critical_action_from_args(args)
    except ValueError as exc:
        assert "missing required details" in str(exc)
    else:
        raise AssertionError("incomplete critical action contract was accepted")


def test_render_wait_and_timeout(root: Path) -> None:
    render = load_module("render_story_self_test", SCRIPTS / "render_story.py")
    assert render.render_timeout_sec(1) == 1200
    assert render.render_timeout_sec(4) == 4800
    try:
        render.render_timeout_sec(2, 1200)
    except ValueError as exc:
        assert "at least 2400" in str(exc)
    else:
        raise AssertionError("segmented render accepted an undersized timeout")

    log = root / "render-wait.log"
    start = time.monotonic()
    render.run_logged(
        [sys.executable, "-c", "pass"], root, log, dict(os.environ), time.monotonic() + 2
    )
    assert time.monotonic() - start < 2
    start = time.monotonic()
    try:
        render.run_logged(
            [sys.executable, "-c", "import sys; sys.exit(7)"],
            root,
            log,
            dict(os.environ),
            time.monotonic() + 2,
        )
    except RuntimeError as exc:
        assert "exit code 7" in str(exc)
        assert time.monotonic() - start < 2
    else:
        raise AssertionError("explicit render-process failure did not return immediately")
    try:
        render.run_logged(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            root,
            log,
            dict(os.environ),
            time.monotonic() + 0.2,
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("silent render process was not stopped at the configured deadline")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--group",
        action="append",
        choices=("timing", "project", "assets", "duration", "images", "render"),
        help="Run one or more focused groups; omit to run all groups",
    )
    args = parser.parse_args()
    selected = set(args.group or ("timing", "project", "assets", "duration", "images", "render"))
    with tempfile.TemporaryDirectory(prefix="kids-word-story-video-self-test-") as temp:
        root = Path(temp)
        groups = {
            "timing": (lambda: test_pause_logic(),),
            "project": (
                lambda: test_saved_node_typecheck_command(root),
                lambda: test_project_defaults_and_visual_timing(root),
            ),
            "assets": (
                lambda: test_static_audit_ratios(root),
                lambda: test_chinese_path_and_missing_manifest(root),
            ),
            "duration": (lambda: test_duration_gate_blocks_four_minutes(root),),
            "images": (lambda: test_image_batch_planning_and_critical_action(),),
            "render": (lambda: test_render_wait_and_timeout(root),),
        }
        for group, tests in groups.items():
            if group not in selected:
                continue
            print(f"[self-test] {group}")
            for test in tests:
                test()
    print("self-test passed")


if __name__ == "__main__":
    main()
