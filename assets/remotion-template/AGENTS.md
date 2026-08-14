# Project guide

This is one generated 1280x720, 20fps kids word story video project.

- Story contract: `public/story/story.json`
- Pipeline state: `build/state.json`
- Runtime paths: `build/toolchain.json`
- Resume by reading pipeline status; never infer completion from chat history.
- Do not hand-edit generated timing fields or overwrite an existing project directory.
- Keep images native 16:9, preserve provenance, and require recorded semantic review.
- Target-word audio silence is configurable and defaults to 0 seconds; only positive values use the insertion path.
- Target-word visual duration is independent and defaults to 1.2 seconds. Keep the recorded TTS pronunciation duration unchanged.
- The narrated Chinese title has an independent 0.6-second visual tail before the body.
- Run actual-TTS duration preflight before bulk illustration; the default acceptable range is 285–375 seconds around a 330-second target.
- Use the default 36px semi-transparent target-word label with one gentle breathing emphasis.
- Run validation before render; treat subjective audio review separately from technical validation.
- Describe plot- or continuity-critical actions with the structured critical-action contract; keep ordinary backgrounds flexible.
- Plan at most three independent illustration scenes per parallel batch and serialize recorded dependencies or retries.
- Final rendering can take several minutes. Use at least a 20-minute limit (higher for segmented renders), wait for the real process result, and treat a caller-side yield as a running state rather than failure.
