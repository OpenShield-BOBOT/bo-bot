from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class LeadCreate(BaseModel):
    session_id: str
    name: str
    contact: str
    lead_score: Optional[str] = None
    channel: str = "web"


class LeadRead(BaseModel):
    id: int
    session_id: str
    channel: str
    name: Optional[str]
    contact: Optional[str]
    lead_score: Optional[str]
    status: str
    created_at: datetime
