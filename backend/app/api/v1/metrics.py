from collections import defaultdict
from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from backend.app.db.session import get_session
from backend.app.db.models import Interaction
from backend.app.schemas.metrics import MetricsSummary
from backend.app.core.lead_scoring import HOT_THRESHOLD  # 👈 NUEVO

router = APIRouter(
    prefix="/metrics",
    tags=["metrics"],
)


@router.get("/summary", response_model=MetricsSummary)
def get_metrics_summary(
    session: Session = Depends(get_session),
) -> MetricsSummary:
    interactions: List[Interaction] = session.exec(
        select(Interaction)
    ).all()

    total = len(interactions)
    if total == 0:
        return MetricsSummary(
            total_interactions=0,
            total_sessions=0,
            avg_response_time_ms=None,
            pct_hot_leads=0.0,
            pct_resolved_without_derivation=0.0,
            context_coverage_rate=0.0,
            avg_interactions_per_session=None,
        )

    # Tiempo de respuesta promedio
    times = [i.response_time_ms for i in interactions if i.response_time_ms is not None]
    avg_response_time_ms = sum(times) / len(times) if times else None

    # Leads calientes (basado en score numérico 0-100)
    hot = sum(
        1
        for i in interactions
        if (i.lead_score_numeric or 0) >= HOT_THRESHOLD
    )
    pct_hot_leads = (hot / total) * 100.0

    # Asumimos que leads calientes se derivan a humano.
    # "Resueltas sin derivar" = interacciones con contexto y score < HOT_THRESHOLD.
    resolved_without_derivation = sum(
        1
        for i in interactions
        if (i.lead_score_numeric or 0) < HOT_THRESHOLD and i.used_context
    )
    pct_resolved_without_derivation = (resolved_without_derivation / total) * 100.0

    # Cobertura de contexto (preguntas con match > umbral)
    with_context = sum(1 for i in interactions if i.used_context)
    context_coverage_rate = (with_context / total) * 100.0

    # Interacciones por sesión
    per_session = defaultdict(int)
    for i in interactions:
        per_session[i.session_id] += 1

    total_sessions = len(per_session)
    avg_interactions_per_session = (
        total / total_sessions if total_sessions > 0 else None
    )

    return MetricsSummary(
        total_interactions=total,
        total_sessions=total_sessions,
        avg_response_time_ms=avg_response_time_ms,
        pct_hot_leads=pct_hot_leads,
        pct_resolved_without_derivation=pct_resolved_without_derivation,
        context_coverage_rate=context_coverage_rate,
        avg_interactions_per_session=avg_interactions_per_session,
    )
