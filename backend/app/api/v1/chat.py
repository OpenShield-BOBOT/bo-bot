from time import perf_counter
import re  # 👈 ya lo tenías
from datetime import datetime, timedelta

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
    FALLBACK_SCORE,
)

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)

pipeline = RAGPipeline()

SESSION_TIMEOUT_MINUTES_WEB = 2



def strip_simple_markdown(text: str) -> str:
    """
    Limpia el Markdown básico para que el frontend (Angular) reciba texto plano.
    - Quita **negritas**, *cursivas* y _cursivas_
    - Convierte bullets tipo '* ' o '- ' al inicio de línea en '- '
    - Convierte links [texto](url) en solo 'texto'
    """
    if not text:
        return text

    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)

    text = re.sub(r"_(.+?)_", r"\1", text)

    text = re.sub(r"(?<!\S)\*(?!\s)(.+?)(?<!\s)\*(?!\S)", r"\1", text)

    text = re.sub(r"^\s*[\*\-]\s+", "- ", text, flags=re.MULTILINE)

    return text.strip()


def build_conversation_text(prev_interactions: list[Interaction], new_message: str) -> str:
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
    msg = (new_message or "").strip().lower()
    if not msg:
        return False

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
        "llámenme",
        "llamame",
        "contactarme",
        "asesor comercial",
    ]
    if any(p in msg for p in direct_phrases):
        return True

    if prev_interactions:
        last_bot_resp = prev_interactions[-1].bot_response or ""
        last_bot_lower = last_bot_resp.lower()

        if any(
            kw in last_bot_lower
            for kw in ["asesor", "que te contacten", "que te contactemos", "derivarte con un asesor"]
        ):
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
            if len(msg) <= 30 and any(a in msg for a in short_affirmatives):
                return True

    return False


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    payload: ChatMessage,
    session: Session = Depends(get_session),
) -> ChatResponse:
    print("\n==============================")
    print(f"💬 [NUEVO MENSAJE] Usuario → {payload.message}")
    print(f"🧩 Session ID: {payload.session_id}")
    print("==============================")

    start = perf_counter()

    prev_interactions = session.exec(
        select(Interaction)
        .where(Interaction.session_id == payload.session_id)
        .order_by(Interaction.created_at.asc())
    ).all()

    now = datetime.utcnow()

    if prev_interactions:
        last_ts = prev_interactions[-1].created_at
        if last_ts and (now - last_ts) > timedelta(minutes=SESSION_TIMEOUT_MINUTES_WEB):
            print("⏲️ [WEB] Sesión expirada por inactividad, reseteando historial.")
            prev_interactions = []
            score_before = 0
        else:
            score_before = prev_interactions[-1].lead_score_numeric or 0
    else:
        score_before = 0

    print(f"📊 Score previo de sesión: {score_before}")

    conversation_text = build_conversation_text(prev_interactions, payload.message)

    user_wants_advisor = user_clearly_requests_advisor(prev_interactions, payload.message)
    print(f"📞 ¿Usuario pidió asesor explícitamente? → {'sí' if user_wants_advisor else 'no'}")

    print("🤖 [PIPELINE] Ejecutando RAG con Gemini...")

    chat_history = []
    for it in prev_interactions[-3:]:
        if it.user_message:
            chat_history.append({"role": "user", "content": it.user_message})
        if it.bot_response:
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
            used_context = False
        else:
            print("🚗 [VEHICLE_QA] No aplicó vehículo/subastas, se mantiene respuesta de RAG.")

    detailed = evaluate_lead(conversation_text)

    total = detailed.get("total", FALLBACK_SCORE)
    try:
        total = int(total)
    except Exception:
        total = FALLBACK_SCORE

    session_category = total_points_to_category(total)

    if user_wants_advisor and total < HOT_THRESHOLD:
        print(
            "📞 El usuario ha solicitado contacto con un asesor. "
            "Forzamos score CALIENTE para esta sesión."
        )
        total = HOT_THRESHOLD
        session_category = "caliente"

    print(f"🏷️ Lead (detallado): {detailed.get('categoria', 'frio').upper()} ({total} pts)")
    print(f"💡 Categoría global (simple): {session_category.upper()}")

    crossed_hot_now = score_before < HOT_THRESHOLD <= total
    if crossed_hot_now:
        print("🔥 El lead acaba de cruzar el umbral CALIENTE.")
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

    clean_answer = strip_simple_markdown(final_answer)

    interaction = Interaction(
        session_id=payload.session_id,
        user_message=payload.message,
        bot_response=clean_answer,
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
        "answer": clean_answer,
        "lead_score": session_category,
        "used_context": used_context,
        "response_time_ms": response_time_ms,
        "lead_score_numeric": total,
    }
    return ChatResponse(**result_out)
