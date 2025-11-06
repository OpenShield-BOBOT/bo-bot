# backend/app/services/vehicles_service.py

from typing import List, Optional, Dict, Any

from sqlmodel import Session, select
from sqlalchemy import func

from backend.app.db.models import Vehicle


# -------------------------------------------------
# 🧱 Helpers de acceso directo
# -------------------------------------------------
def get_vehicle_by_plate(session: Session, placa: str) -> Optional[Vehicle]:
    """
    Busca un vehículo por placa (normalmente almacenada en minúsculas y sin espacios).
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


# -------------------------------------------------
# 🔍 Query genérica por filtros
# -------------------------------------------------
def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        # Permitimos cosas tipo "8 000" o "8,000"
        txt = str(value).replace(" ", "").replace(",", "").strip()
        return float(txt)
    except Exception:
        return None


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "si", "sí", "yes", "1"):
            return True
        if v in ("false", "no", "0"):
            return False
    # Si es algo raro, mejor lo ignoramos (None → no filtramos)
    return None


def build_vehicle_query(filters: Dict) -> "select":
    """
    Construye una sentencia select(Vehicle) aplicando los filtros indicados.

    Filtros soportados (todas las claves son opcionales):

      - marca: str
      - modelo: str
      - placa: str
      - ubicacion: str
      - anio_min: int o str numérica
      - anio_max: int o str numérica
      - precio_max: float o str numérica
      - categoria: str
      - tipo_subasta: str
      - con_garantia: bool / str ("true"/"false")

    NOTA sobre con_garantia:
      En los datos solo hay True o vacío (que significa False).
      Aquí el filtro se trata como un bool normal.
    """
    stmt = select(Vehicle)

    marca = filters.get("marca")
    if marca:
        stmt = stmt.where(Vehicle.marca.ilike(f"%{marca}%"))

    modelo = filters.get("modelo")
    if modelo:
        stmt = stmt.where(Vehicle.modelo.ilike(f"%{modelo}%"))

    placa = filters.get("placa")
    if placa:
        placa_norm = str(placa).strip().lower()
        stmt = stmt.where(Vehicle.placa == placa_norm)

    ubicacion = filters.get("ubicacion")
    if ubicacion:
        stmt = stmt.where(Vehicle.ubicacion.ilike(f"%{ubicacion}%"))

    anio_min = _to_int(filters.get("anio_min"))
    if anio_min is not None:
        stmt = stmt.where(Vehicle.anio >= anio_min)

    anio_max = _to_int(filters.get("anio_max"))
    if anio_max is not None:
        stmt = stmt.where(Vehicle.anio <= anio_max)

    precio_max = _to_float(filters.get("precio_max"))
    if precio_max is not None:
        stmt = stmt.where(Vehicle.precio_base <= precio_max)

    categoria = filters.get("categoria")
    if categoria:
        stmt = stmt.where(Vehicle.categoria.ilike(f"%{categoria}%"))

    tipo_subasta = filters.get("tipo_subasta")
    if tipo_subasta:
        stmt = stmt.where(Vehicle.tipo_subasta.ilike(f"%{tipo_subasta}%"))

    con_garantia_raw = filters.get("con_garantia") if "con_garantia" in filters else None
    con_garantia = _to_bool(con_garantia_raw)
    if con_garantia is not None:
        stmt = stmt.where(Vehicle.con_garantia == con_garantia)

    return stmt


def count_vehicles(session: Session, filters: Dict) -> int:
    """
    Devuelve la cantidad de vehículos que cumplen los filtros.
    """
    stmt = build_vehicle_query(filters)
    stmt = stmt.with_only_columns(func.count()).select_from(Vehicle)
    return session.exec(stmt).one()


def list_vehicles(
    session: Session,
    filters: Dict,
    limit: int = 10,
) -> List[Vehicle]:
    """
    Devuelve una lista de vehículos que cumplen los filtros (máximo 'limit').
    """
    stmt = build_vehicle_query(filters).limit(limit)
    return list(session.exec(stmt))


def vehicle_stats(session: Session, filters: Dict) -> Dict:
    """
    Calcula estadísticas simples sobre el conjunto filtrado:
      - count: cantidad de vehículos
      - avg_price: precio_base promedio (o None si no hay datos)
      - avg_km: kilometraje promedio (o None si no hay datos)
    """
    stmt = build_vehicle_query(filters)
    rows = list(session.exec(stmt))

    if not rows:
        return {"count": 0, "avg_price": None, "avg_km": None}

    prices = [v.precio_base for v in rows if v.precio_base is not None]
    kms = [v.kilometraje for v in rows if v.kilometraje is not None]

    avg_price = sum(prices) / len(prices) if prices else None
    avg_km = sum(kms) / len(kms) if kms else None

    return {
        "count": len(rows),
        "avg_price": avg_price,
        "avg_km": avg_km,
    }


# -------------------------------------------------
# 🧩 Funciones legacy / wrappers para no romper API
# -------------------------------------------------
def get_vehicles_with_warranty_in_city(
    session: Session,
    city_text: str,
) -> List[Vehicle]:
    """
    Versión antigua, ahora envuelta sobre la query genérica.

    Devuelve vehículos con garantía cuyo campo 'ubicacion' coincida con el texto dado.
    Ejemplo: city_text="LIMA" → ubicacion ILIKE %LIMA%
    """
    filters: Dict[str, Any] = {
        "con_garantia": True,
        "ubicacion": city_text,
    }
    return list_vehicles(session, filters, limit=50)


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

    Se mantiene la firma antigua para no romper /api/v1/vehicles/search,
    pero internamente construye un dict de filtros y delega en list_vehicles().
    """
    filters: Dict[str, Any] = {}

    if marca:
        filters["marca"] = marca

    if modelo:
        filters["modelo"] = modelo

    if anio_desde is not None:
        filters["anio_min"] = anio_desde

    if anio_hasta is not None:
        filters["anio_max"] = anio_hasta

    if con_garantia is not None:
        filters["con_garantia"] = con_garantia

    if ciudad:
        filters["ubicacion"] = ciudad

    return list_vehicles(session, filters, limit=limite)


# -------------------------------------------------
# 📝 Formateo para el bot / API
# -------------------------------------------------
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

    # En datos: True → con garantía, vacío/None → sin garantía
    garantia_text = "con garantía" if vehicle.con_garantia else "sin garantía"
    partes.append(garantia_text)

    descripcion = ", ".join(partes)

    if vehicle.empresa_proveedora:
        descripcion += f" (proveedor: {vehicle.empresa_proveedora})"

    return descripcion or vehicle.title or "Vehículo del catálogo"
