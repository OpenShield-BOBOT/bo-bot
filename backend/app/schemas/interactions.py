from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class InteractionRead(BaseModel):
    id: int
    session_id: str
    user_message: str
    bot_response: str
    lead_score: Optional[str]
    lead_score_numeric: Optional[int]
    response_time_ms: float
    used_context: bool
    created_at: datetime

    class Config:
        from_attributes = True