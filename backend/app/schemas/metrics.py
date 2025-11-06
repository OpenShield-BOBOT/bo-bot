from pydantic import BaseModel
from typing import Optional


class MetricsSummary(BaseModel):
    total_interactions: int
    total_sessions: int
    avg_response_time_ms: Optional[float]
    pct_hot_leads: float
    pct_resolved_without_derivation: float
    context_coverage_rate: float
    avg_interactions_per_session: Optional[float]
