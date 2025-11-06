from typing import Tuple, Optional

from sqlmodel import Session

from backend.app.services.bob_api_service import (
    get_live_sublots,
    format_sublot_summary,
    filter_sublots_for_message,
)
from backend.app.services.vehicle_qa import (
    try_answer_vehicle_question as qa_from_catalog,
)


def _looks_like_live_auction_question(msg: str) -> bool:
    """
    Heurística para detectar preguntas sobre subastas en vivo
    (usaremos la API real de BOB en esos casos).

    OJO: aquí queremos cosas tipo:
      - "¿qué subastas hay?"
      - "muéstrame las subastas activas"
      - "qué hay en venta directa"
    y NO cosas tipo:
      - "quiero ofertar en una subasta"
      - "cómo participo en las subastas"
      - "cómo es el proceso para ofertar"
    esas van al RAG porque son informativas/proceso.
    """
    msg = msg.lower()

    question_terms = [
        "que subastas hay",
        "qué subastas hay",
        "que lotes hay",
        "qué lotes hay",
        "que hay en subasta",
        "qué hay en subasta",
        "que hay en venta directa",
        "qué hay en venta directa",
        "muestrame subastas",
        "muéstrame subastas",
        "muestrame los lotes",
        "muéstrame los lotes",
        "ver subastas",
        "ver lotes",
        "listar subastas",
        "lista de subastas",
        "subastas activas",
        "subasta activa",
        "subastas en vivo",
        "sublotes",
        "sub-lotes",
    ]

    return any(term in msg for term in question_terms)


def _looks_like_process_question(msg: str) -> bool:
    """
    Detecta si el usuario está preguntando por proceso / cómo participar,
    no por autos específicos ni por ver el catálogo.

    Ejemplos:
      - "quiero ofertar en una subasta"
      - "cómo es el proceso para ofertar"
      - "cómo participo en las subastas"
      - "me refirió un amigo para participar"
      - "cómo me registro"
      - "tiempos de entrega", "plazos", etc.
    """
    msg = msg.lower()

    keywords = [
        "como ofertar",
        "cómo ofertar",
        "quiero ofertar",
        "quiero pujar",
        "como pujar",
        "cómo pujar",
        "como participo",
        "cómo participo",
        "participar en las subastas",
        "participar en subastas",
        "proceso para ofertar",
        "proceso para participar",
        "proceso de subasta",
        "proceso de las subastas",
        "registrarme",
        "registro",
        "inscribirme",
        "inscripción",
        "inscripcion",
        "formulario de registro",
        "como funciona la subasta",
        "cómo funciona la subasta",
        "como funciona bob",
        "cómo funciona bob",
        "metodo de pago",
        "método de pago",
        "pagos",
        "pago",
        "plazo",
        "plazos",
        "tiempo de entrega",
        "entrega inmediata",
        "lo necesito de inmediato",
        "reemplazo urgente",
        "he sido referido",
        "fui referido",
        "referido por un amigo",
    ]

    return any(k in msg for k in keywords)


def _humanize_vehicle_type(slug: Optional[str]) -> Optional[str]:
    if not slug:
        return None
    slug = slug.lower()
    if slug.startswith("maquinaria"):
        return "maquinaria pesada"
    if slug.startswith("auto"):
        return "autos / camionetas"
    return slug.replace("-", " ")


def _humanize_modality(slug: Optional[str]) -> Optional[str]:
    if not slug:
        return None
    slug = slug.lower()
    if slug == "venta-directa":
        return "en venta directa"
    if slug == "subasta":
        return "en subasta"
    return slug.replace("-", " ")


def try_answer_vehicle_question(
    user_message: str,
    session: Session,
    session_id: str,
) -> Tuple[bool, Optional[str]]:
    """
    Lógica híbrida de vehículos / subastas (cuando el RAG no usó contexto):

    1) Preguntas de PROCESO (cómo ofertar, cómo participar, plazos, entregas, etc.):
       - NO las manejamos aquí → las responde el RAG general.

    2) Catálogo del hackatón (tabla Vehicle, CSV embebido):
       - detalle por placa
       - conteos por marca
       - listados y estadísticas con filtros
       (vehicle_qa + memoria de filtros por sesión)

    3) Subastas en vivo (API oficial de BOB):
       - qué subastas/lotes hay ahora
       - filtrar por marca, modelo, tipo de vehículo, ciudad, modalidad, precio máximo
       - distinguir entre preguntas de "¿cuántos?" y "muéstrame ejemplos"

    4) Si nada de lo anterior aplica, devolvemos (False, None) para que
       la respuesta del RAG se mantenga.
    """
    text = (user_message or "").strip()
    if not text:
        return False, None

    msg_lower = text.lower()

    if _looks_like_process_question(msg_lower):
        return False, None

    handled, answer = qa_from_catalog(
        user_message=text,
        session=session,
        session_id=session_id,
    )
    if handled:
        return True, answer

    if _looks_like_live_auction_question(msg_lower):
        sublots = get_live_sublots()
        if not sublots:
            return True, (
                "⚠️ Intenté consultar las subastas activas de BOB Subastas, "
                "pero en este momento no pude obtener la información. "
                "Te recomiendo revisar directamente la web oficial: https://somosbob.com"
            )

        filtered, meta = filter_sublots_for_message(text, sublots)
        total_filt = len(filtered)

        brand = meta.get("brand")
        model = meta.get("model")
        vehicle_type_slug = meta.get("vehicle_type_slug")
        vehicle_type_h = _humanize_vehicle_type(vehicle_type_slug)
        city = meta.get("city")
        modality_slug = meta.get("modality_slug")
        modality_h = _humanize_modality(modality_slug)
        price_max = meta.get("price_max")
        intent_count = meta.get("intent_count", False)

        if total_filt == 0:
            partes = ["Revisé las subastas activas de BOB Subastas"]

            if modality_h:
                partes.append(modality_h)
            if vehicle_type_h:
                partes.append(f"de **{vehicle_type_h}**")
            if brand:
                partes.append(f"para la marca **{brand.title()}**")
            if model:
                partes.append(f"modelo **{model.upper()}**")
            if city:
                partes.append(f"en **{city.title()}**")
            if price_max is not None:
                partes.append(f"con precios hasta aproximadamente **{int(price_max):,}**")

            base = " ".join(partes)
            answer = (
                f"{base}, pero no encontré sublotes que coincidan con esos criterios en este momento.\n\n"
                "Puedes probar con otra marca, tipo de vehículo, ciudad o rango de precio, "
                "o ver el catálogo completo en https://somosbob.com."
            )
            return True, answer

        # 2.b) Sí hay resultados filtrados
        ejemplos = filtered[:3]
        resumen = "\n\n".join(format_sublot_summary(s) for s in ejemplos)

        encabezado_partes = ["📢 Actualmente veo"]

        if intent_count:
            encabezado_partes.append(f"**{total_filt} sublotes**")
        else:
            encabezado_partes.append(f"{total_filt} sublotes")

        if vehicle_type_h:
            encabezado_partes.append(f"de **{vehicle_type_h}**")
        if brand:
            encabezado_partes.append(f"de la marca **{brand.title()}**")
        if model:
            encabezado_partes.append(f"modelo **{model.upper()}**")
        if city:
            encabezado_partes.append(f"en **{city.title()}**")
        if modality_h:
            encabezado_partes.append(modality_h)

        encabezado = " ".join(encabezado_partes) + "."

        if intent_count:
            answer = (
                f"{encabezado}\n\n"
                f"Para que te hagas una idea, aquí van algunos ejemplos:\n\n"
                f"{resumen}\n\n"
                "Si quieres, puedo ayudarte a afinar más la búsqueda "
                "(por ejemplo, otra marca, ciudad o rango de precios), "
                "o puedes ver todos los detalles en [somosbob.com](https://somosbob.com)."
            )
        else:
            answer = (
                f"{encabezado}\n\n"
                f"Te muestro algunos de ellos:\n\n"
                f"{resumen}\n\n"
                "Si quieres ver más opciones o pujar por alguno, "
                "puedes entrar a [somosbob.com](https://somosbob.com), "
                "o decirme qué marca, modelo o ciudad te interesan y te ayudo a filtrarlos."
            )

        return True, answer

    return False, None
