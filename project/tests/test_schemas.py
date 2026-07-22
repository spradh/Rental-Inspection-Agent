"""Unit tests for the core data contract (AnalystAnswer)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from project.schemas import AnalystAnswer


def test_defaults_are_sane():
    a = AnalystAnswer(answer="hello")
    assert a.answer == "hello"
    assert a.evidence == [] and a.recommendations == [] and a.sql_used == [] and a.citations == []
    assert a.confidence == 0.5


def test_confidence_is_bounded():
    with pytest.raises(ValidationError):
        AnalystAnswer(answer="x", confidence=1.5)
    with pytest.raises(ValidationError):
        AnalystAnswer(answer="x", confidence=-0.1)


def test_json_round_trip():
    a = AnalystAnswer(answer="net revenue was $1", evidence=["e"], confidence=0.8)
    restored = AnalystAnswer.model_validate_json(a.model_dump_json())
    assert restored == a


def test_chart_spec_defaults_and_invalid_type():
    from project.schemas import ChartSeries, ChartSpec

    c = ChartSpec(x=["a", "b"], series=[ChartSeries(name="s", values=[1.0, 2.0])])
    assert c.type == "bar"  # default
    with pytest.raises(ValidationError):
        ChartSpec(type="pie")  # only bar/line/area allowed


def test_analyst_answer_chart_default_none_and_round_trip():
    from project.schemas import ChartSeries, ChartSpec

    assert AnalystAnswer(answer="x").chart is None  # optional, off by default
    a = AnalystAnswer(answer="x", chart=ChartSpec(x=["a"], series=[ChartSeries(name="s", values=[1.0])]))
    restored = AnalystAnswer.model_validate_json(a.model_dump_json())
    assert restored.chart.series[0].values == [1.0]
