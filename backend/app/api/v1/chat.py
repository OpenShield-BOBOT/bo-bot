from time import perf_counter

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from backend.app.schemas.chat import ChatMessage, ChatResponse
from backend.app.rag.pipeline import RAGPipeline
from backend.app.db.session import get_session
from backend.app.db.models import Interaction
from backend.app.services.vehicle_qa import try_answer_vehicle_question
from backend.app.core.lead_scoring import (
    classify_lead,
    category_to_points,
    total_points_to_category,
    HOT_THRESHOLD,
)

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)

pipeline = RAGPipeline()


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    payload: ChatMessage,
    session: Session = Depends(get_session),
) -> ChatResponse:
    """
    Endpoint principal de chat.
    - Primero intenta responder usando la BD de vehículos (sin LLM).
    - Si no aplica, llama al pipeline RAG con memoria de sesión.
    - Cada mensaje aporta puntos a un score acumulado por sesión.
    - Si el score cruza HOT_THRESHOLD, sugiere derivación a asesor.
    - Guarda interacción en SQLite.
    """
    start = perf_counter()

    # -----------------------
    # 1) Intentar con Vehicle
    # -----------------------
    handled, vehicle_answer = try_answer_vehicle_question(
        user_message=payload.message,
        session=session,
    )

    if handled:
        # Clasificación del MENSAJE (por texto)
        message_label = classify_lead(payload.message)  # "frio"/"templado"/"caliente"
        message_points = category_to_points(message_label)

        # Score acumulado previo de la sesión
        prev_interactions = session.exec(
            select(Interaction).where(Interaction.session_id == payload.session_id)
        ).all()
        score_before = sum(i.lead_score_numeric or 0 for i in prev_interactions)
        score_after = score_before + message_points

        # Categoría global de la SESIÓN según el acumulado
        session_category = total_points_to_category(score_after)

        # Respuesta basada en datos tabulares, sin RAG
        answer = vehicle_answer or ""
        used_context = False  # aquí NO usamos Chroma ni RAG

        # ¿Acaba de cruzar el umbral caliente?
        crossed_hot_now = score_before < HOT_THRESHOLD <= score_after
        if crossed_hot_now:
            answer += (
                "\n\n🟢 Veo que tienes **alta intención de compra**. "
                "Puedo derivarte con un asesor comercial de BOB Subastas para ayudarte "
                "con los siguientes pasos (ofertas, pagos, reservas, etc.)."
            )

        end = perf_counter()
        response_time_ms = (end - start) * 1000.0

        # Guardar interacción en la BD
        interaction = Interaction(
            session_id=payload.session_id,
            user_message=payload.message,
            bot_response=answer,
            lead_score=message_label,          # etiqueta del MENSAJE
            lead_score_numeric=message_points, # puntos que aportó este mensaje
            response_time_ms=response_time_ms,
            used_context=used_context,
        )
        session.add(interaction)
        session.commit()

        # Respuesta al cliente:
        # - lead_score: categoría de la SESIÓN
        # - lead_score_numeric: score acumulado
        result = {
            "answer": answer,
            "lead_score": session_category,
            "used_context": used_context,
            "response_time_ms": response_time_ms,
            "lead_score_numeric": score_after,
        }
        return ChatResponse(**result)

    # ----------------------------------------
    # 2) Si no aplica Vehicle → pipeline RAG
    # ----------------------------------------

    # Recuperar historial previo de la sesión (ordenado) para memoria
    prev_interactions = session.exec(
        select(Interaction)
        .where(Interaction.session_id == payload.session_id)
        .order_by(Interaction.created_at.asc())
    ).all()

    chat_history = []
    # Tomamos últimos 3 turnos usuario-bot (si existen)
    for it in prev_interactions[-3:]:
        chat_history.append({"role": "user", "content": it.user_message})
        chat_history.append({"role": "assistant", "content": it.bot_response})

    # Llamar al pipeline con historial
    result = await pipeline.answer(
        question=payload.message,
        session_id=payload.session_id,
        chat_history=chat_history,
    )

    end = perf_counter()
    response_time_ms = (end - start) * 1000.0

    # Resultado del pipeline (lead_score = etiqueta del MENSAJE)
    answer = result["answer"]
    message_label = (result.get("lead_score") or "frio").lower()
    used_context = result.get("used_context", False)

    # Puntos del MENSAJE
    message_points = category_to_points(message_label)

    # Score acumulado previo de la sesión
    score_before = sum(i.lead_score_numeric or 0 for i in prev_interactions)
    score_after = score_before + message_points

    # Categoría global de la SESIÓN
    session_category = total_points_to_category(score_after)

    # ¿Acaba de cruzar el umbral caliente?
    crossed_hot_now = score_before < HOT_THRESHOLD <= score_after
    if crossed_hot_now:
        answer += (
            "\n\n🟢 Veo que tienes **alta intención de compra**. "
            "Puedo derivarte con un asesor comercial de BOB Subastas para ayudarte "
            "con los siguientes pasos (ofertas, pagos, reservas, etc.)."
        )

    # Guardar interacción en la base de datos
    interaction = Interaction(
        session_id=payload.session_id,
        user_message=payload.message,
        bot_response=answer,
        lead_score=message_label,           # etiqueta del MENSAJE
        lead_score_numeric=message_points,  # puntos del mensaje
        response_time_ms=response_time_ms,
        used_context=used_context,
    )
    session.add(interaction)
    session.commit()

    # Devolver respuesta al cliente (categoría de SESIÓN + score acumulado)
    result_out = {
        "answer": answer,
        "lead_score": session_category,
        "used_context": used_context,
        "response_time_ms": response_time_ms,
        "lead_score_numeric": score_after,
    }
    return ChatResponse(**result_out)
