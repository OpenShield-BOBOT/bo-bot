from time import perf_counter

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from backend.app.schemas.chat import ChatMessage, ChatResponse
from backend.app.rag.pipeline import RAGPipeline
from backend.app.db.session import get_session
from backend.app.db.models import Interaction
from backend.app.core.vehicle_service import try_answer_vehicle_question
from backend.app.core.lead_scoring import (
    evaluate_lead,
    total_points_to_category,
    HOT_THRESHOLD,
    FALLBACK_SCORE,  # usamos el mismo fallback (20) que en lead_scoring.py
)

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)

pipeline = RAGPipeline()


def build_conversation_text(prev_interactions: list[Interaction], new_message: str) -> str:
    """
    Construye un texto con TODOS los mensajes del usuario en la sesión,
    más el mensaje actual. No incluimos los mensajes del bot para no
    “contaminar” el scoring.
    """
    user_msgs: list[str] = []

    for it in prev_interactions:
        if it.user_message:
            user_msgs.append(f"Usuario: {it.user_message}")

    user_msgs.append(f"Usuario: {new_message}")

    conversation_text = "\n".join(user_msgs)
    print("🧾 Texto de conversación enviado a scoring:")
    print(conversation_text)
    return conversation_text


def user_clearly_requests_advisor(
    prev_interactions: list[Interaction],
    new_message: str,
) -> bool:
    """
    Detecta si el usuario está pidiendo explícitamente hablar con un asesor
    o si está respondiendo afirmativamente a una oferta de asesor del bot.
    """
    msg = (new_message or "").strip().lower()
    if not msg:
        return False

    # 1) Frases directas donde el usuario pide asesor/contacto
    direct_phrases = [
        "hablar con un asesor",
        "quiero un asesor",
        "quiero hablar con un asesor",
        "quiero que me contacten",
        "quiero que me contact",
        "que me contacten",
        "me contacten",
        "quiero contacto",
        "quiero que me llamen",
        "quiero que me llamen",
        "llámenme",
        "llamame",
        "contactarme",
        "asesor comercial",
    ]
    if any(p in msg for p in direct_phrases):
        return True

    # 2) Confirmación corta después de que el bot ofreció asesor
    if prev_interactions:
        last_bot_resp = prev_interactions[-1].bot_response or ""
        last_bot_lower = last_bot_resp.lower()

        # ¿El bot habló de asesor/contacto en el último mensaje?
        if any(
            kw in last_bot_lower
            for kw in ["asesor", "que te contacten", "que te contactemos", "derivarte con un asesor"]
        ):
            # Y el usuario responde algo tipo "sí", "ok", "si por favor", "claro", etc.
            short_affirmatives = [
                "si",
                "sí",
                "ok",
                "okay",
                "claro",
                "dale",
                "de acuerdo",
                "si por favor",
                "sí por favor",
                "por favor",
            ]
            # Mensajes cortos que contengan alguna de estas palabras
            if len(msg) <= 30 and any(a in msg for a in short_affirmatives):
                return True

    return False


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    payload: ChatMessage,
    session: Session = Depends(get_session),
) -> ChatResponse:
    """
    Endpoint principal de chat.

    Prioridad:
      1) RAG con Chroma (docs embebidos).
      2) Catálogo de vehículos (CSV → tabla Vehicle).
      3) API en vivo de BOB (sublots/details).

    Siempre se evalúa scoring sobre TODA la conversación.
    """

    print("\n==============================")
    print(f"💬 [NUEVO MENSAJE] Usuario → {payload.message}")
    print(f"🧩 Session ID: {payload.session_id}")
    print("==============================")

    start = perf_counter()

    # ---------------------------------
    # Historial de la sesión
    # ---------------------------------
    prev_interactions = session.exec(
        select(Interaction)
        .where(Interaction.session_id == payload.session_id)
        .order_by(Interaction.created_at.asc())
    ).all()

    if prev_interactions:
        score_before = prev_interactions[-1].lead_score_numeric or 0
    else:
        score_before = 0

    print(f"📊 Score previo de sesión: {score_before}")

    # Texto completo de conversación para scoring
    conversation_text = build_conversation_text(prev_interactions, payload.message)

    # Flag: ¿el usuario pidió claramente un asesor?
    user_wants_advisor = user_clearly_requests_advisor(prev_interactions, payload.message)
    print(f"📞 ¿Usuario pidió asesor explícitamente? → {'sí' if user_wants_advisor else 'no'}")

    # ----------------------------------------
    # 1️⃣ RAG con Chroma (prioridad #1)
    # ----------------------------------------
    print("🤖 [PIPELINE] Ejecutando RAG con Gemini...")

    # Historial reducido para el LLM (últimos 3 turnos)
    chat_history = []
    for it in prev_interactions[-3:]:
        chat_history.append({"role": "user", "content": it.user_message})
        chat_history.append({"role": "assistant", "content": it.bot_response})
    print(f"🕓 Historial incluido en RAG: {len(chat_history)} mensajes")

    rag_result = await pipeline.answer(
        question=payload.message,
        session_id=payload.session_id,
        chat_history=chat_history,
    )

    rag_answer = rag_result["answer"]
    rag_used_context = rag_result.get("used_context", False)

    print(f"📚 Contexto usado por RAG: {'Sí' if rag_used_context else 'No'}")

    final_answer = rag_answer
    used_context = rag_used_context

    # ---------------------------------------------------
    # 2️⃣ Si RAG NO usó contexto → intentamos vehículos
    #     (catálogo CSV → tabla Vehicle + API BOB)
    # ---------------------------------------------------
    if not rag_used_context:
        print("🚗 [VEHICLE_QA] RAG no usó contexto, probando módulo de vehículos...")
        handled, vehicle_answer = try_answer_vehicle_question(
            user_message=payload.message,
            session=session,
            session_id=payload.session_id,
        )
        if handled:
            print("🚗 [VEHICLE_QA] La pregunta fue respondida con datos tabulares / API BOB.")
            final_answer = vehicle_answer or ""
            used_context = False  # viene de tablas / API, no de Chroma
        else:
            print("🚗 [VEHICLE_QA] No aplicó vehículo/subastas, se mantiene respuesta de RAG.")

    # --------------------------------
    # 3️⃣ Scoring sobre la conversación
    # --------------------------------
    detailed = evaluate_lead(conversation_text)

    # Usamos el mismo fallback estándar que en evaluate_lead (20),
    # por si por alguna razón no llega 'total' en el dict.
    total = detailed.get("total", FALLBACK_SCORE)
    try:
        total = int(total)
    except Exception:
        total = FALLBACK_SCORE

    session_category = total_points_to_category(total)

    # 🔥 Si el usuario pidió asesor explícitamente, forzamos score caliente
    if user_wants_advisor and total < HOT_THRESHOLD:
        print(
            "📞 El usuario ha solicitado contacto con un asesor. "
            "Forzamos score CALIENTE para esta sesión."
        )
        total = HOT_THRESHOLD
        session_category = "caliente"

    print(f"🏷️ Lead (detallado): {detailed.get('categoria', 'frio').upper()} ({total} pts)")
    print(f"💡 Categoría global (simple): {session_category.upper()}")

    # ¿Acaba de cruzar el umbral caliente?
    crossed_hot_now = score_before < HOT_THRESHOLD <= total
    if crossed_hot_now:
        print("🔥 El lead acaba de cruzar el umbral CALIENTE.")
        # 👉 Aquí SÍ mencionamos asesores de forma explícita para el canal web
        final_answer += (
            "\n\n🟢 Veo que tienes **alta intención de compra**. "
            "Si quieres, puedo derivarte con un asesor comercial de BOB Subastas "
            "para ayudarte con los siguientes pasos (ofertas, pagos, reservas, etc.). "
            "Además, en pantalla verás un pequeño formulario para que dejes tus datos "
            "y puedan contactarte. 😊"
        )

    end = perf_counter()
    response_time_ms = (end - start) * 1000.0
    print(f"⏱️ Tiempo total: {response_time_ms:.0f} ms")

    # Guardar interacción
    interaction = Interaction(
        session_id=payload.session_id,
        user_message=payload.message,
        bot_response=final_answer,
        lead_score=session_category,
        lead_score_numeric=total,
        response_time_ms=response_time_ms,
        used_context=used_context,
    )
    session.add(interaction)
    session.commit()
    print("💾 Interacción guardada correctamente en SQLite.")
    print("✅ Respuesta enviada al frontend.\n")

    result_out = {
        "answer": final_answer,
        "lead_score": session_category,
        "used_context": used_context,
        "response_time_ms": response_time_ms,
        "lead_score_numeric": total,
    }
    return ChatResponse(**result_out)
