"""
Tests for pure helper functions embedded in src/dashboard.py.
No Streamlit runtime needed — warnings about ScriptRunContext are expected and harmless.
"""
import pytest
import warnings

# Suppress Streamlit "missing ScriptRunContext" warnings from the import
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from src.dashboard import (
        _brier_score,
        _accuracy,
        _compute_calibration,
    )


# ─── _brier_score ─────────────────────────────────────────────────────────────

class TestBrierScore:
    def test_perfect_predictions(self):
        data = [
            {"model_prob": 1.0, "resolved_yes": True},
            {"model_prob": 0.0, "resolved_yes": False},
        ]
        assert _brier_score(data) == pytest.approx(0.0)

    def test_worst_predictions(self):
        data = [
            {"model_prob": 0.0, "resolved_yes": True},
            {"model_prob": 1.0, "resolved_yes": False},
        ]
        assert _brier_score(data) == pytest.approx(1.0)

    def test_random_baseline(self):
        # All 50% predictions → Brier = 0.25
        data = [
            {"model_prob": 0.5, "resolved_yes": True},
            {"model_prob": 0.5, "resolved_yes": False},
        ]
        assert _brier_score(data) == pytest.approx(0.25)

    def test_skips_unresolved(self):
        data = [
            {"model_prob": 0.8, "resolved_yes": True},
            {"model_prob": 0.7, "resolved_yes": None},   # unresolved — skipped
        ]
        # Only the first row counts: (0.8 - 1)^2 = 0.04
        assert _brier_score(data) == pytest.approx(0.04)

    def test_empty_list(self):
        assert _brier_score([]) == 0.0

    def test_all_unresolved(self):
        data = [{"model_prob": 0.7, "resolved_yes": None}]
        assert _brier_score(data) == 0.0

    def test_mixed_correctness(self):
        data = [
            {"model_prob": 0.9, "resolved_yes": True},   # (0.9-1)^2 = 0.01
            {"model_prob": 0.1, "resolved_yes": False},  # (0.1-0)^2 = 0.01
        ]
        assert _brier_score(data) == pytest.approx(0.01)


# ─── _accuracy ────────────────────────────────────────────────────────────────

class TestAccuracy:
    def test_all_correct(self):
        data = [
            {"model_prob": 0.8, "resolved_yes": True},
            {"model_prob": 0.3, "resolved_yes": False},
        ]
        assert _accuracy(data) == pytest.approx(1.0)

    def test_all_wrong(self):
        data = [
            {"model_prob": 0.2, "resolved_yes": True},   # predicts NO, was YES
            {"model_prob": 0.8, "resolved_yes": False},  # predicts YES, was NO
        ]
        assert _accuracy(data) == pytest.approx(0.0)

    def test_boundary_at_0_5(self):
        # p=0.5 → predicted YES (>= 0.5 is YES)
        data = [{"model_prob": 0.5, "resolved_yes": True}]
        assert _accuracy(data) == pytest.approx(1.0)

    def test_skips_unresolved(self):
        data = [
            {"model_prob": 0.9, "resolved_yes": True},
            {"model_prob": 0.6, "resolved_yes": None},  # skipped
        ]
        assert _accuracy(data) == pytest.approx(1.0)

    def test_empty_list(self):
        assert _accuracy([]) == 0.0

    def test_half_correct(self):
        data = [
            {"model_prob": 0.8, "resolved_yes": True},   # correct
            {"model_prob": 0.8, "resolved_yes": False},  # wrong
        ]
        assert _accuracy(data) == pytest.approx(0.5)


# ─── _compute_calibration ─────────────────────────────────────────────────────

class TestComputeCalibration:
    def test_returns_three_lists(self):
        data = [{"model_prob": 0.7, "resolved_yes": True}]
        mids, rates, counts = _compute_calibration(data)
        assert len(mids) == len(rates) == len(counts)

    def test_perfect_calibration_at_bucket(self):
        # All predictions ~0.75 (bucket 7), all resolved YES → rate should be 100%
        data = [
            {"model_prob": 0.72, "resolved_yes": True},
            {"model_prob": 0.78, "resolved_yes": True},
        ]
        mids, rates, counts = _compute_calibration(data)
        assert len(mids) == 1
        assert mids[0] == 75  # bucket 7 → mid = 75
        assert rates[0] == pytest.approx(100.0)
        assert counts[0] == 2

    def test_zero_rate_when_all_false(self):
        data = [{"model_prob": 0.65, "resolved_yes": False}]
        mids, rates, counts = _compute_calibration(data)
        assert rates[0] == pytest.approx(0.0)

    def test_multiple_buckets(self):
        data = [
            {"model_prob": 0.15, "resolved_yes": True},   # bucket 1 → mid 15
            {"model_prob": 0.85, "resolved_yes": False},  # bucket 8 → mid 85
        ]
        mids, rates, counts = _compute_calibration(data)
        assert len(mids) == 2
        assert set(mids) == {15, 85}

    def test_skips_unresolved(self):
        data = [
            {"model_prob": 0.55, "resolved_yes": True},
            {"model_prob": 0.55, "resolved_yes": None},   # skipped
        ]
        mids, rates, counts = _compute_calibration(data)
        assert counts[0] == 1  # only 1 resolved

    def test_empty_returns_empty_lists(self):
        mids, rates, counts = _compute_calibration([])
        assert mids == []
        assert rates == []
        assert counts == []

    def test_bucket_100_goes_to_last_bucket(self):
        # p=1.0 → min(int(1.0*10), 9) = 9 → bucket 9 → mid 95
        data = [{"model_prob": 1.0, "resolved_yes": True}]
        mids, rates, counts = _compute_calibration(data)
        assert mids[0] == 95
