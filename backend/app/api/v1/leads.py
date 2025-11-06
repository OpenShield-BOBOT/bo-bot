from typing import List, Optional  # 👈 añadimos Optional

from fastapi import APIRouter, Depends, Query  # 👈 añadimos Query
from sqlmodel import Session, select

from backend.app.db.session import get_session
from backend.app.db.models import Lead
from backend.app.schemas.leads import LeadCreate, LeadRead

router = APIRouter(
    prefix="/leads",
    tags=["leads"],
)


@router.post("/", response_model=LeadRead)
def create_lead(
    payload: LeadCreate,
    session: Session = Depends(get_session),
) -> LeadRead:
    """
    Crea un lead a partir de un usuario del chat web.
    Usado cuando el lead_score es 'caliente' y el usuario
    deja sus datos de contacto.
    """
    lead = Lead(
        session_id=payload.session_id,
        channel=payload.channel,
        name=payload.name,
        contact=payload.contact,
        lead_score=payload.lead_score,
        status="open",
    )
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return LeadRead(
        id=lead.id,
        session_id=lead.session_id,
        channel=lead.channel,
        name=lead.name,
        contact=lead.contact,
        lead_score=lead.lead_score,
        status=lead.status,
        created_at=lead.created_at,
    )


@router.get("/hot", response_model=List[LeadRead])
def list_hot_leads(
    session: Session = Depends(get_session),
) -> List[LeadRead]:
    """
    Lista leads 'calientes' que están en estado 'open'.
    Vista pensada para el asesor en la web.
    """
    statement = (
        select(Lead)
        .where((Lead.lead_score == "caliente") & (Lead.status == "open"))
        .order_by(Lead.created_at.desc())
    )
    leads = session.exec(statement).all()
    return [
        LeadRead(
            id=l.id,
            session_id=l.session_id,
            channel=l.channel,
            name=l.name,
            contact=l.contact,
            lead_score=l.lead_score,
            status=l.status,
            created_at=l.created_at,
        )
        for l in leads
    ]


@router.get("/", response_model=List[LeadRead])  # 👈 NUEVO
def list_leads(
    session: Session = Depends(get_session),
    channel: Optional[str] = Query(
        None, description='Filtrar por canal. Ej: "web", "whatsapp", "excel_import"'
    ),
    status: Optional[str] = Query(
        None, description='Filtrar por estado. Ej: "open", "closed"'
    ),
    lead_score: Optional[str] = Query(
        None, description='Filtrar por score. Ej: "frio", "templado", "caliente"'
    ),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[LeadRead]:
    """
    Lista leads con filtros básicos.

    Ejemplos:
    - /api/v1/leads?channel=excel_import
    - /api/v1/leads?lead_score=caliente&status=open
    - /api/v1/leads?channel=whatsapp&lead_score=templado
    """
    statement = select(Lead)

    if channel:
        statement = statement.where(Lead.channel == channel)

    if status:
        statement = statement.where(Lead.status == status)

    if lead_score:
        statement = statement.where(Lead.lead_score == lead_score)

    statement = statement.order_by(Lead.created_at.desc())
    statement = statement.offset(offset).limit(limit)

    leads = session.exec(statement).all()

    return [
        LeadRead(
            id=l.id,
            session_id=l.session_id,
            channel=l.channel,
            name=l.name,
            contact=l.contact,
            lead_score=l.lead_score,
            status=l.status,
            created_at=l.created_at,
        )
        for l in leads
    ]
