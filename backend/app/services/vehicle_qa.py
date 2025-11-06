# backend/app/services/vehicle_qa.py

import json
import re
from typing import Tuple, Optional, List, Dict, Any

from sqlmodel import Session
import google.generativeai as genai

from backend.app.core.config import get_settings
from backend.app.db.models import Vehicle
from backend.app.services.vehicles_service import (
    get_vehicle_by_plate,
    format_vehicle_summary,
    count_vehicles,
    list_vehicles,
    vehicle_stats,
)

settings = get_settings()

# Configuramos Gemini una sola vez
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)
else:
    print("⚠️ Advertencia: GEMINI_API_KEY no configurada. vehicle_qa usará solo heurísticas simples.")


# =================================================
# 🔎 Detección de placa (fallback útil)
# =================================================
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
    m = re.search(r"\b([A-Z0-9]{3})[-\s]?(\d{3})\b", upper)
    if m:
        # Normalizamos a minúsculas y sin separador
        return (m.group(1) + m.group(2)).lower()
    return None


# =================================================
# 🧠 Parser de intención + filtros (Gemini)
# =================================================
def parse_vehicle_question_with_llm(user_message: str) -> Dict[str, Any]:
    """
    Usa Gemini para:
      - decidir si la pregunta es sobre vehículos/subastas
      - extraer intención (count, list, detail, stats, unknown)
      - extraer filtros estructurados para SQL
    """
    system_prompt = """
Eres un PARSER especializado en consultas de subastas de vehículos de BOB Subastas.

Tu tarea NO es responder al usuario, sino analizar su mensaje y devolver un JSON
con la intención de consulta y los filtros detectados.

Devuelve SIEMPRE un JSON con esta estructura exacta:

{
  "is_vehicle_question": bool,
  "intent": "count" | "list" | "detail" | "stats" | "unknown",
  "filters": {
    "marca": string or null,
    "modelo": string or null,
    "placa": string or null,
    "ubicacion": string or null,
    "anio_min": int or null,
    "anio_max": int or null,
    "precio_max": float or null,
    "categoria": string or null,
    "tipo_subasta": string or null,
    "con_garantia": bool or null
  },
  "metric": "precio" | "kilometraje" | null
}

Guía rápida:

- is_vehicle_question:
    true  → cuando el usuario pregunta por vehículos, autos, camionetas, subastas, lotes, etc.
    false → cuando habla de otros temas (pagos, scoring, políticas, etc.)

- intent:
    "count"  → cuando pregunta "cuántos", "cuántas", "cantidad", etc.
    "list"   → cuando pide ver autos, listar opciones, "qué autos hay", "muéstrame".
    "detail" → cuando menciona una PLACA específica o un título muy concreto de vehículo.
    "stats"  → cuando pide promedio, mínimo, máximo, rango de precios o kilometraje.
    "unknown" → cuando no esté claro.

- filtros:
    - marca: ej. "toyota", "kia", "hyundai".
    - modelo: ej. "rio", "corolla", "hilux".
    - placa: texto tipo "ABC123" (aunque venga como "ABC-123" o "ABC 123").
    - ubicacion: ciudad o región (ej. "Lima", "Arequipa").
    - anio_min / anio_max: deducidos de frases como "desde 2018", "de 2020 a 2022".
    - precio_max: si dice "menos de 8000", "hasta 15 mil", etc.
    - con_garantia:
        true si pide explícitamente garantía o vehículos con garantía.
        false si pide explícitamente sin garantía.
        null si no menciona.
    - categoria, tipo_subasta: si habla de "livianos", "pesados", "venta directa", etc.

- metric (solo para intent="stats"):
    "precio"      → si habla de precio, barato, caro, promedio de precios, etc.
    "kilometraje" → si habla de km, kilometraje, uso, recorrido, etc.
    null          → si no aplica.

Responde SOLO con el JSON, sin texto adicional ni explicaciones.
"""

    prompt = f"{system_prompt}\n\nMENSAJE_DEL_USUARIO:\n{user_message}"

    if not settings.gemini_api_key:
        return {
            "is_vehicle_question": False,
            "intent": "unknown",
            "filters": {},
            "metric": None,
        }

    try:
        model_name = getattr(settings, "gemini_model_name", "gemini-2.5-flash") or "gemini-2.5-flash"
        model = genai.GenerativeModel(model_name)

        # 👇 Forzamos salida en JSON puro
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
            },
        )
        raw = (response.text or "").strip()

        # Intento directo de parseo
        try:
            data = json.loads(raw)
        except Exception:
            # Por si el modelo metiera ruido, intentamos recortar al primer y último '{' '}'.
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(raw[start : end + 1])
            else:
                raise

        if "filters" not in data or data["filters"] is None:
            data["filters"] = {}

        filters = data["filters"]
        for key in [
            "marca", "modelo", "placa", "ubicacion",
            "anio_min", "anio_max", "precio_max",
            "categoria", "tipo_subasta", "con_garantia",
        ]:
            filters.setdefault(key, None)

        data["filters"] = filters
        data.setdefault("metric", None)
        data.setdefault("intent", "unknown")
        data.setdefault("is_vehicle_question", False)

        return data

    except Exception as e:
        print(f"⚠️ [VehicleParser] Error parseando con Gemini: {e}")
        # Fallback súper conservador: que el orquestador decida si es vehículo o no.
        return {
            "is_vehicle_question": False,
            "intent": "unknown",
            "filters": {},
            "metric": None,
        }


# =================================================
# 🧠 Memoria de filtros por sesión (continuidad)
# =================================================

# session_id -> filtros usados en la última consulta de vehículos
FILTER_MEMORY: Dict[str, Dict[str, Any]] = {}


def _get_session_filters(session_id: str) -> Dict[str, Any]:
    """Devuelve una copia de los filtros recordados para esta sesión."""
    return FILTER_MEMORY.get(session_id, {}).copy()


def _merge_with_session_filters(session_id: str, new_filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Completa filtros vacíos con lo último que recordamos para esta sesión.
    Lo nuevo siempre pisa a lo viejo.

    Ejemplo:
      - sesión tenía {"marca": "toyota", "ubicacion": "LIMA"}
      - usuario dice: "afínalo por precio menor a 19000"
        → new_filters = {"precio_max": 19000}
      - merged = {"marca": "toyota", "ubicacion": "LIMA", "precio_max": 19000}
    """
    prev = _get_session_filters(session_id)
    merged = prev.copy()

    for k, v in (new_filters or {}).items():
        # si viene algo nuevo (no None/""), lo usamos
        if v not in (None, ""):
            merged[k] = v

    return merged


def _remember_session_filters(session_id: str, filters: Dict[str, Any]) -> None:
    """
    Guarda filtros relevantes para la próxima pregunta de esta sesión.
    """
    if not filters:
        return

    keys_of_interest = [
        "marca",
        "modelo",
        "ubicacion",
        "anio_min",
        "anio_max",
        "precio_max",
        "categoria",
        "tipo_subasta",
        "con_garantia",
    ]
    snapshot = {k: filters.get(k) for k in keys_of_interest}
    FILTER_MEMORY[session_id] = snapshot


def try_answer_vehicle_question(
    user_message: str,
    session: Session,
    session_id: str,
) -> Tuple[bool, Optional[str]]:
    """
    Intenta responder una pregunta sobre vehículos usando la BD (catálogo hackathon).

    Devuelve (handled, answer):
      - handled = True si se pudo construir una respuesta basándose en el catálogo
        (detail / count / list / stats).
      - handled = False si no se detectó que la pregunta sea de vehículos
        o la intención no es clara → que responda el RAG normal.
    """

    text = (user_message or "").strip()
    if not text:
        return False, None

    plate_from_regex = _extract_plate(text)
    if plate_from_regex:
        vehicle = get_vehicle_by_plate(session, plate_from_regex)
        if not vehicle:
            return True, (
                f"No encontré un vehículo con placa **{plate_from_regex.upper()}** "
                "en el catálogo del hackatón."
            )

        price = (
            f"{vehicle.precio_base:,.0f} {vehicle.tipo_moneda}"
            if vehicle.precio_base is not None and vehicle.tipo_moneda
            else "no disponible"
        )
        km = (
            f"{vehicle.kilometraje:,.0f} km"
            if vehicle.kilometraje is not None
            else "no disponible"
        )
        anio = vehicle.anio or "no disponible"
        garantia = "Sí" if vehicle.con_garantia else "No"
        ubic = vehicle.ubicacion or "no disponible"
        tipo = vehicle.tipo_subasta or "no especificado"

        answer = (
            f"Este es el detalle del vehículo con placa **{plate_from_regex.upper()}**:\n\n"
            f"- **Título**: {vehicle.title}\n"
            f"- **Marca / Modelo**: {vehicle.marca or '-'} / {vehicle.modelo or '-'}\n"
            f"- **Año**: {anio}\n"
            f"- **Precio base**: {price}\n"
            f"- **Kilometraje**: {km}\n"
            f"- **Ubicación**: {ubic}\n"
            f"- **Tipo de subasta**: {tipo}\n"
            f"- **Con garantía**: {garantia}\n"
            f"- **Empresa proveedora**: {vehicle.empresa_proveedora or '-'}\n"
        )
        answer += "\nSi quieres, puedo ayudarte a comparar este vehículo con otros similares en precio o año."

        _remember_session_filters(session_id, {"placa": plate_from_regex})
        return True, answer

    parsed = parse_vehicle_question_with_llm(text)
    print(f"🔎 [VehicleParser] Parsed → {parsed}")

    if not parsed.get("is_vehicle_question", False):
        return False, None

    intent = (parsed.get("intent") or "unknown").lower()
    filters: Dict[str, Any] = parsed.get("filters") or {}
    metric = parsed.get("metric")

    allowed_intents = {"detail", "count", "list", "stats"}
    if intent not in allowed_intents:
        return False, None

    for key in ("marca", "modelo", "ubicacion", "categoria", "tipo_subasta"):
        if filters.get(key):
            filters[key] = str(filters[key]).strip()

    filters = _merge_with_session_filters(session_id, filters)

    if intent == "detail":
        placa = filters.get("placa")
        vehicle: Optional[Vehicle] = None

        try:
            if placa:
                vehicle = get_vehicle_by_plate(session, placa)

            if not vehicle:
                vehicles = list_vehicles(session, filters, limit=1)
                vehicle = vehicles[0] if vehicles else None
        except Exception as e:
            print(f"⚠️ [VehicleQA] Error buscando detalle: {e}")
            return False, None

        if not vehicle:
            return True, (
                "No encontré un vehículo que coincida con esos datos en el catálogo del hackatón "
                "de BOB Subastas."
            )

        _remember_session_filters(session_id, filters)

        price = (
            f"{vehicle.precio_base:,.0f} {vehicle.tipo_moneda}"
            if vehicle.precio_base is not None and vehicle.tipo_moneda
            else "no disponible"
        )
        km = (
            f"{vehicle.kilometraje:,.0f} km"
            if vehicle.kilometraje is not None
            else "no disponible"
        )
        anio = vehicle.anio or "no disponible"
        garantia = "Sí" if vehicle.con_garantia else "No"
        ubic = vehicle.ubicacion or "no disponible"
        tipo = vehicle.tipo_subasta or "no especificado"

        answer = (
            f"Este es el detalle del vehículo que encontré:\n\n"
            f"- **Título**: {vehicle.title}\n"
            f"- **Marca / Modelo**: {vehicle.marca or '-'} / {vehicle.modelo or '-'}\n"
            f"- **Año**: {anio}\n"
            f"- **Precio base**: {price}\n"
            f"- **Kilometraje**: {km}\n"
            f"- **Ubicación**: {ubic}\n"
            f"- **Tipo de subasta**: {tipo}\n"
            f"- **Con garantía**: {garantia}\n"
            f"- **Empresa proveedora**: {vehicle.empresa_proveedora or '-'}\n"
        )
        answer += "\nSi quieres, puedo ayudarte a comparar este vehículo con otros similares en precio o año."
        return True, answer

    if intent == "count":
        try:
            count = count_vehicles(session, filters)
        except Exception as e:
            print(f"⚠️ [VehicleQA] Error en count_vehicles: {e}")
            return False, None

        _remember_session_filters(session_id, filters)

        marca = filters.get("marca")
        ubicacion = filters.get("ubicacion")

        if count == 0:
            if marca and ubicacion:
                answer = (
                    f"No encontré vehículos de la marca **{marca}** "
                    f"en subasta en **{ubicacion}** en este momento."
                )
            elif marca:
                answer = (
                    f"No encontré vehículos de la marca **{marca}** "
                    "en las subastas del catálogo del hackatón."
                )
            else:
                answer = "No encontré vehículos que cumplan esos criterios en el catálogo del hackatón."
        elif count == 1:
            if marca:
                answer = f"Actualmente hay **1 vehículo {marca}** en el catálogo con esos criterios."
            else:
                answer = "Actualmente hay **1 vehículo** en el catálogo con esos criterios."
        else:
            base = f"Actualmente hay **{count} vehículos** en el catálogo"
            if marca:
                base += f" de la marca **{marca}**"
            if ubicacion:
                base += f" en **{ubicacion}**"
            base += "."
            answer = base + " Si quieres, puedo ayudarte a ver algunos casos concretos."

        return True, answer

    if intent == "list":
        try:
            vehicles = list_vehicles(session, filters, limit=5)
        except Exception as e:
            print(f"⚠️ [VehicleQA] Error en list_vehicles: {e}")
            return False, None

        _remember_session_filters(session_id, filters)

        if not vehicles:
            return True, "No encontré vehículos que cumplan esos criterios en el catálogo del hackatón."

        lines: List[str] = []
        for v in vehicles:
            price = (
                f"{v.precio_base:,.0f} {v.tipo_moneda}"
                if v.precio_base is not None and v.tipo_moneda
                else "precio no disponible"
            )
            anio = v.anio or "s/año"
            ubic = v.ubicacion or "ubicación no disponible"
            placa_txt = f"[Placa {v.placa.upper()}] " if v.placa else ""
            lines.append(f"- {placa_txt}**{v.title}** · {anio} · {ubic} · {price}")

        answer = (
            "Estos son algunos vehículos que encontré para tu búsqueda:\n\n"
            + "\n".join(lines)
            + "\n\nSi quieres, puedo ayudarte a afinar la búsqueda por año, precio o ubicación."
        )
        return True, answer

    if intent == "stats":
        try:
            stats = vehicle_stats(session, filters)
        except Exception as e:
            print(f"⚠️ [VehicleQA] Error en vehicle_stats: {e}")
            return False, None

        _remember_session_filters(session_id, filters)

        count = stats["count"]
        if count == 0:
            return True, "No encontré vehículos suficientes para calcular estadísticas con esos criterios."

        partes: List[str] = [f"Encontré **{count} vehículos** que coinciden con tu búsqueda."]

        avg_price = stats.get("avg_price")
        avg_km = stats.get("avg_km")

        if metric == "precio" or (metric is None and avg_price is not None):
            partes.append(
                f"El **precio base promedio** está alrededor de **{avg_price:,.0f}** "
                "(según los registros disponibles)."
            )

        if metric == "kilometraje" or (metric is None and avg_km is not None):
            partes.append(
                f"El **kilometraje promedio** está alrededor de **{avg_km:,.0f} km**."
            )

        answer = " ".join(partes) + " Si quieres, puedo mostrarte algunos ejemplos específicos."
        return True, answer

    return False, None
