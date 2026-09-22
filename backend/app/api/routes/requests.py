from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import DecisionOut, OverrideOut, OverrideRequest, RequestOut
from app.db.models import Decision, Override, Request
from app.db.session import get_db
from app.services.scoring import APPROVE, APPROVE_REDUCED, MANUAL_REVIEW, REJECT

router = APIRouter(prefix="/requests", tags=["requests"])

VALID_DECISIONS = {APPROVE, APPROVE_REDUCED, MANUAL_REVIEW, REJECT}


def _to_request_out(req: Request) -> RequestOut:
    latest = max(req.decisions, key=lambda d: d.created_at) if req.decisions else None
    return RequestOut(
        id=req.id,
        ticket_id=req.ticket_id,
        hostname=req.hostname,
        mount_point=req.mount_point,
        requested_gb=req.requested_gb,
        requester=req.requester,
        created_at=req.created_at,
        latest_decision=(
            DecisionOut(
                request_id=latest.request_id,
                decision=latest.decision,
                score=latest.score,
                recommended_gb=latest.recommended_gb,
                reasoning=latest.reasoning_json,
            )
            if latest
            else None
        ),
    )


@router.get("", response_model=list[RequestOut])
def list_requests(db: Session = Depends(get_db)):
    stmt = select(Request).options(selectinload(Request.decisions)).order_by(Request.created_at.desc())
    requests = db.execute(stmt).scalars().all()
    return [_to_request_out(r) for r in requests]


@router.get("/{request_id}", response_model=RequestOut)
def get_request(request_id: int, db: Session = Depends(get_db)):
    stmt = select(Request).options(selectinload(Request.decisions)).where(Request.id == request_id)
    req = db.execute(stmt).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Talep bulunamadı")
    return _to_request_out(req)


@router.post("/{request_id}/override", response_model=OverrideOut)
def override_decision(request_id: int, payload: OverrideRequest, db: Session = Depends(get_db)):
    if payload.new_decision not in VALID_DECISIONS:
        raise HTTPException(status_code=400, detail=f"Geçersiz karar: {payload.new_decision}")

    stmt = select(Decision).where(Decision.request_id == request_id).order_by(Decision.created_at.desc())
    decision = db.execute(stmt).scalars().first()
    if decision is None:
        raise HTTPException(status_code=404, detail="Bu talep için karar bulunamadı")

    override = Override(
        decision_id=decision.id,
        new_decision=payload.new_decision,
        reason=payload.reason,
        user=payload.user,
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    return override
