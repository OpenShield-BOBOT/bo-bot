from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class LeadCreate(BaseModel):
    session_id: str
    channel: str = "web"

    nombres: str
    apellidos: str
    dni: Optional[str] = None
    telefono: str
    correo_electronico: EmailStr
    ciudad: str

    lead_score: Optional[str] = None


class LeadRead(BaseModel):
    id: int
    session_id: str
    channel: str

    nombres: Optional[str]
    apellidos: Optional[str]
    dni: Optional[str]
    telefono: Optional[str]
    correo_electronico: Optional[str]
    ciudad: Optional[str]

    lead_score: Optional[str]
    status: str
    created_at: datetime
