# backend/app/services/vehicles_service.py

from typing import List, Optional
from sqlmodel import Session, select
from backend.app.db.models import Vehicle


def get_vehicle_by_plate(session: Session, placa: str) -> Optional[Vehicle]:
    """
    Busca un vehículo por placa (case-insensitive, sin espacios).
    """
    placa_norm = placa.strip().lower()
    statement = select(Vehicle).where(Vehicle.placa == placa_norm)
    return session.exec(statement).first()


def get_base_price_by_plate(session: Session, placa: str) -> Optional[float]:
    """
    Devuelve el precio base de un vehículo a partir de la placa.
    """
    vehicle = get_vehicle_by_plate(session, placa)
    if vehicle is None:
        return None
    return vehicle.precio_base


def get_vehicles_with_warranty_in_city(
    session: Session,
    city_text: str,
) -> List[Vehicle]:
    """
    Devuelve vehículos con garantía cuyo campo 'ubicacion' contenga el texto dado.
    Ejemplo: city_text="LIMA" → ubicacion LIKE %LIMA%
    """
    pattern = city_text.strip().upper()
    statement = (
        select(Vehicle)
        .where(Vehicle.con_garantia == True)  # noqa: E712
        .where(Vehicle.ubicacion.contains(pattern))
    )
    return list(session.exec(statement))


def search_vehicles(
    session: Session,
    marca: Optional[str] = None,
    modelo: Optional[str] = None,
    anio_desde: Optional[int] = None,
    anio_hasta: Optional[int] = None,
    con_garantia: Optional[bool] = None,
    ciudad: Optional[str] = None,
    limite: int = 50,
) -> List[Vehicle]:
    """
    Filtro flexible de vehículos según varios criterios.
    Usaremos esto después desde el bot para responder preguntas tipo:
    - "vehículos MG5 con garantía en Lima"
    - "autos 2018 a 2022 en Arequipa"
    """
    statement = select(Vehicle)

    if marca:
        statement = statement.where(Vehicle.marca == marca.strip().lower())

    if modelo:
        statement = statement.where(Vehicle.modelo == modelo.strip().lower())

    if anio_desde is not None:
        statement = statement.where(Vehicle.anio >= anio_desde)

    if anio_hasta is not None:
        statement = statement.where(Vehicle.anio <= anio_hasta)

    if con_garantia is not None:
        statement = statement.where(Vehicle.con_garantia == con_garantia)

    if ciudad:
        # Buscamos el texto dentro de 'ubicacion'
        statement = statement.where(Vehicle.ubicacion.contains(ciudad.strip().upper()))

    statement = statement.limit(limite)

    return list(session.exec(statement))


def format_vehicle_summary(vehicle: Vehicle) -> str:
    """
    Arma una descripción legible para el usuario.
    Esto nos servirá para que el bot responda bonito.
    """
    partes = []

    if vehicle.marca or vehicle.modelo:
        partes.append(f"{(vehicle.marca or '').upper()} {(vehicle.modelo or '').upper()}".strip())

    if vehicle.anio:
        partes.append(f"año {vehicle.anio}")

    if vehicle.kilometraje is not None:
        partes.append(f"{int(vehicle.kilometraje)} km")

    if vehicle.ubicacion:
        partes.append(f"ubicado en {vehicle.ubicacion}")

    if vehicle.precio_base is not None and vehicle.tipo_moneda:
        partes.append(
            f"precio base {vehicle.precio_base:,.0f} {vehicle.tipo_moneda}"
        )

    garantia_text = None
    if vehicle.con_garantia is True:
        garantia_text = "con garantía"
    else:
        garantia_text = "sin garantía"

    if garantia_text:
        partes.append(garantia_text)

    descripcion = ", ".join(partes)

    if vehicle.empresa_proveedora:
        descripcion += f" (proveedor: {vehicle.empresa_proveedora})"

    return descripcion or vehicle.title or "Vehículo del catálogo"
