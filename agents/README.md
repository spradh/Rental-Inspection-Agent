# agents/

This package is the orchestration/reasoning "brain" of Pre-Inspect. It runs a fixed, 3-step linear pipeline (no routing graph, no open-ended tool loop) that turns a PM-narrated walkthrough video into a structured `InspectionReport`.

## Data flow

```
agents.pipeline.run_inspection(video_path, session_type)
  |
  |-- 1. tools.video.probe(video_path)
  |        local ffprobe guardrail -> VideoMeta
  |        raises VideoValidationError (fatal) if the file is missing,
  |        unreadable, silent, or too long
  |
  |-- 2. tools.perception.analyze_video(video_path)
  |        one fused multimodal LLM call -> (transcript, visual)
  |        a RuntimeError here is caught and treated as non-fatal;
  |        falls back to empty lists (sparse/no narration is expected,
  |        not an error)
  |
  `-- 3. agents.compile.compile_report(transcript, visual,
                                        session_type, video_duration_s)
           merges the two signal streams -> InspectionReport
```

## Files

### `__init__.py`
Public surface of the package. Re-exports:
- `run_inspection` (from `pipeline.py`)
- `InspectionReport` (from the root `schemas.py`)

Nothing else in this package should be imported directly by outside callers.

### `pipeline.py`
The orchestrator.

```python
run_inspection(video_path: str, *, session_type: SessionType) -> InspectionReport
```

Runs the three steps above in order and returns the final report. Only step 1's failure (`VideoValidationError`) is allowed to propagate out of `run_inspection`; step 2's failure is swallowed and degraded instead, since the product allows a PM to film with little or no narration.

Also has a CLI demo entrypoint:

```
python -m project.agents.pipeline <video_path> [move_in|move_out]
```

which prints the resulting report as pretty JSON.

### `compile.py`
The single reasoning/LLM step in the whole pipeline — and the *only* place where narrated-vs-visual judgment happens. A finding that's visible in the video but never called out by the PM becomes a review flag (via `InspectionReport.flagged_for_review()`), not a second LLM pass.

```python
compile_report(
    transcript: list[TranscriptSegment],
    visual: list[VisualObservation],
    *,
    session_type: SessionType,
    video_duration_s: float,
) -> InspectionReport
```

What it does:
1. Builds a system prompt from `InspectionReport.model_json_schema()`, telling the LLM how to categorize findings and set `source`/`narrated`/`confidence` — and explicitly forbidding condition judgments or dollar estimates.
2. Renders the transcript and visual observations into one interleaved, timestamp-sorted timeline string (`_render_timeline`) so the model sees both streams in chronological order.
3. Calls `shared.llm.chat(prompt, model=COMPILE_MODEL)` and validates the response with `InspectionReport.model_validate_json`.
4. If validation fails, makes exactly one repair attempt — re-prompts the LLM with its own bad output plus the validation error text, then re-validates.
5. If the repair also fails, degrades gracefully: returns an `InspectionReport` with empty `findings`/`rooms` and a summary explaining compilation failed, rather than raising.
6. Always overwrites `report.session_type` and `report.video_duration_s` with the caller-supplied ground truth (never trusts the LLM for these), and fills `generated_at` with the current UTC timestamp if the model didn't set one.

Internal helpers: `_render_timeline` (timeline formatting) and `_strip_fences` (strips ` ```json ` code fences if the model adds them despite instructions).

## External dependencies to know about

- `compile.py` imports `shared.llm.chat`, which is **not part of this repo** — it resolves to a sibling package (a course-provided multi-provider LLM client) that must be importable, e.g. via `PYTHONPATH` or by running from within the larger workspace this repo is nested under.
- Every module in this repo uses `project.*`-style imports (`from project.schemas import ...`), which means the repo root must itself be importable as a package named `project`.
- Model choice for `compile.py` is controlled by `config.COMPILE_MODEL` (env var `COMPILE_MODEL`, default `anthropic:claude-sonnet-4-6`).
