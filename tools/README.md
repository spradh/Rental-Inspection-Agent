# tools/

This package holds the deterministic and perception utilities used directly by `agents/pipeline.py`. There is intentionally no dynamic tool-registry or dispatch layer here — `agents.pipeline` runs a fixed, linear sequence of steps rather than an open-ended tool-calling loop, so callers just `import tools.video` and `import tools.perception` directly and call their functions.

## Files

### `__init__.py`
Docstring-only module. Documents the "no registry" design decision above — there's nothing to export.

### `video.py`
Local, deterministic validation of an uploaded walkthrough video, used as a cheap guardrail before the expensive perception call in `tools/perception.py`. Makes no LLM or network calls.

```python
class VideoMeta(BaseModel):
    path: str
    duration_s: float
    has_audio: bool

class VideoValidationError(ValueError):
    ...

def probe(path: str | Path) -> VideoMeta: ...
```

`probe()`:
1. Confirms the file exists (`Path.is_file()`), else raises `VideoValidationError`.
2. Shells out to `ffprobe -v error -print_format json -show_format -show_streams <path>` to read format/stream metadata. Raises `VideoValidationError` if `ffprobe` isn't installed or the subprocess call fails — **`ffprobe` (part of ffmpeg) must be on `PATH`.**
3. Extracts `duration_s` from `format.duration` and `has_audio` from whether any stream has `codec_type == "audio"`.
4. Validates: duration must be `> 0`, duration must be `<= MAX_VIDEO_S` (from `config.py`, default 300s — the PRD's hard cap), and an audio track must exist (narration is required). Raises `VideoValidationError` with a descriptive message for whichever check fails.
5. Returns a populated `VideoMeta` on success.

CLI: `python -m project.tools.video <path>` prints `probe(path)` as JSON.

### `perception.py`
Sends the whole walkthrough video (with audio) in a single request to a video-native multimodal LLM (Gemini 2.5 Flash via OpenRouter, by default) and gets back two purely descriptive, timestamped streams. Does **no** categorization, room-tagging, or condition judgment — that reasoning step happens later, in `agents/compile.py`.

```python
def analyze_video(
    video_path: str | Path,
) -> tuple[list[TranscriptSegment], list[VisualObservation]]: ...
```

What it does:
1. Reads `OPENROUTER_API_KEY` from the environment; raises `RuntimeError` if unset.
2. Parses `config.PERCEPTION_MODEL` (format `"<provider>:<model>"`); raises `RuntimeError` if the provider isn't `"openrouter"` — unlike `agents/compile.py`, this module only talks to OpenRouter directly, not through `shared.llm.chat`.
3. Builds a chat-completions request: a system prompt (instructing verbatim transcript segmentation plus independent visual description, and forbidding condition judgments/dollar estimates) plus a user message containing a text part and a `video_url` content part — the video encoded as a base64 `data:video/...;base64,...` URI via `_video_data_uri`.
4. POSTs directly to `https://openrouter.ai/api/v1/chat/completions` (180s timeout), requesting `response_format: {"type": "json_object"}`.
5. Validates the response against an internal `_PerceptionPayload` model (`transcript: list[TranscriptSegment]`, `visual: list[VisualObservation]`). Raises `RuntimeError` wrapping either an HTTP failure or a schema-validation failure.
6. Returns `(payload.transcript, payload.visual)` on success.

Internal helpers: `_video_data_uri` (base64-encodes the video file into a data URI) and `_strip_fences` (same code-fence-stripping pattern as `agents/compile.py`).

CLI: `python -m project.tools.perception <video_path>` prints segment/observation counts.

**Documented caveat:** the exact multimodal request shape for a combined video+audio content part is a documented assumption in the module, not yet verified against a live OpenRouter call — flagged in the code as needing a smoke test.

## Shared data contracts

Both modules produce/consume pydantic models defined once in the root `schemas.py` (`TranscriptSegment`, `VisualObservation`) plus `VideoMeta` defined locally in `video.py`. See `schemas.py` for full field-level documentation rather than duplicating it here.
