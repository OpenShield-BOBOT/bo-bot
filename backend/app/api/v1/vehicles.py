# backend/app/api/v1/vehicles.py

from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from backend.app.db.session import get_session
from backend.app.db.models import Vehicle
from backend.app.services.vehicles_service import (
    get_vehicle_by_plate,
    list_vehicles,
    vehicle_stats,
    format_vehicle_summary,
)

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


# ----------------------------
# 📌 Helpers internos
# ----------------------------
def _build_filters_from_query(
    marca: Optional[str],
    modelo: Optional[str],
    ubicacion: Optional[str],
    anio_min: Optional[int],
    anio_max: Optional[int],
    precio_max: Optional[float],
    categoria: Optional[str],
    tipo_subasta: Optional[str],
    con_garantia: Optional[bool],
) -> Dict[str, Any]:
    """
    Traducimos los query params en el mismo dict de filtros
    que usa vehicles_service.build_vehicle_query.
    """
    filters: Dict[str, Any] = {}

    if marca:
        filters["marca"] = marca
    if modelo:
        filters["modelo"] = modelo
    if ubicacion:
        filters["ubicacion"] = ubicacion
    if anio_min is not None:
        filters["anio_min"] = anio_min
    if anio_max is not None:
        filters["anio_max"] = anio_max
    if precio_max is not None:
        filters["precio_max"] = precio_max
    if categoria:
        filters["categoria"] = categoria
    if tipo_subasta:
        filters["tipo_subasta"] = tipo_subasta
    if con_garantia is not None:
        filters["con_garantia"] = con_garantia

    return filters


# ----------------------------
# 🧱 Endpoints básicos
# ----------------------------
@router.get("/by-plate/{placa}", response_model=Vehicle)
def api_get_vehicle_by_plate(
    placa: str,
    session: Session = Depends(get_session),
):
    """
    Devuelve el registro completo de un vehículo a partir de la placa.
    Útil para debugging o integraciones futuras.
    """
    vehicle = get_vehicle_by_plate(session, placa)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    return vehicle


@router.get("/summary/by-plate/{placa}")
def api_vehicle_summary_by_plate(
    placa: str,
    session: Session = Depends(get_session),
):
    """
    Devuelve un pequeño resumen legible del vehículo (marca, modelo,
    año, precio, ubicación, garantía, etc.).
    """
    vehicle = get_vehicle_by_plate(session, placa)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")

    summary = format_vehicle_summary(vehicle)
    return {"placa": placa, "summary": summary}


# ----------------------------
# 📋 Listado por filtros
# ----------------------------
@router.get("/list", response_model=List[Vehicle])
def api_list_vehicles(
    marca: Optional[str] = Query(None),
    modelo: Optional[str] = Query(None),
    ubicacion: Optional[str] = Query(None),
    anio_min: Optional[int] = Query(None),
    anio_max: Optional[int] = Query(None),
    precio_max: Optional[float] = Query(None),
    categoria: Optional[str] = Query(None),
    tipo_subasta: Optional[str] = Query(None),
    con_garantia: Optional[bool] = Query(
        None,
        description="True para solo con garantía, False para solo sin garantía, omitido para ambos",
    ),
    limite: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """
    Endpoint de lista simple sobre el catálogo del hackatón.

    Ejemplos:
      /api/v1/vehicles/list?marca=toyota
      /api/v1/vehicles/list?marca=hyundai&anio_min=2018&precio_max=8000
      /api/v1/vehicles/list?ubicacion=LIMA&con_garantia=true
    """
    filters = _build_filters_from_query(
        marca=marca,
        modelo=modelo,
        ubicacion=ubicacion,
        anio_min=anio_min,
        anio_max=anio_max,
        precio_max=precio_max,
        categoria=categoria,
        tipo_subasta=tipo_subasta,
        con_garantia=con_garantia,
    )

    vehicles = list_vehicles(session, filters, limit=limite)
    return vehicles


# ----------------------------
# 📊 Stats sobre un conjunto
# ----------------------------
@router.get("/stats")
def api_vehicle_stats(
    marca: Optional[str] = Query(None),
    modelo: Optional[str] = Query(None),
    ubicacion: Optional[str] = Query(None),
    anio_min: Optional[int] = Query(None),
    anio_max: Optional[int] = Query(None),
    precio_max: Optional[float] = Query(None),
    categoria: Optional[str] = Query(None),
    tipo_subasta: Optional[str] = Query(None),
    con_garantia: Optional[bool] = Query(None),
    session: Session = Depends(get_session),
):
    """
    Calcula estadísticas simples sobre el catálogo filtrado:

      - count: cantidad de vehículos
      - avg_price: precio base promedio
      - avg_km: kilometraje promedio

    Ejemplos:
      /api/v1/vehicles/stats?marca=hyundai
      /api/v1/vehicles/stats?marca=kia&anio_min=2018
    """
    filters = _build_filters_from_query(
        marca=marca,
        modelo=modelo,
        ubicacion=ubicacion,
        anio_min=anio_min,
        anio_max=anio_max,
        precio_max=precio_max,
        categoria=categoria,
        tipo_subasta=tipo_subasta,
        con_garantia=con_garantia,
    )

    stats = vehicle_stats(session, filters)
    return stats
