import datetime as dt

import pytest

from app.services.scoring import (
    APPROVE,
    APPROVE_REDUCED,
    GB,
    MANUAL_REVIEW,
    REJECT,
    ScoringInput,
    compute_headroom_days,
    evaluate,
    linear_growth_bytes_per_day,
)


def test_audit_unavailable_forces_manual_review():
    inp = ScoringInput(
        capacity_bytes=100 * GB,
        used_bytes=95 * GB,
        requested_gb=50,
        growth_bytes_per_day=5 * GB,
        reclaimable_bytes=0,
        has_logrotate=False,
        audit_available=False,
    )
    result = evaluate(inp)
    assert result.decision == MANUAL_REVIEW
    assert result.score is None
    assert result.recommended_gb is None
    assert "audit" in result.reasoning


def test_high_usage_fast_growth_no_reclaimable_approves():
    inp = ScoringInput(
        capacity_bytes=100 * GB,
        used_bytes=92 * GB,
        requested_gb=50,
        growth_bytes_per_day=2 * GB,  # 2%/day of capacity -> fast growth
        reclaimable_bytes=0,
        has_logrotate=True,
        audit_available=True,
    )
    result = evaluate(inp)
    assert result.decision == APPROVE
    assert result.score >= 75
    assert result.recommended_gb == 50


def test_high_reclaimable_space_rejects():
    inp = ScoringInput(
        capacity_bytes=100 * GB,
        used_bytes=40 * GB,
        requested_gb=20,
        growth_bytes_per_day=0,
        reclaimable_bytes=25 * GB,  # covers the whole request
        has_logrotate=False,
        audit_available=True,
    )
    result = evaluate(inp)
    assert result.decision == REJECT
    assert result.score < 30
    assert "logrotate" in result.reasoning["action"] or "temizlen" in result.reasoning["action"]


def test_partial_reclaimable_gives_approve_reduced():
    inp = ScoringInput(
        capacity_bytes=100 * GB,
        used_bytes=85 * GB,
        requested_gb=40,
        growth_bytes_per_day=1 * GB,
        reclaimable_bytes=15 * GB,
        has_logrotate=True,
        audit_available=True,
    )
    result = evaluate(inp)
    assert result.decision in (APPROVE_REDUCED, APPROVE, MANUAL_REVIEW)
    if result.decision == APPROVE_REDUCED:
        assert result.recommended_gb < inp.requested_gb


def test_ambiguous_signals_manual_review():
    inp = ScoringInput(
        capacity_bytes=100 * GB,
        used_bytes=50 * GB,
        requested_gb=20,
        growth_bytes_per_day=0.2 * GB,
        reclaimable_bytes=5 * GB,
        has_logrotate=True,
        audit_available=True,
    )
    result = evaluate(inp)
    assert result.decision in (MANUAL_REVIEW, REJECT, APPROVE_REDUCED)
    assert result.score is not None


def test_score_is_bounded_0_100():
    for used_pct_bytes, growth, reclaim in [
        (0, 0, 0),
        (100 * GB, 100 * GB, 100 * GB),
        (10 * GB, -5 * GB, 0),
    ]:
        inp = ScoringInput(
            capacity_bytes=100 * GB,
            used_bytes=used_pct_bytes,
            requested_gb=10,
            growth_bytes_per_day=growth,
            reclaimable_bytes=reclaim,
            has_logrotate=True,
            audit_available=True,
        )
        result = evaluate(inp)
        assert result.score is not None
        assert 0.0 <= result.score <= 100.0


def test_compute_headroom_days_no_growth_returns_none():
    assert compute_headroom_days(100 * GB, 50 * GB, 0) is None
    assert compute_headroom_days(100 * GB, 50 * GB, -1 * GB) is None


def test_compute_headroom_days_positive_growth():
    days = compute_headroom_days(100 * GB, 90 * GB, 1 * GB)
    assert days == pytest.approx(10.0)


def test_linear_growth_bytes_per_day_simple_trend():
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    points = [
        (base, 0),
        (base + dt.timedelta(days=1), 10 * GB),
        (base + dt.timedelta(days=2), 20 * GB),
        (base + dt.timedelta(days=3), 30 * GB),
    ]
    slope = linear_growth_bytes_per_day(points)
    assert slope == pytest.approx(10 * GB, rel=0.01)


def test_linear_growth_bytes_per_day_insufficient_points():
    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    assert linear_growth_bytes_per_day([]) == 0.0
    assert linear_growth_bytes_per_day([(base, 1)]) == 0.0


def test_reject_reasoning_mentions_recommended_action_without_logrotate():
    inp = ScoringInput(
        capacity_bytes=100 * GB,
        used_bytes=30 * GB,
        requested_gb=10,
        growth_bytes_per_day=0,
        reclaimable_bytes=8 * GB,
        has_logrotate=False,
        audit_available=True,
    )
    result = evaluate(inp)
    assert result.decision == REJECT
    assert "logrotate" in result.reasoning["action"]
