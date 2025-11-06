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

    print("\n==============================")
    print(f"💬 [NUEVO MENSAJE] Usuario → {payload.message}")
    print(f"🧩 Session ID: {payload.session_id}")
    print("==============================")

    start = perf_counter()

    # -----------------------
    # 1️⃣ Intentar con Vehicle
    # -----------------------
    handled, vehicle_answer = try_answer_vehicle_question(
        user_message=payload.message,
        session=session,
    )

    if handled:
        print("🚗 [VEHICLE_QA] La pregunta fue respondida con datos tabulares.")

        # Clasificación del MENSAJE (por texto)
        message_label = classify_lead(payload.message)
        message_points = category_to_points(message_label)
        print(f"🏷️ Lead (mensaje): {message_label.upper()} ({message_points} pts)")

        # Score acumulado previo de la sesión
        prev_interactions = session.exec(
            select(Interaction).where(Interaction.session_id == payload.session_id)
        ).all()
        score_before = sum(i.lead_score_numeric or 0 for i in prev_interactions)
        score_after = score_before + message_points
        print(f"📈 Score acumulado: {score_before} → {score_after}")

        # Categoría global de la SESIÓN
        session_category = total_points_to_category(score_after)
        print(f"💡 Categoría global de sesión: {session_category.upper()}")

        # Respuesta basada en datos tabulares, sin RAG
        answer = vehicle_answer or ""
        used_context = False

        # ¿Acaba de cruzar el umbral caliente?
        crossed_hot_now = score_before < HOT_THRESHOLD <= score_after
        if crossed_hot_now:
            print("🔥 El lead acaba de cruzar el umbral CALIENTE.")
            answer += (
                "\n\n🟢 Veo que tienes **alta intención de compra**. "
                "Puedo derivarte con un asesor comercial de BOB Subastas para ayudarte "
                "con los siguientes pasos (ofertas, pagos, reservas, etc.)."
            )

        end = perf_counter()
        response_time_ms = (end - start) * 1000.0
        print(f"⏱️ Tiempo total: {response_time_ms:.0f} ms")

        # Guardar interacción
        interaction = Interaction(
            session_id=payload.session_id,
            user_message=payload.message,
            bot_response=answer,
            lead_score=message_label,
            lead_score_numeric=message_points,
            response_time_ms=response_time_ms,
            used_context=used_context,
        )
        session.add(interaction)
        session.commit()
        print("💾 Interacción guardada correctamente en SQLite.")

        result = {
            "answer": answer,
            "lead_score": session_category,
            "used_context": used_context,
            "response_time_ms": response_time_ms,
            "lead_score_numeric": score_after,
        }
        print("✅ [FIN Vehicle QA] Respuesta enviada al frontend.")
        return ChatResponse(**result)

    # ----------------------------------------
    # 2️⃣ Si no aplica Vehicle → pipeline RAG
    # ----------------------------------------
    print("🤖 [PIPELINE] Ejecutando RAG con Gemini...")

    # Historial de conversación
    prev_interactions = session.exec(
        select(Interaction)
        .where(Interaction.session_id == payload.session_id)
        .order_by(Interaction.created_at.asc())
    ).all()

    chat_history = []
    for it in prev_interactions[-3:]:
        chat_history.append({"role": "user", "content": it.user_message})
        chat_history.append({"role": "assistant", "content": it.bot_response})
    print(f"🕓 Historial incluido: {len(chat_history)} mensajes")

    # Llamar al pipeline
    result = await pipeline.answer(
        question=payload.message,
        session_id=payload.session_id,
        chat_history=chat_history,
    )

    end = perf_counter()
    response_time_ms = (end - start) * 1000.0
    print(f"⏱️ Tiempo total: {response_time_ms:.0f} ms")

    # Resultado del pipeline
    answer = result["answer"]
    message_label = (result.get("lead_score") or "frio").lower()
    lead_score_numeric = result.get("lead_score_numeric", 0)
    used_context = result.get("used_context", False)

    print(f"🏷️ Lead (mensaje): {message_label.upper()} ({lead_score_numeric})")
    print(f"📚 Contexto usado: {'Sí' if used_context else 'No'}")

    # Puntos del MENSAJE
    message_points = category_to_points(message_label)

    # Score acumulado
    score_before = sum(i.lead_score_numeric or 0 for i in prev_interactions)
    score_after = score_before + message_points
    session_category = total_points_to_category(score_after)
    print(f"📈 Score acumulado: {score_before} → {score_after} ({session_category.upper()})")

    # ¿Cruzó el umbral caliente?
    crossed_hot_now = score_before < HOT_THRESHOLD <= score_after
    if crossed_hot_now:
        print("🔥 El lead acaba de cruzar el umbral CALIENTE.")
        answer += (
            "\n\n🟢 Veo que tienes **alta intención de compra**. "
            "Puedo derivarte con un asesor comercial de BOB Subastas para ayudarte "
            "con los siguientes pasos (ofertas, pagos, reservas, etc.)."
        )

    # Guardar interacción en la BD
    interaction = Interaction(
        session_id=payload.session_id,
        user_message=payload.message,
        bot_response=answer,
        lead_score=message_label,
        lead_score_numeric=message_points,
        response_time_ms=response_time_ms,
        used_context=used_context,
    )
    session.add(interaction)
    session.commit()
    print("💾 Interacción guardada correctamente en SQLite.")
    print("✅ [FIN Pipeline] Respuesta enviada al frontend.\n")

    result_out = {
        "answer": answer,
        "lead_score": session_category,
        "used_context": used_context,
        "response_time_ms": response_time_ms,
        "lead_score_numeric": score_after,
    }
    return ChatResponse(**result_out)
