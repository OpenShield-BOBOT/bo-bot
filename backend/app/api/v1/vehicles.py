# backend/app/api/v1/vehicles.py

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from backend.app.db.session import engine
from backend.app.db.models import Vehicle
from backend.app.services.vehicles_service import (
    get_vehicle_by_plate,
    get_base_price_by_plate,
    get_vehicles_with_warranty_in_city,
    search_vehicles,
    format_vehicle_summary,
)

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def get_session():
    """
    Dependencia simple para obtener una sesión de BD.
    (Independiente de otras deps que puedas tener.)
    """
    with Session(engine) as session:
        yield session


@router.get("/by-plate/{placa}", response_model=Vehicle)
def api_get_vehicle_by_plate(
    placa: str,
    session: Session = Depends(get_session),
):
    vehicle = get_vehicle_by_plate(session, placa)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    return vehicle


@router.get("/price/by-plate/{placa}")
def api_get_base_price_by_plate(
    placa: str,
    session: Session = Depends(get_session),
):
    price = get_base_price_by_plate(session, placa)
    if price is None:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado o sin precio base")
    return {"placa": placa, "precio_base": price}


@router.get("/with-warranty", response_model=List[Vehicle])
def api_get_vehicles_with_warranty_in_city(
    city: str = Query(..., description="Texto a buscar en 'ubicacion', ej. 'LIMA'"),
    session: Session = Depends(get_session),
):
    vehicles = get_vehicles_with_warranty_in_city(session, city)
    return vehicles


@router.get("/search", response_model=List[Vehicle])
def api_search_vehicles(
    marca: Optional[str] = Query(None),
    modelo: Optional[str] = Query(None),
    anio_desde: Optional[int] = Query(None),
    anio_hasta: Optional[int] = Query(None),
    con_garantia: Optional[bool] = Query(None),
    ciudad: Optional[str] = Query(None),
    limite: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """
    Endpoint genérico de búsqueda.
    Ejemplo:
      /api/v1/vehicles/search?marca=mg&modelo=mg5&con_garantia=true&ciudad=LIMA
    """
    vehicles = search_vehicles(
        session=session,
        marca=marca,
        modelo=modelo,
        anio_desde=anio_desde,
        anio_hasta=anio_hasta,
        con_garantia=con_garantia,
        ciudad=ciudad,
        limite=limite,
    )
    return vehicles


@router.get("/summary/by-plate/{placa}")
def api_vehicle_summary_by_plate(
    placa: str,
    session: Session = Depends(get_session),
):
    vehicle = get_vehicle_by_plate(session, placa)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    summary = format_vehicle_summary(vehicle)
    return {"placa": placa, "summary": summary}
