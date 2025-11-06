import re
from typing import List, Dict, Any, Tuple, Optional

import requests

BOB_API_URL = "https://apiv3.somosbob.com/v3/sublots/details"


def get_live_sublots() -> List[Dict[str, Any]]:
    """Obtiene información en tiempo real de las subastas de BOB."""
    try:
        print("🌐 [BOB API] Consultando sublotes en tiempo real...")
        response = requests.get(BOB_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or []

        if not isinstance(data, list):
            print("⚠️ [BOB API] Respuesta no es una lista, usando []")
            return []

        print(f"✅ [BOB API] {len(data)} registros obtenidos.")
        return data
    except requests.exceptions.RequestException as e:
        print(f"⚠️ [BOB API] Error al conectar con la API: {e}")
        return []


def format_sublot_summary(s: Dict[str, Any]) -> str:
    """
    Formatea un sublote en texto legible para respuestas del chatbot.
    """
    title = s.get("title", "Lote sin título")
    brand = s.get("brand")
    model = s.get("model")
    year = s.get("year")

    price = s.get("basePriceFormatted", "Sin precio")
    location = s.get("location", "Sin ubicación")
    modality = (s.get("modality") or {}).get("name", "Sin modalidad")
    category = (s.get("category_base") or {}).get("name", "Sin categoría")

    company_name = (s.get("company") or {}).get("name", "Sin empresa")
    link = s.get("link", "https://somosbob.com")

    header_parts = [title]
    if brand:
        header_parts.append(brand)
    if model:
        header_parts.append(model)
    if year:
        header_parts.append(f"({year})")

    header = " ".join(str(p) for p in header_parts if p)

    line2 = f"{price} | {location} | {modality} · {category}"
    line3 = f"Empresa: {company_name}"

    return f"**{header}**\n{line2}\n{line3}\n[Ver más]({link})"


def _detect_brand_from_message(
    msg_lower: str,
    sublots: List[Dict[str, Any]],
) -> Optional[str]:
    brands = {
        (s.get("brand") or "").strip().lower()
        for s in sublots
        if s.get("brand")
    }
    brands = {b for b in brands if b}

    for b in sorted(brands, key=len, reverse=True):
        if b in msg_lower:
            return b
    return None


def _detect_model_from_message(
    msg_lower: str,
    sublots: List[Dict[str, Any]],
) -> Optional[str]:
    models = {
        (s.get("model") or "").strip().lower()
        for s in sublots
        if s.get("model")
    }
    models = {m for m in models if m}

    for m in sorted(models, key=len, reverse=True):
        if m in msg_lower:
            return m
    return None


def _detect_vehicle_type_slug(msg_lower: str) -> Optional[str]:
    if any(w in msg_lower for w in ["camioneta", "camionetas", "pickup"]):
        return "autos"
    if any(w in msg_lower for w in ["auto", "carro", "sedan", "sedán"]):
        return "autos"
    if "maquinaria" in msg_lower or "grua" in msg_lower or "grúa" in msg_lower:
        return "maquinaria-pesada"
    return None


def _detect_city(msg_lower: str) -> Optional[str]:
    if "lima" in msg_lower:
        return "LIMA"
    if "villa el salvador" in msg_lower:
        return "VILLA EL SALVADOR"
    if "arequipa" in msg_lower:
        return "AREQUIPA"
    if "trujillo" in msg_lower:
        return "TRUJILLO"
    return None


def _detect_modality(msg_lower: str) -> Optional[str]:
    """
    Detecta modalidad a partir del texto del usuario.
    De momento distinguimos 'venta directa' del resto.

    IMPORTANTE:
    - 'venta directa' → filtramos explícitamente esa modalidad
    - 'subasta(s)' genérico → NO filtramos, dejamos todas las modalidades
    """
    if "venta directa" in msg_lower:
        return "venta-directa"
    return None



def _parse_price_max(msg_lower: str) -> Optional[float]:
    """
    Intenta detectar un precio máximo en el mensaje.
    """
    if not any(w in msg_lower for w in ["menos", "hasta", "máximo", "maximo", "tope"]):
        return None

    cleaned = msg_lower.replace(",", "")
    numbers = re.findall(r"\d+(\.\d+)?", cleaned)
    if not numbers:
        return None

    try:
        value = float(numbers[-1])
    except ValueError:
        return None

    if "k" in cleaned:
        value *= 1000.0

    return value


def _detect_count_intent(msg_lower: str) -> bool:
    return any(
        w in msg_lower
        for w in ["cuantos", "cuántos", "cuantas", "cuántas"]
    )


def filter_sublots_for_message(
    user_message: str,
    sublots: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    msg_lower = user_message.lower()

    intent_count = _detect_count_intent(msg_lower)
    price_max = _parse_price_max(msg_lower)
    city = _detect_city(msg_lower)
    modality_slug = _detect_modality(msg_lower)
    vehicle_type_slug = _detect_vehicle_type_slug(msg_lower)

    brand = _detect_brand_from_message(msg_lower, sublots)
    model = _detect_model_from_message(msg_lower, sublots)

    filtered = sublots

    if brand:
        filtered = [
            s for s in filtered
            if (s.get("brand") or "").strip().lower() == brand
        ]
    
    if model:
        filtered = [
            s for s in filtered
            if (s.get("model") or "").strip().lower() == model
        ]

    if vehicle_type_slug:
        def matches_type(s: Dict[str, Any]) -> bool:
            cat = (s.get("category_base") or {}).get("slug") or ""
            name = (s.get("category_base") or {}).get("name") or ""
            text = f"{cat} {name}".lower()
            return vehicle_type_slug in text

        filtered = [s for s in filtered if matches_type(s)]

    if city:
        filtered = [
            s for s in filtered
            if city in (s.get("location") or "").upper()
        ]

    if modality_slug:
        def matches_modality(s: Dict[str, Any]) -> bool:
            mod = (s.get("modality") or {}).get("slug") or ""
            name = (s.get("modality") or {}).get("name") or ""
            txt = f"{mod} {name}".lower()
            if modality_slug == "venta-directa":
                return "venta directa" in txt or "venta-directa" in txt
            if modality_slug == "subasta":
                return "subasta" in txt
            return False

        filtered = [s for s in filtered if matches_modality(s)]

    if price_max is not None:
        def parse_base_price(s: Dict[str, Any]) -> Optional[float]:
            raw = s.get("basePrice")
            if raw is None:
                return None
            try:
                return float(raw)
            except Exception:
                return None

        filtered_tmp = []
        for s in filtered:
            p = parse_base_price(s)
            if p is not None and p <= price_max:
                filtered_tmp.append(s)
        filtered = filtered_tmp

    metadata: Dict[str, Any] = {
        "brand": brand,
        "model": model,
        "vehicle_type_slug": vehicle_type_slug,
        "city": city,
        "modality_slug": modality_slug,
        "price_max": price_max,
        "intent_count": intent_count,
        "total_before_filters": len(sublots),
        "total_after_filters": len(filtered),
    }

    return filtered, metadata
