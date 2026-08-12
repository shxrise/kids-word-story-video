# Project guide

This is one generated 1280x720, 20fps kids word story video project.

- Story contract: `public/story/story.json`
- Pipeline state: `build/state.json`
- Runtime paths: `build/toolchain.json`
- Resume by reading pipeline status; never infer completion from chat history.
- Do not hand-edit generated timing fields or overwrite an existing project directory.
- Keep images native 16:9, preserve provenance, and require recorded semantic review.
- Target-word silence is configurable and defaults to 0 seconds; keep the insertion path for positive values.
- Use the default 36px semi-transparent target-word label unless the user requests another size.
- Run validation before render; treat subjective audio review separately from technical validation.
