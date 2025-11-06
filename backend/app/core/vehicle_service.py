# backend/app/core/vehicles_service.py
from typing import List, Optional

from sqlmodel import select
from sqlmodel import Session  # si tu get_session devuelve sqlmodel.Session
from backend.app.db.models import Vehicle


def get_vehicles_by_model_or_title(
    db: Session,
    query: str,
    max_results: int = 5,
) -> List[Vehicle]:
    """
    Busca vehículos cuyo título, marca o modelo matcheen con el query.
    """
    q = f"%{query.lower()}%"
    stmt = (
        select(Vehicle)
        .where(
            (Vehicle.title.ilike(q)) |
            (Vehicle.marca.ilike(q)) |
            (Vehicle.modelo.ilike(q))
        )
        .limit(max_results)
    )
    return list(db.exec(stmt).all())


def get_vehicles_by_city_and_guarantee(
    db: Session,
    ciudad: Optional[str] = None,
    con_garantia: Optional[bool] = None,
    max_results: int = 20,
) -> List[Vehicle]:
    """
    Devuelve vehículos filtrando por ubicación y garantía.
    """
    stmt = select(Vehicle)

    if ciudad:
        c = f"%{ciudad.lower()}%"
        stmt = stmt.where(Vehicle.ubicacion.ilike(c))

    if con_garantia is not None:
        target = "si" if con_garantia else "no"
        stmt = stmt.where(Vehicle.con_garantia.ilike(target))

    stmt = stmt.limit(max_results)
    return list(db.exec(stmt).all())


def format_vehicle_list_for_answer(vehicles: List[Vehicle]) -> str:
    """
    Texto amigable para el chat.
    """
    if not vehicles:
        return "No encontré vehículos que cumplan con esos criterios en el dataset oficial."

    lines = []
    for v in vehicles:
        line = (
            f"- {v.title} ({v.marca or ''} {v.modelo or ''}, {v.anio or ''}) – "
            f"Ubicación: {v.ubicacion or 'N/D'} – "
            f"Precio base: {v.precio_base or 'N/D'} {v.tipo_moneda or ''} – "
            f"Garantía: {v.con_garantia or 'N/D'}"
        )
        lines.append(line)

    return "Estos son algunos vehículos que encontré en el dataset oficial:\n" + "\n".join(lines)
