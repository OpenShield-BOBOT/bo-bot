# backend/app/services/vehicle_qa.py

import re
from typing import Tuple, Optional, List

from sqlmodel import Session

from backend.app.db.models import Vehicle
from backend.app.services.vehicles_service import (
    get_vehicle_by_plate,
    get_vehicles_with_warranty_in_city,
    search_vehicles,
    format_vehicle_summary,
)


def _extract_plate(text: str) -> Optional[str]:
    """
    Intenta detectar una placa en el texto.
    Formato peruano típico actual:
    - 3 caracteres alfanuméricos (letra o número)
    - opcional guion o espacio
    - 3 dígitos finales
    Ejemplos válidos:
      BSV248, BSV-248, BSV 248
      P3R248, C7H877, P3R-248
    """
    upper = text.upper()
    # 3 alfanuméricos + opcional guion/espacio + 3 dígitos
    m = re.search(r"\b([A-Z0-9]{3})[-\s]?(\d{3})\b", upper)
    if m:
        # Normalizamos a minúsculas y sin separador, igual que en el CSV (bvu851, p3r248, etc.)
        return (m.group(1) + m.group(2)).lower()
    return None




def _extract_city_hint(text: str) -> Optional[str]:
    """
    Heurística MUY simple para detectar ciudad en el texto.
    (Se puede mejorar luego, por ahora usamos LIMA como principal caso.)
    """
    lower = text.lower()
    if "lima" in lower:
        return "LIMA"
    if "arequipa" in lower:
        return "AREQUIPA"
    if "trujillo" in lower:
        return "TRUJILLO"
    # agrega más si quieres
    return None


def _is_price_question(text: str) -> bool:
    lower = text.lower()
    return "precio" in lower or "precio base" in lower or "cuánto cuesta" in lower


def _is_warranty_question(text: str) -> bool:
    lower = text.lower()
    return "garantia" in lower or "garantía" in lower


def _is_list_with_warranty_question(text: str) -> bool:
    lower = text.lower()
    return ("vehiculos" in lower or "autos" in lower) and "garant" in lower


def try_answer_vehicle_question(
    user_message: str,
    session: Session,
) -> Tuple[bool, Optional[str]]:
    """
    Intenta responder una pregunta sobre vehículos usando la BD.
    Devuelve (handled, answer):
      - handled = True si se pudo construir una respuesta SIN LLM.
      - handled = False si no se detectó que la pregunta sea de vehículos
                  o no se encontró la data.
    """

    text = user_message.strip()
    if not text:
        return False, None

    # 1) Preguntas por placa (precio, garantía, info general)
    plate = _extract_plate(text)
    if plate:
        vehicle = get_vehicle_by_plate(session, plate)
        if not vehicle:
            # Sí era una pregunta de vehículos, pero no encontramos el registro
            return True, f"No encontré información del vehículo con placa {plate.upper()} en el catálogo del hackatón."

        # --- PRECIO BASE ---
        if _is_price_question(text):
            if vehicle.precio_base is not None and vehicle.tipo_moneda:
                return True, (
                    f"El vehículo con placa {plate.upper()} tiene un precio base de "
                    f"{vehicle.precio_base:,.0f} {vehicle.tipo_moneda}."
                )
            else:
                return True, f"No tengo registrado el precio base del vehículo con placa {plate.upper()}."

        # --- GARANTÍA ---
        if _is_warranty_question(text):
            # Normalizamos el valor de con_garantia a un bool o None
            raw = vehicle.con_garantia
            has_warranty: Optional[bool] = None

            if isinstance(raw, bool):
                has_warranty = raw
            elif isinstance(raw, str):
                xl = raw.strip().lower()
                if xl in ("true", "si", "sí", "yes", "1"):
                    has_warranty = True
                elif xl in ("false", "no", "0"):
                    has_warranty = False
                else:
                    has_warranty = None
            else:
                # None, NaN convertido a None, etc.
                has_warranty = None

            # 🔴 Regla de negocio que tú comentaste:
            # - True  → tiene garantía
            # - vacío / cualquier otra cosa → lo tratamos como NO tiene garantía
            if has_warranty is True:
                msg = f"El vehículo con placa {plate.upper()} SÍ cuenta con garantía registrada en el catálogo."
            else:
                msg = f"El vehículo con placa {plate.upper()} NO cuenta con garantía registrada en el catálogo."

            return True, msg

        # --- INFO GENERAL (si no preguntó explícitamente por precio o garantía) ---
        resumen = format_vehicle_summary(vehicle)
        return True, f"Esto es lo que tengo del vehículo con placa {plate.upper()}: {resumen}"

    # 2) Preguntas tipo: "vehículos con garantía en Lima"
    if _is_list_with_warranty_question(text):
        city = _extract_city_hint(text)
        if city:
            vehicles = get_vehicles_with_warranty_in_city(session, city)
        else:
            # Si no detectamos ciudad, devolvemos todos con garantía (limit en el servicio)
            vehicles = search_vehicles(session, con_garantia=True, limite=20)

        if not vehicles:
            return True, "No encontré vehículos con garantía que coincidan con tu búsqueda."

        descripciones: List[str] = []
        for v in vehicles[:10]:  # mostramos solo los primeros 10
            desc = format_vehicle_summary(v)
            if v.placa:
                desc = f"[Placa {v.placa.upper()}] {desc}"
            descripciones.append(f"- {desc}")

        lista = "\n".join(descripciones)
        return True, (
            "Estos son algunos vehículos con garantía que encontré:\n"
            f"{lista}\n\nSi quieres detalles de alguno, dime la placa."
        )

    # 3) Si no detectamos nada específico de vehículos, dejamos que siga el LLM
    return False, None
