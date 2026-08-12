#!/usr/bin/env python3
"""Generate deterministic local WAV sound effects from project recipes."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import struct
import sys
import wave
from pathlib import Path

from pipeline_state import mark_stage


def safe_public_path(public: Path, relative: str) -> Path:
    resolved = (public / relative.replace("\\", "/").lstrip("/")).resolve()
    try:
        resolved.relative_to(public.resolve())
    except ValueError:
        raise ValueError(f"path escapes project public directory: {relative}")
    return resolved


def envelope(t: float, duration: float, attack: float, decay: float) -> float:
    attack_gain = min(1.0, t / max(attack, 1e-6))
    release_start = max(attack, duration * 0.75)
    release_gain = 1.0 if t <= release_start else max(0.0, (duration - t) / max(duration - release_start, 1e-6))
    return attack_gain * release_gain * math.exp(-decay * t)


def render_recipe(recipe: dict, sample_rate: int) -> list[int]:
    kind = str(recipe.get("kind", "tone"))
    duration = float(recipe.get("durationSec", 0))
    if not 0.05 <= duration <= 10:
        raise ValueError("durationSec must be between 0.05 and 10 seconds")
    count = max(1, round(duration * sample_rate))
    volume = min(1.0, max(0.0, float(recipe.get("volume", 0.65))))
    attack = max(0.001, float(recipe.get("attackSec", 0.02)))
    decay = max(0.0, float(recipe.get("decay", 1.5)))
    frequencies = [float(value) for value in recipe.get("frequencies", [440])]
    start_hz = float(recipe.get("startHz", frequencies[0] if frequencies else 440))
    end_hz = float(recipe.get("endHz", start_hz))
    noise_mix = min(1.0, max(0.0, float(recipe.get("noiseMix", 0.35))))
    smoothing = min(0.999, max(0.0, float(recipe.get("smoothing", 0.92))))
    rng = random.Random(int(recipe.get("seed", 20260811)))
    smooth_noise = 0.0
    output: list[int] = []

    for index in range(count):
        t = index / sample_rate
        gain = envelope(t, duration, attack, decay)
        tone = 0.0
        if kind in {"tone", "hybrid"}:
            tone = sum(math.sin(2 * math.pi * hz * t) for hz in frequencies) / max(1, len(frequencies))
        elif kind == "sweep":
            phase = 2 * math.pi * (start_hz * t + 0.5 * (end_hz - start_hz) * t * t / duration)
            tone = math.sin(phase)

        raw_noise = rng.uniform(-1.0, 1.0)
        smooth_noise = smoothing * smooth_noise + (1 - smoothing) * raw_noise
        normalized_noise = max(-1.0, min(1.0, smooth_noise * 5))

        if kind == "noise":
            sample = normalized_noise
        elif kind == "hybrid":
            sample = (1 - noise_mix) * tone + noise_mix * normalized_noise
        elif kind in {"tone", "sweep"}:
            sample = tone
        else:
            raise ValueError(f"unsupported kind {kind!r}; use tone, sweep, noise, or hybrid")
        output.append(round(max(-1.0, min(1.0, sample * gain * volume)) * 32767))
    return output


def write_wav(path: Path, samples: list[int], sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp.wav")
    with wave.open(str(temp), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"".join(struct.pack("<h", value) for value in samples))
    os.replace(temp, path)


def atomic_story(path: Path, story: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    public = project / "public"
    recipes_path = public / "story" / "sfx-recipes.json"
    story_path = public / "story" / "story.json"
    if not recipes_path.is_file() or not story_path.is_file():
        sys.exit("sfx-recipes.json or story.json is missing")

    recipes = json.loads(recipes_path.read_text(encoding="utf-8"))
    story = json.loads(story_path.read_text(encoding="utf-8"))
    sample_rate = int(recipes.get("sampleRate", 24000))
    if not 8000 <= sample_rate <= 48000:
        sys.exit("sampleRate must be between 8000 and 48000")
    assets = recipes.get("assets", [])
    if not isinstance(assets, list):
        sys.exit("sfx-recipes.json assets must be a list")

    catalog = story.setdefault("sfxCatalog", {})
    rendered = []
    seen_ids: set[str] = set()
    try:
        for recipe in assets:
            asset_id = str(recipe.get("id", "")).strip()
            relative = str(recipe.get("file", f"sfx/{asset_id}.wav")).replace("\\", "/")
            if not asset_id or asset_id in seen_ids:
                raise ValueError(f"missing or duplicate asset id: {asset_id!r}")
            seen_ids.add(asset_id)
            if not relative.lower().endswith(".wav"):
                raise ValueError(f"local generated sound must be WAV: {relative}")
            destination = safe_public_path(public, relative)
            samples = render_recipe(recipe, sample_rate)
            write_wav(destination, samples, sample_rate)
            catalog[asset_id] = {
                "src": relative,
                "license": "本地生成",
                "source": f"可复现配方 public/story/sfx-recipes.json#{asset_id}",
            }
            rendered.append({"id": asset_id, "file": relative, "samples": len(samples)})
    except (TypeError, ValueError) as exc:
        sys.exit(str(exc))

    atomic_story(story_path, story)
    mark_stage(project, "sfx_ready", {"generatedAssets": len(rendered)})
    print(json.dumps({"sampleRate": sample_rate, "rendered": rendered}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
