import pytest
from evaluation.metrics.wilson_ci import wilson_score_interval, format_proportion_ci


def test_wilson_zero_events():
    low, high = wilson_score_interval(0, 20)
    assert low == 0.0
    assert 0.0 < high < 0.20


def test_wilson_all_events():
    low, high = wilson_score_interval(20, 20)
    assert 0.80 < low < 1.0
    assert high == 1.0


def test_wilson_half_events():
    low, high = wilson_score_interval(50, 100)
    assert 0.40 < low < 0.50
    assert 0.50 < high < 0.60


def test_wilson_empty_denominator():
    low, high = wilson_score_interval(0, 0)
    assert low == 0.0
    assert high == 0.0


def test_format_proportion_ci():
    res = format_proportion_ci(5, 10)
    assert "5/10 (50.0%)" in res
    assert "95% CI:" in res
