"""Tools for the Pre-Inspect pipeline: video.probe and perception.analyze_video.

The pipeline (agents.pipeline) is a fixed 3-step sequence, not an open-ended
tool-calling loop, so there's no dynamic registry/dispatch layer here — callers import
each tool module directly.
"""
