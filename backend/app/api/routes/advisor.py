"""POST /api/v1/advisor/evaluate -- the synchronous endpoint the ITSM calls
when a disk add/extend ticket is created. Orchestrates: host lookup/creation,
latest disk metrics + growth trend from disk_metrics, SSH/Ansible audit
(cached), scoring, and persistence of the request + decision.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import DecisionOut, EvaluateRequest
from app.core.config import Settings, get_settings
from app.db.models import Decision, Host, Request
from app.db.session import get_db
from app.services import ssh_audit
from app.services.metrics_query import get_growth_bytes_per_day, get_latest_metric
from app.services.scoring import ScoringInput, ScoringThresholds, ScoringWeights, evaluate

router = APIRouter(prefix="/advisor", tags=["advisor"])


def _get_or_create_host(db: Session, hostname: str) -> Host:
    host = db.execute(select(Host).where(Host.hostname == hostname)).scalar_one_or_none()
    if host is None:
        host = Host(hostname=hostname)
        db.add(host)
        db.commit()
        db.refresh(host)
    return host


@router.post("/evaluate", response_model=DecisionOut)
def evaluate_request(
    payload: EvaluateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DecisionOut:
    host = _get_or_create_host(db, payload.hostname)

    req = Request(
        ticket_id=payload.ticket_id,
        hostname=payload.hostname,
        mount_point=payload.mount_point,
        requested_gb=payload.requested_gb,
        requester=payload.requester,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    latest_metric = get_latest_metric(db, host.id, payload.mount_point)
    growth_bytes_per_day = get_growth_bytes_per_day(
        db, host.id, payload.mount_point, settings.growth_lookback_days
    )

    audit = ssh_audit.run_audit(db, host, payload.mount_point, settings)

    weights = ScoringWeights(
        usage_pct=settings.weight_usage_pct,
        growth_trend=settings.weight_growth_trend,
        headroom_days=settings.weight_headroom_days,
        reclaimable=settings.weight_reclaimable,
    )
    thresholds = ScoringThresholds(
        approve=settings.threshold_approve,
        approve_reduced=settings.threshold_approve_reduced,
        manual_review=settings.threshold_manual_review,
    )

    scoring_input = ScoringInput(
        capacity_bytes=latest_metric.capacity_bytes if latest_metric else 0,
        used_bytes=latest_metric.used_bytes if latest_metric else 0,
        requested_gb=payload.requested_gb,
        growth_bytes_per_day=growth_bytes_per_day,
        reclaimable_bytes=audit.reclaimable_bytes if audit else 0,
        has_logrotate=audit.has_logrotate if audit else False,
        audit_available=audit is not None,
        weights=weights,
        thresholds=thresholds,
    )

    if latest_metric is None:
        # No Dynatrace metrics collected yet for this host/mount: usage/growth
        # cannot be scored reliably either, so force MANUAL_REVIEW just like
        # a failed SSH audit -- never fall through to a silent APPROVE.
        scoring_input.audit_available = False

    result = evaluate(scoring_input)
    if latest_metric is None:
        result.reasoning.setdefault(
            "metrics",
            "Bu host/mount için henüz Dynatrace metrik verisi toplanmadı.",
        )

    decision = Decision(
        request_id=req.id,
        score=result.score,
        decision=result.decision,
        recommended_gb=result.recommended_gb,
        reasoning_json=result.reasoning,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    return DecisionOut(
        request_id=req.id,
        decision=decision.decision,
        score=decision.score,
        recommended_gb=decision.recommended_gb,
        reasoning=decision.reasoning_json,
    )
