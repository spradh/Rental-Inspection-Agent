"""Pre-Inspect — Property Manager upload UI (Streamlit).

The Property Manager's front door: upload a narrated walkthrough video of a vacant unit,
pick move-in or move-out, and get back a room-by-room condition report. Calls
`project.agents.run_inspection` directly (in-process) — the same pipeline the FastAPI
service in `project/api/main.py` wraps for HTTP clients.

Non-negotiables reflected in this UI (see BRD.md / README.md): reports document condition,
never a Good/Bad verdict or a dollar figure; the uploaded video is deleted right after the
report is generated, never persisted.

Run from the repo root:
    streamlit run project/streamlit/app.py
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

# Make `project` importable when Streamlit runs this file directly.
# project/streamlit/app.py -> project/streamlit -> project -> repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from project.agents import InspectionReport, run_inspection
from project.config import COMPILE_MODEL, MAX_VIDEO_S, PERCEPTION_MODEL
from project.tools.video import VideoValidationError

st.set_page_config(page_title="Pre-Inspect", layout="wide")
st.title("Pre-Inspect")
st.caption("Upload a narrated walkthrough of a vacant unit to generate a condition report.")

_SESSION_LABELS = {"move_in": "Move-in", "move_out": "Move-out"}
_SOURCE_BADGE = {
    "narration": ("🗣️ Narrated", "#3b82f6"),
    "visual": ("👁️ Visual only", "#f59e0b"),
    "both": ("🗣️👁️ Narrated + visual", "#22c55e"),
}
_CATEGORY_LABELS = {
    "walls_paint": "Walls / paint",
    "floors": "Floors",
    "cleanliness": "Cleanliness",
    "appliances": "Appliances",
    "fixtures_hardware": "Fixtures / hardware",
    "windows_screens": "Windows / screens",
    "general_condition": "General condition",
}


# ── Session state ────────────────────────────────────────────────────
def _ensure_session_state() -> None:
    st.session_state.setdefault("report", None)
    st.session_state.setdefault("report_error", None)
    st.session_state.setdefault("flag_decisions", {})  # "{room}::{idx}" -> "confirmed"/"dismissed"


# ── Sidebar ──────────────────────────────────────────────────────────
def _render_sidebar() -> str:
    import shutil

    with st.sidebar:
        st.header("New walkthrough")
        session_type = st.radio(
            "Session type",
            options=["move_in", "move_out"],
            format_func=lambda k: _SESSION_LABELS[k],
        )
        st.caption(f"Max video length: {MAX_VIDEO_S // 60} min")
        st.divider()
        st.subheader("Pipeline")
        st.caption(f"Perception · {PERCEPTION_MODEL}")
        st.caption(f"Compile · {COMPILE_MODEL}")
        ffprobe_ok = shutil.which("ffprobe") is not None
        st.markdown(("🟢" if ffprobe_ok else "🔴") + " **ffprobe** " + ("on PATH" if ffprobe_ok else "missing"))
    return session_type


# ── Report rendering ──────────────────────────────────────────────────
def _render_flagged(report: InspectionReport) -> None:
    flagged = report.flagged_for_review()
    st.markdown("#### Flagged for review")
    st.caption("Visible in the video but not called out in narration — confirm or dismiss each one.")
    if not flagged:
        st.success("Nothing flagged — everything visible was also narrated.")
        return

    for i, f in enumerate(flagged):
        key = f"{f.room}::{i}"
        decision = st.session_state.flag_decisions.get(key)
        with st.container(border=True):
            cols = st.columns([5, 1, 1])
            with cols[0]:
                st.markdown(f"**{f.room}** · {_CATEGORY_LABELS.get(f.category, f.category)}")
                st.write(f.description)
                st.caption(
                    f"{f.timestamp.start_s:.0f}s–{f.timestamp.end_s:.0f}s · "
                    f"confidence {f.confidence:.0%}"
                )
            with cols[1]:
                if st.button("Confirm", key=f"confirm_{key}", disabled=decision == "confirmed"):
                    st.session_state.flag_decisions[key] = "confirmed"
                    st.rerun()
            with cols[2]:
                if st.button("Dismiss", key=f"dismiss_{key}", disabled=decision == "dismissed"):
                    st.session_state.flag_decisions[key] = "dismissed"
                    st.rerun()
            if decision:
                st.caption(f"→ {decision}")


def _render_rooms(report: InspectionReport) -> None:
    st.markdown("#### Room-by-room")
    if not report.rooms:
        st.info("No rooms were identified in this walkthrough.")
        return
    for room in report.rooms:
        with st.expander(f"{room.room} ({len(room.findings)} finding{'s' if len(room.findings) != 1 else ''})", expanded=True):
            if not room.findings:
                st.caption("No findings recorded for this room.")
                continue
            for f in room.findings:
                label, color = _SOURCE_BADGE.get(f.source, (f.source, "#7f8c8d"))
                st.markdown(
                    f"<span style='background:{color};color:white;padding:2px 8px;"
                    f"border-radius:6px;font-size:0.75rem;font-weight:600;'>{label}</span> "
                    f"&nbsp; **{_CATEGORY_LABELS.get(f.category, f.category)}**",
                    unsafe_allow_html=True,
                )
                st.write(f.description)
                st.caption(
                    f"{f.timestamp.start_s:.0f}s–{f.timestamp.end_s:.0f}s · "
                    f"confidence {f.confidence:.0%}"
                )
                st.divider()


def _render_report(report: InspectionReport) -> None:
    st.success("Report generated. The uploaded video has been discarded.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Session", _SESSION_LABELS.get(report.session_type, report.session_type))
    c2.metric("Video length", f"{report.video_duration_s:.0f}s")
    c3.metric("Rooms", len(report.rooms))

    st.markdown("#### Summary")
    st.write(report.summary or "_(no summary)_")

    st.divider()
    _render_flagged(report)
    st.divider()
    _render_rooms(report)

    st.divider()
    st.download_button(
        "Download report (JSON)",
        data=report.model_dump_json(indent=2),
        file_name=f"pre-inspect-{report.session_type}-{uuid.uuid4().hex[:8]}.json",
        mime="application/json",
    )


# ── Upload flow ────────────────────────────────────────────────────────
def _render_upload(session_type: str) -> None:
    st.markdown("#### Upload walkthrough video")
    uploaded = st.file_uploader(
        "Narrated video of the vacant unit (video must include audio narration)",
        type=["mp4", "mov", "m4v", "webm"],
    )
    generate = st.button("Generate report", type="primary", disabled=uploaded is None)

    if generate and uploaded is not None:
        suffix = Path(uploaded.name).suffix or ".mp4"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(uploaded.getbuffer())
                tmp_path = tmp.name

            with st.spinner("Transcribing narration and analyzing the video…"):
                report = run_inspection(tmp_path, session_type=session_type)

            st.session_state.report = report
            st.session_state.report_error = None
            st.session_state.flag_decisions = {}
        except VideoValidationError as exc:
            st.session_state.report = None
            st.session_state.report_error = str(exc)
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the UI
            st.session_state.report = None
            st.session_state.report_error = f"The pipeline failed: {exc}"
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
        st.rerun()

    if st.session_state.report_error:
        st.error(st.session_state.report_error)


# ── Main ───────────────────────────────────────────────────────────────
def main() -> None:
    _ensure_session_state()
    session_type = _render_sidebar()
    _render_upload(session_type)

    if st.session_state.report is not None:
        st.divider()
        _render_report(st.session_state.report)


main()
