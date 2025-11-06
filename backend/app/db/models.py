from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Interaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str
    user_message: str
    bot_response: str
    lead_score: Optional[str] = None
    lead_score_numeric: Optional[int] = None
    response_time_ms: Optional[float] = None
    used_context: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Lead(SQLModel, table=True):
    """
    Lead derivado a un asesor desde el chat web (o desde otros canales).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str
    channel: str = Field(default="web")  # "web", "whatsapp", etc.
    name: Optional[str] = None
    contact: Optional[str] = None  # teléfono, email o ambos
    lead_score: Optional[str] = None  # "caliente", "templado", etc.
    status: str = Field(default="open")  # "open" / "closed"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Vehicle(SQLModel, table=True):
    """
    Vehículo del dataset del hackatón (hackathon_data.csv).
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    # Columnas tal cual vienen en el CSV
    title: str
    precio_base: Optional[float] = None
    tipo_moneda: Optional[str] = None
    ubicacion: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    placa: Optional[str] = None
    kilometraje: Optional[float] = None 
    anio: Optional[int] = None
    procedencia: Optional[str] = None
    con_garantia: Optional[bool] = None
    categoria: Optional[str] = None
    tipo_subasta: Optional[str] = None
    empresa_proveedora: Optional[str] = None

