from time import perf_counter
from typing import List
import time  # 👈 NUEVO
from datetime import datetime, timedelta

from fastapi import APIRouter, Form, BackgroundTasks
from fastapi.responses import Response
from sqlmodel import Session, select

from backend.app.rag.pipeline import RAGPipeline
from backend.app.db.session import engine
from backend.app.db.models import Interaction, Lead
from backend.app.integrations.twilio_client import (
    notify_advisor_new_hot_lead,
    send_whatsapp_message,
)
from backend.app.core.lead_scoring import (
    evaluate_lead,
    total_points_to_category,
    HOT_THRESHOLD,
    FALLBACK_SCORE,
)
from backend.app.core.vehicle_service import try_answer_vehicle_question

router = APIRouter(
    prefix="/twilio",
    tags=["twilio-whatsapp"],
)

pipeline = RAGPipeline()

SESSION_TIMEOUT_MINUTES_WA = 30


def build_conversation_text(prev_interactions: List[Interaction], new_message: str) -> str:
    user_msgs: list[str] = []

    for it in prev_interactions:
        if it.user_message:
            user_msgs.append(f"Usuario: {it.user_message}")

    user_msgs.append(f"Usuario: {new_message}")

    conversation_text = "\n".join(user_msgs)
    print("🧾 [WA] Texto de conversación enviado a scoring:")
    print(conversation_text)
    return conversation_text


def user_clearly_requests_advisor_wa(
    prev_interactions: List[Interaction],
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
        "llámame",
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
            for kw in ["asesor", "que un asesor", "que te contacte", "que se ponga en contacto"]
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
            if len(msg) <= 40 and any(a in msg for a in short_affirmatives):
                return True

    return False


def inactivity_ping_task(
    *,
    session_id: str,
    user_phone: str,
    scheduled_at_iso: str,
    wait_seconds: int = 120,
) -> None:
    """
    Espera X segundos y, si el usuario NO ha enviado ningún mensaje nuevo
    desde `scheduled_at`, le manda un ping de '¿sigues ahí?'.
    """
    print(
        f"⏲️ [WA] (BG) Programando ping de inactividad para {user_phone} "
        f"en {wait_seconds} segundos..."
    )

    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_iso)
    except Exception:
        scheduled_at = datetime.utcnow()

    time.sleep(wait_seconds)

    with Session(engine) as session:
        last_user_msg = session.exec(
            select(Interaction)
            .where(
                (Interaction.session_id == session_id)
                & (Interaction.user_message != None)
                & (Interaction.created_at > scheduled_at)
            )
            .order_by(Interaction.created_at.desc())
        ).first()

        if last_user_msg:
            print("✅ [WA] (BG) El usuario respondió, no enviamos ping de inactividad.")
            return

    ping_text = (
        "👋 Solo quería confirmar si sigues por aquí.\n\n"
        "Si aún necesitas ayuda con las subastas o los vehículos de BOB Subastas, "
        "puedes escribirme y seguimos 😉"
    )
    send_whatsapp_message(
        to_number=user_phone,
        body=ping_text,
    )
    print(f"📨 [WA] (BG) Ping de inactividad enviado a {user_phone}.")


def process_lead_data_message_bg(
    *,
    session_id: str,
    user_phone: str,
    incoming_text: str,
) -> None:
    print(f"📥 [WA] (BG) Intentando interpretar mensaje como datos de lead: '{incoming_text}'")

    parts = [p.strip() for p in incoming_text.split(";")]
    if len(parts) < 5:
        msg = (
            "❌ No pude entender tus datos.\n\n"
            "Por favor envíalos en este formato (todo en un solo mensaje):\n"
            "Nombres; Apellidos; DNI; Teléfono; Correo; Ciudad"
        )
        print("⚠️ [WA] Datos incompletos para lead, respondiendo al usuario.")
        send_whatsapp_message(
            to_number=user_phone,
            body=msg,
        )
        return

    nombres = parts[0] or None
    apellidos = parts[1] if len(parts) > 1 else None
    dni = parts[2] if len(parts) > 2 else None
    telefono = parts[3] if len(parts) > 3 else None
    correo = parts[4] if len(parts) > 4 else None
    ciudad = parts[5] if len(parts) > 5 else None

    errores: list[str] = []
    if not nombres:
        errores.append("Debes indicar tus nombres.")
    if not apellidos:
        errores.append("Debes indicar tus apellidos.")
    if not telefono:
        errores.append("Debes indicar tu teléfono.")
    if not correo or "@" not in correo:
        errores.append("El correo electrónico no parece válido.")
    if not ciudad:
        errores.append("Debes indicar tu ciudad.")

    if errores:
        msg = (
            "❌ Hay algunos problemas con tus datos:\n- "
            + "\n- ".join(errores)
            + "\n\nEnvíalos de nuevo en el formato:\n"
            "Nombres; Apellidos; DNI; Teléfono; Correo; Ciudad"
        )
        print("⚠️ [WA] Errores en datos de lead, respondiendo al usuario.")
        send_whatsapp_message(
            to_number=user_phone,
            body=msg,
        )
        return

    with Session(engine) as session:
        lead = session.exec(
            select(Lead).where(
                (Lead.session_id == session_id)
                & (Lead.channel == "whatsapp")
                & (Lead.status == "open")
            )
        ).first()

        if not lead:
            lead = Lead(
                session_id=session_id,
                channel="whatsapp",
                lead_score="caliente",
                status="open",
            )

        lead.nombres = nombres
        lead.apellidos = apellidos
        lead.dni = dni
        lead.telefono = telefono or user_phone
        lead.correo_electronico = correo
        lead.ciudad = ciudad

        if not lead.lead_score:
            lead.lead_score = "caliente"

        session.add(lead)
        session.commit()
        session.refresh(lead)

        print(
            f"✅ [WA] (BG) Datos de lead registrados/actualizados para session_id={session_id} "
            f"(ID lead={lead.id})"
        )

        confirm_msg = (
            "✅ Perfecto, ya registré tus datos.\n"
            "Un asesor de BOB Subastas se pondrá en contacto contigo en breve. 🙌"
        )

        interaction = Interaction(
            session_id=session_id,
            user_message=incoming_text,
            bot_response=confirm_msg,
            lead_score=lead.lead_score,
            lead_score_numeric=None,
            response_time_ms=None,
            used_context=False,
        )
        session.add(interaction)
        session.commit()

    notify_advisor_new_hot_lead(
        user_waid=user_phone,
        user_message="Usuario compartió sus datos de contacto por WhatsApp.",
        lead_score=lead.lead_score or "caliente",
    )

    send_whatsapp_message(
        to_number=user_phone,
        body=confirm_msg,
    )
    print("📨 [WA] (BG) Mensaje de confirmación enviado al usuario.")


def process_normal_message_bg(
    *,
    session_id: str,
    user_phone: str,
    user_message: str,
) -> None:
    print(f"\n🧵 [WA] (BG) Procesando mensaje: {user_message} (session_id={session_id})")
    start = perf_counter()

    with Session(engine) as session:
        prev_interactions = session.exec(
            select(Interaction)
            .where(Interaction.session_id == session_id)
            .order_by(Interaction.created_at.asc())
        ).all()

        now = datetime.utcnow()

        if prev_interactions:
            last_ts = prev_interactions[-1].created_at
            if last_ts and (now - last_ts) > timedelta(minutes=SESSION_TIMEOUT_MINUTES_WA):
                print("⏲️ [WA] Sesión expirada por inactividad, reseteando historial.")
                prev_interactions = []
                score_before = 0
            else:
                score_before = prev_interactions[-1].lead_score_numeric or 0
        else:
            score_before = 0

        print(f"📊 [WA] (BG) Score previo de sesión: {score_before}")

        conversation_text = build_conversation_text(prev_interactions, user_message)

        user_wants_advisor = user_clearly_requests_advisor_wa(prev_interactions, user_message)
        print(f"📞 [WA] (BG) ¿Usuario pidió asesor explícitamente? → {'sí' if user_wants_advisor else 'no'}")

        from anyio import run as anyio_run

        chat_history = []
        for it in prev_interactions[-3:]:
            if it.user_message:
                chat_history.append({"role": "user", "content": it.user_message})
            if it.bot_response:
                chat_history.append({"role": "assistant", "content": it.bot_response})

        async def _run_rag():
            return await pipeline.answer(
                question=user_message,
                session_id=session_id,
                chat_history=chat_history,
            )

        rag_result = anyio_run(_run_rag)

        rag_answer = rag_result["answer"]
        rag_used_context = rag_result.get("used_context", False)

        print(f"📚 [WA] (BG) Contexto usado por RAG: {'Sí' if rag_used_context else 'No'}")

        final_answer = rag_answer
        used_context = rag_used_context

        if not rag_used_context:
            print("🚗 [WA][VEHICLE_QA] (BG) RAG no usó contexto, probando módulo de vehículos...")
            handled, vehicle_answer = try_answer_vehicle_question(
                user_message=user_message,
                session=session,
                session_id=session_id,
            )
            if handled:
                print("🚗 [WA][VEHICLE_QA] (BG) Pregunta respondida con datos tabulares / API BOB.")
                final_answer = vehicle_answer or ""
                used_context = False
            else:
                print("🚗 [WA][VEHICLE_QA] (BG) No aplicó vehículo/subastas, se mantiene respuesta de RAG.")

        detailed = evaluate_lead(conversation_text)
        total = detailed.get("total", FALLBACK_SCORE)
        try:
            total = int(total)
        except Exception:
            total = FALLBACK_SCORE

        session_category = total_points_to_category(total)

        if user_wants_advisor and total < HOT_THRESHOLD:
            print(
                "📞 [WA] (BG) El usuario ha solicitado contacto con un asesor. "
                "Forzamos score CALIENTE para esta sesión."
            )
            total = HOT_THRESHOLD
            session_category = "caliente"

        print(
            f"🏷️ [WA] (BG) Lead (detallado): "
            f"{detailed.get('categoria', 'frio').upper()} ({total} pts)"
        )
        print(f"💡 [WA] (BG) Categoría global (simple): {session_category.upper()}")

        crossed_hot_now = score_before < HOT_THRESHOLD <= total

        if crossed_hot_now:
            final_answer += (
                "\n\n🟢 Veo que tienes **alta intención de compra**. 🙌\n"
                "Para que un asesor de BOB Subastas se ponga en contacto contigo, "
                "por favor responde a este mensaje enviando tus datos en este formato "
                "(todo en un solo mensaje):\n\n"
                "Nombres; Apellidos; DNI; Teléfono; Correo; Ciudad"
            )

            existing_lead = session.exec(
                select(Lead).where(
                    (Lead.session_id == session_id)
                    & (Lead.channel == "whatsapp")
                    & (Lead.status == "open")
                )
            ).first()

            if not existing_lead:
                new_lead = Lead(
                    session_id=session_id,
                    channel="whatsapp",
                    telefono=user_phone,
                    lead_score=session_category,
                    status="open",
                )
                session.add(new_lead)
                print(
                    f"🚨 [WA] (BG) Lead caliente DETECTADO (parcial) registrado: "
                    f"{user_phone} (session_id={session_id})"
                )
            else:
                print(
                    f"[WA] (BG) Lead ya existente para session_id={session_id}, "
                    f"no se crea un duplicado (se esperarán los datos completos)."
                )

        end = perf_counter()
        response_time_ms = (end - start) * 1000.0
        print(f"⏱️ [WA] (BG) Tiempo total de procesamiento: {response_time_ms:.0f} ms")

        if not final_answer or not final_answer.strip():
            print("⚠️ [WA] (BG) final_answer llegó vacío, aplicando mensaje de fallback.")
            final_answer = (
                "Ups, tuve un problema para generar la respuesta esta vez. "
                "Recuerda que soy BOBot, el chatbot oficial de BOB Subastas. "
                "¿Me puedes repetir tu consulta o formularla de otra manera?"
            )

        interaction = Interaction(
            session_id=session_id,
            user_message=user_message,
            bot_response=final_answer,
            lead_score=session_category,
            lead_score_numeric=total,
            response_time_ms=response_time_ms,
            used_context=used_context,
        )
        session.add(interaction)
        session.commit()
        print(f"💾 [WA] (BG) Interacción guardada. Score actual: {total} ({session_category})")

    send_whatsapp_message(
        to_number=user_phone,
        body=final_answer,
    )
    print(f"📨 [WA] (BG) Mensaje enviado al usuario {user_phone} vía API de Twilio.")


@router.post("/whatsapp")
async def twilio_whatsapp_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(...),
    WaId: str = Form(None),
):
    session_id = WaId or From
    raw_contact = From.strip()
    if raw_contact.startswith("whatsapp:"):
        user_phone = raw_contact[len("whatsapp:"):]
    else:
        user_phone = raw_contact

    user_message = (Body or "").strip()

    print(f"\n==============================")
    print(f"💬 [WA] Nuevo mensaje de {user_phone}: {user_message}")
    print(f"🧩 Session ID: {session_id}")
    print("==============================")

    if ";" in user_message:
        background_tasks.add_task(
            process_lead_data_message_bg,
            session_id=session_id,
            user_phone=user_phone,
            incoming_text=user_message,
        )
    else:
        background_tasks.add_task(
            process_normal_message_bg,
            session_id=session_id,
            user_phone=user_phone,
            user_message=user_message,
        )

        now_iso = datetime.utcnow().isoformat()
        background_tasks.add_task(
            inactivity_ping_task,
            session_id=session_id,
            user_phone=user_phone,
            scheduled_at_iso=now_iso,
            wait_seconds=120,
        )

    return Response(content="", status_code=202)
