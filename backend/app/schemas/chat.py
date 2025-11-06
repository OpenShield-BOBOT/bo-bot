from pydantic import BaseModel
from typing import Optional


class ChatMessage(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    answer: str
    lead_score: Optional[str] = None           # categoría de la SESIÓN (frio/templado/caliente)
    used_context: bool = False
    response_time_ms: Optional[float] = None
    lead_score_numeric: Optional[int] = None   # 👈 score acumulado 0–N de la sesión
