from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from backend.app.db.session import get_session
from backend.app.db.models import Interaction
from backend.app.schemas.interactions import InteractionRead

router = APIRouter(
    prefix="/interactions",
    tags=["interactions"],
)


@router.get("/", response_model=List[InteractionRead])
def list_interactions(
    session: Session = Depends(get_session),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session_id: Optional[str] = Query(None),
    lead_score: Optional[str] = Query(None),
):
    """
    Lista interacciones. Opcionalmente filtra por session_id y/o lead_score
    (etiqueta textual: 'frio', 'templado', 'caliente').
    """
    stmt = select(Interaction)

    if session_id:
        stmt = stmt.where(Interaction.session_id == session_id)

    if lead_score:
        stmt = stmt.where(Interaction.lead_score == lead_score)

    stmt = stmt.order_by(Interaction.created_at.desc())
    stmt = stmt.offset(offset).limit(limit)

    results = session.exec(stmt).all()
    return results
