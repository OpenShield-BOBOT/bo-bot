# backend/app/api/v1/twilio_whatsapp.py
from time import perf_counter
from typing import List

from fastapi import APIRouter, Form, BackgroundTasks
from fastapi.responses import Response
from sqlmodel import Session, select

from backend.app.rag.pipeline import RAGPipeline
from backend.app.db.session import engine  # usamos engine para crear Session
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
from backend.app.core.vehicle_service import try_answer_vehicle_question  # 👈 VEHÍCULOS

router = APIRouter(
    prefix="/twilio",
    tags=["twilio-whatsapp"],
)

pipeline = RAGPipeline()


# =====================================================
# 🧱 Helpers comunes
# =====================================================
def build_conversation_text(prev_interactions: List[Interaction], new_message: str) -> str:
    """
    Construye un texto con TODOS los mensajes del usuario en la sesión
    (solo usuario), más el mensaje actual.
    """
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
    """
    Detecta si el usuario está pidiendo explícitamente hablar con un asesor
    o si está respondiendo afirmativamente a una oferta de asesor del bot.
    """
    msg = (new_message or "").strip().lower()
    if not msg:
        return False

    # 1) Frases directas de solicitud de asesor/contacto
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

    # 2) Confirmación corta después de una oferta de asesor del bot
    if prev_interactions:
        last_bot_resp = prev_interactions[-1].bot_response or ""
        last_bot_lower = last_bot_resp.lower()

        # ¿El bot habló de asesor/contacto en el último mensaje?
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


# =============================================
# 🧵 Tarea background: datos de lead por WhatsApp
# =============================================
def process_lead_data_message_bg(
    *,
    session_id: str,
    user_phone: str,
    incoming_text: str,
) -> None:
    """
    Versión en background de lo que antes hacía handle_lead_data_message.
    Ahora NO devolvemos TwiML; enviamos mensaje con la API de Twilio.
    """
    print(f"📥 [WA] (BG) Intentando interpretar mensaje como datos de lead: '{incoming_text}'")

    parts = [p.strip() for p in incoming_text.split(";")]
    # Esperamos mínimo: Nombres, Apellidos, DNI, Teléfono, Correo, Ciudad (6 campos)
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

    # A partir de aquí ya necesitamos BD
    with Session(engine) as session:
        # Buscamos un Lead abierto para esta sesión + canal
        lead = session.exec(
            select(Lead).where(
                (Lead.session_id == session_id)
                & (Lead.channel == "whatsapp")
                & (Lead.status == "open")
            )
        ).first()

        if not lead:
            # Si no existía, creamos uno nuevo (asumimos que es caliente)
            lead = Lead(
                session_id=session_id,
                channel="whatsapp",
                lead_score="caliente",
                status="open",
            )

        # Actualizamos campos estándar
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

        # Guardamos interacción
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

    # Notificamos al asesor AHORA que ya tenemos los datos completos
    notify_advisor_new_hot_lead(
        user_waid=user_phone,
        user_message="Usuario compartió sus datos de contacto por WhatsApp.",
        lead_score=lead.lead_score or "caliente",
    )

    # Respondemos al usuario vía API de Twilio
    send_whatsapp_message(
        to_number=user_phone,
        body=confirm_msg,
    )
    print("📨 [WA] (BG) Mensaje de confirmación enviado al usuario.")


# ===========================================
# 🧵 Tarea background: flujo normal del bot
# ===========================================
def process_normal_message_bg(
    *,
    session_id: str,
    user_phone: str,
    user_message: str,
) -> None:
    """
    Procesa en background el mensaje normal:
      - carga historial
      - RAG + módulo vehículos
      - scoring
      - posible solicitud de datos
      - guarda interacción
      - envía respuesta vía Twilio API
    """
    print(f"\n🧵 [WA] (BG) Procesando mensaje: {user_message} (session_id={session_id})")
    start = perf_counter()

    with Session(engine) as session:
        # Historial de la sesión
        prev_interactions = session.exec(
            select(Interaction)
            .where(Interaction.session_id == session_id)
            .order_by(Interaction.created_at.asc())
        ).all()

        if prev_interactions:
            score_before = prev_interactions[-1].lead_score_numeric or 0
        else:
            score_before = 0

        print(f"📊 [WA] (BG) Score previo de sesión: {score_before}")

        # Texto conversación completo para scoring
        conversation_text = build_conversation_text(prev_interactions, user_message)

        # Flag: ¿el usuario pidió claramente un asesor?
        user_wants_advisor = user_clearly_requests_advisor_wa(prev_interactions, user_message)
        print(f"📞 [WA] (BG) ¿Usuario pidió asesor explícitamente? → {'sí' if user_wants_advisor else 'no'}")

        # 1️⃣ RAG con Chroma (llamamos async desde sync con anyio)
        from anyio import run as anyio_run

        # Historial reducido para el LLM (últimos 3 turnos)
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

        # 2️⃣ Si RAG no usó contexto → probar vehículos
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

        # 3️⃣ Scoring avanzado (conversación)
        detailed = evaluate_lead(conversation_text)
        total = detailed.get("total", FALLBACK_SCORE)
        try:
            total = int(total)
        except Exception:
            total = FALLBACK_SCORE

        session_category = total_points_to_category(total)

        # Si el usuario PIDE asesor explícitamente, forzamos score caliente
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

        # ¿Acaba de cruzar el umbral caliente en este mensaje?
        crossed_hot_now = score_before < HOT_THRESHOLD <= total

        if crossed_hot_now:
            final_answer += (
                "\n\n🟢 Veo que tienes **alta intención de compra**. 🙌\n"
                "Para que un asesor de BOB Subastas se ponga en contacto contigo, "
                "por favor responde a este mensaje enviando tus datos en este formato "
                "(todo en un solo mensaje):\n\n"
                "Nombres; Apellidos; DNI; Teléfono; Correo; Ciudad"
            )

            # Lead parcial
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

        # Fallback: nunca mandar respuesta vacía
        if not final_answer or not final_answer.strip():
            print("⚠️ [WA] (BG) final_answer llegó vacío, aplicando mensaje de fallback.")
            final_answer = (
                "Ups, tuve un problema para generar la respuesta esta vez. "
                "Recuerda que soy BOBot, el chatbot oficial de BOB Subastas. "
                "¿Me puedes repetir tu consulta o formularla de otra manera?"
            )

        # Guardar interacción en la BD
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

    # Por último, respondemos al usuario por la API de Twilio
    send_whatsapp_message(
        to_number=user_phone,
        body=final_answer,
    )
    print(f"📨 [WA] (BG) Mensaje enviado al usuario {user_phone} vía API de Twilio.")


# ===========================================
# 🌐 WEBHOOK: súper ligero (Twilio-friendly)
# ===========================================
@router.post("/whatsapp")
async def twilio_whatsapp_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),   # número de WhatsApp (ej: whatsapp:+51...)
    Body: str = Form(...),   # texto del mensaje del usuario
    WaId: str = Form(None),  # id de WhatsApp (número sin prefijo 'whatsapp:')
):
    """
    Webhook para recibir mensajes de WhatsApp vía Twilio.

    AHORA:
      - NO hace RAG ni scoring ni acceso pesado a BD.
      - Solo normaliza datos, decide tipo de mensaje
        y lanza tareas en background.
      - Responde rápido a Twilio con un 202 vacío.
    """

    # Normalizamos identificadores
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

    # 0️⃣ Si detectamos ';', asumimos que son datos de contacto
    if ";" in user_message:
        background_tasks.add_task(
            process_lead_data_message_bg,
            session_id=session_id,
            user_phone=user_phone,
            incoming_text=user_message,
        )
    else:
        # 1️⃣ Lanzamos el flujo normal del bot en background
        background_tasks.add_task(
            process_normal_message_bg,
            session_id=session_id,
            user_phone=user_phone,
            user_message=user_message,
        )

    # 2️⃣ Twilio queda feliz: respondemos rápido sin TwiML
    return Response(content="", status_code=202)
