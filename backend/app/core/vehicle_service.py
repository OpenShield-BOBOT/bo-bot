# backend/app/core/vehicle_service.py

from backend.app.services.bob_api_service import get_live_sublots, format_sublot_summary
from backend.app.services.vehicle_qa import try_answer_vehicle_question as qa_from_catalog
from backend.app.services.vehicles_service import search_vehicles, format_vehicle_summary


def try_answer_vehicle_question(user_message: str, session):
    """
    Lógica híbrida:
    - Si detecta palabras relacionadas a 'subastas', consulta la API en vivo.
    - Si detecta preguntas específicas de vehículos (placa, garantía, precio base),
      usa el módulo vehicle_qa (base local del hackathon).
    - Si detecta preguntas generales sobre vehículos, busca en la base local.
    """
    msg = user_message.lower()

    # 🚀 SUBASTAS EN VIVO (API)
    if any(word in msg for word in ["subasta", "venta directa", "maquinaria", "ofertas", "en vivo"]):
        sublots = get_live_sublots()
        if not sublots:
            return True, "⚠️ No pude obtener la información de las subastas en este momento."

        resumen = "\n\n".join([format_sublot_summary(s) for s in sublots[:3]])
        answer = (
            "📢 Actualmente hay subastas activas en **BOB Subastas**:\n\n"
            f"{resumen}\n\n"
            "Puedes ver más en [somosbob.com](https://somosbob.com) o contactar a un asesor."
        )
        return True, answer

    # 🔍 VEHÍCULOS CON CONSULTAS ESPECÍFICAS (placa, garantía, precio base)
    handled, answer = qa_from_catalog(user_message, session)
    if handled:
        return True, answer

    # 🚗 CONSULTA GENERAL DE CATÁLOGO LOCAL
    if any(word in msg for word in ["vehículo", "auto", "carro", "camioneta", "garantía", "precio base", "placa"]):
        vehicles = search_vehicles(session=session, limite=3)
        if not vehicles:
            return True, "No encontré vehículos que coincidan con tu búsqueda."

        resumen = "\n\n".join([f"- {format_vehicle_summary(v)}" for v in vehicles])
        answer = (
            "🚗 Algunos vehículos disponibles en el catálogo de **BOB Subastas**:\n\n"
            f"{resumen}\n\n"
            "Puedes solicitar más detalles o ver los vehículos en la web oficial."
        )
        return True, answer

    # ❌ Si no aplica a vehículos ni subastas
    return False, None
