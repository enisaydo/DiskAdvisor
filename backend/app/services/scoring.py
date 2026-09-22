"""Pure scoring engine: turns disk metrics + SSH audit findings into a 0-100
score and a threshold-based decision. No DB/network access here so it stays
trivially unit-testable.

IMPORTANT invariant: if the SSH audit could not be performed (audit_available
is False), the decision MUST be MANUAL_REVIEW regardless of score. We never
silently APPROVE without an audit.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime

GB = 1024 ** 3

APPROVE = "APPROVE"
APPROVE_REDUCED = "APPROVE_REDUCED"
MANUAL_REVIEW = "MANUAL_REVIEW"
REJECT = "REJECT"


@dataclass
class ScoringWeights:
    usage_pct: float = 0.35
    growth_trend: float = 0.25
    headroom_days: float = 0.20
    reclaimable: float = 0.20


@dataclass
class ScoringThresholds:
    approve: float = 75.0
    approve_reduced: float = 55.0
    manual_review: float = 30.0


@dataclass
class ScoringInput:
    capacity_bytes: int
    used_bytes: int
    requested_gb: float
    growth_bytes_per_day: float = 0.0
    reclaimable_bytes: int = 0
    has_logrotate: bool = True
    audit_available: bool = True
    weights: ScoringWeights = field(default_factory=ScoringWeights)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)


@dataclass
class ScoringResult:
    score: float | None
    decision: str
    recommended_gb: float | None
    reasoning: dict


def linear_growth_bytes_per_day(points: list[tuple[datetime, int]]) -> float:
    """Least-squares slope (bytes/day) of used_bytes over time.

    `points` is a list of (timestamp, used_bytes) tuples, any order, any
    number of points. Returns 0.0 if there are fewer than 2 points or all
    timestamps coincide.
    """
    if len(points) < 2:
        return 0.0

    ordered = sorted(points, key=lambda p: p[0])
    t0 = ordered[0][0]
    xs = [(t - t0).total_seconds() / 86400.0 for t, _ in ordered]  # days
    ys = [float(v) for _, v in ordered]

    if len(set(xs)) < 2:
        return 0.0

    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def _score_usage_pct(used_pct: float) -> float:
    """0-100: higher current usage -> stronger justification for growth."""
    return max(0.0, min(100.0, used_pct))


def _score_growth_trend(growth_bytes_per_day: float, capacity_bytes: int) -> float:
    """0-100: faster growth relative to capacity -> stronger justification."""
    if capacity_bytes <= 0:
        return 0.0
    daily_pct = (growth_bytes_per_day / capacity_bytes) * 100.0
    # 1%/day sustained growth is already very fast; cap scaling at that.
    return max(0.0, min(100.0, (daily_pct / 1.0) * 100.0))


def _score_headroom_days(headroom_days: float | None) -> float:
    """0-100: fewer days until full -> stronger justification for growth."""
    if headroom_days is None:
        # Not growing / shrinking: no urgency from headroom.
        return 0.0
    if headroom_days <= 7:
        return 100.0
    if headroom_days >= 90:
        return 0.0
    # Linear interpolation between 7 (100) and 90 (0) days.
    return 100.0 * (90 - headroom_days) / (90 - 7)


def _score_reclaimable(reclaimable_bytes: int, requested_bytes: float, has_logrotate: bool) -> float:
    """0-100: the MORE reclaimable space covers the request, the LOWER the
    justification score (cleanup should be done instead of growing disk).
    Missing logrotate config further reduces the score (fixable via config).
    """
    if requested_bytes <= 0:
        coverage = 0.0
    else:
        coverage = min(1.0, reclaimable_bytes / requested_bytes)
    score = 100.0 * (1.0 - coverage)
    if not has_logrotate:
        # Missing logrotate is an easy structural fix; penalize further.
        score = max(0.0, score - 20.0)
    return max(0.0, min(100.0, score))


def compute_headroom_days(capacity_bytes: int, used_bytes: int, growth_bytes_per_day: float) -> float | None:
    """Days until the mount is full at the current growth rate.

    Returns None if the disk is not growing (rate <= 0).
    """
    if growth_bytes_per_day <= 0:
        return None
    free_bytes = max(0, capacity_bytes - used_bytes)
    return free_bytes / growth_bytes_per_day


def evaluate(inp: ScoringInput) -> ScoringResult:
    reasoning: dict = {}

    if not inp.audit_available:
        reasoning["audit"] = (
            "SSH/Ansible audit sunucuya erişemedi veya zaman aşımına uğradı; "
            "skor hesaplanmadı, karar güvenlik gereği MANUAL_REVIEW olarak işaretlendi."
        )
        return ScoringResult(
            score=None,
            decision=MANUAL_REVIEW,
            recommended_gb=None,
            reasoning=reasoning,
        )

    used_pct = (inp.used_bytes / inp.capacity_bytes * 100.0) if inp.capacity_bytes else 0.0
    headroom_days = compute_headroom_days(inp.capacity_bytes, inp.used_bytes, inp.growth_bytes_per_day)
    requested_bytes = inp.requested_gb * GB

    s_usage = _score_usage_pct(used_pct)
    s_growth = _score_growth_trend(inp.growth_bytes_per_day, inp.capacity_bytes)
    s_headroom = _score_headroom_days(headroom_days)
    s_reclaim = _score_reclaimable(inp.reclaimable_bytes, requested_bytes, inp.has_logrotate)

    w = inp.weights
    weight_sum = w.usage_pct + w.growth_trend + w.headroom_days + w.reclaimable
    if weight_sum <= 0:
        weight_sum = 1.0

    score = (
        s_usage * w.usage_pct
        + s_growth * w.growth_trend
        + s_headroom * w.headroom_days
        + s_reclaim * w.reclaimable
    ) / weight_sum
    score = round(max(0.0, min(100.0, score)), 2)

    reasoning.update(
        {
            "used_pct": round(used_pct, 2),
            "growth_bytes_per_day": round(inp.growth_bytes_per_day, 2),
            "headroom_days": round(headroom_days, 1) if headroom_days is not None else None,
            "reclaimable_gb": round(inp.reclaimable_bytes / GB, 2),
            "has_logrotate": inp.has_logrotate,
            "subscores": {
                "usage_pct": round(s_usage, 2),
                "growth_trend": round(s_growth, 2),
                "headroom_days": round(s_headroom, 2),
                "reclaimable": round(s_reclaim, 2),
            },
        }
    )

    t = inp.thresholds
    reclaimable_gb = inp.reclaimable_bytes / GB
    recommended_gb: float | None

    if score >= t.approve:
        decision = APPROVE
        recommended_gb = inp.requested_gb
        reasoning["action"] = "Talep gerekçelendirilmiş bulundu, olduğu gibi onaylandı."
    elif score >= t.approve_reduced:
        decision = APPROVE_REDUCED
        recommended_gb = max(1.0, round(inp.requested_gb - reclaimable_gb, 1))
        reasoning["action"] = (
            f"Talep kısmen gerekçelendirilmiş: yaklaşık {round(reclaimable_gb, 1)} GB "
            f"log temizliği/logrotate ile geri kazanılabilir, bu nedenle {recommended_gb} GB önerildi."
        )
    elif score >= t.manual_review:
        decision = MANUAL_REVIEW
        recommended_gb = None
        reasoning["action"] = "Sinyaller belirsiz, manuel inceleme gerekiyor."
    else:
        decision = REJECT
        recommended_gb = None
        actions = []
        if not inp.has_logrotate:
            actions.append(f"{inp.reclaimable_bytes // GB} GB kazanmak için ilgili dizine logrotate ekleyin")
        elif reclaimable_gb > 0:
            actions.append(f"Yaklaşık {round(reclaimable_gb, 1)} GB rotate edilmemiş/eski log ve önbellek temizlenebilir")
        if not actions:
            actions.append("Mevcut kullanım ve büyüme trendi ek disk gerektirmiyor")
        decision_text = "; ".join(actions)
        reasoning["action"] = f"Talep reddedildi: {decision_text}."

    return ScoringResult(score=score, decision=decision, recommended_gb=recommended_gb, reasoning=reasoning)
