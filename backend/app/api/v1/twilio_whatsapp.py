# backend/app/api/v1/twilio_whatsapp.py
from time import perf_counter

from fastapi import APIRouter, Form, Depends
from fastapi.responses import Response
from sqlmodel import Session, select

from backend.app.rag.pipeline import RAGPipeline
from backend.app.db.session import get_session
from backend.app.db.models import Interaction, Lead
from backend.app.integrations.twilio_client import notify_advisor_new_hot_lead
from backend.app.core.lead_scoring import (
    evaluate_lead,
    total_points_to_category,
    HOT_THRESHOLD,
    FALLBACK_SCORE,  # 👈 NUEVO: para alinear el fallback con 20
)
from backend.app.core.vehicle_service import try_answer_vehicle_question  # 👈 VEHÍCULOS

router = APIRouter(
    prefix="/twilio",
    tags=["twilio-whatsapp"],
)

pipeline = RAGPipeline()


def build_conversation_text(prev_interactions: list[Interaction], new_message: str) -> str:
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


def twiml_response(message: str) -> Response:
    """
    Helper para construir la respuesta XML que Twilio espera.
    """
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{message}</Message>
</Response>
"""
    return Response(content=twiml, media_type="application/xml")


def handle_lead_data_message(
    *,
    session: Session,
    session_id: str,
    user_phone: str,
    incoming_text: str,
) -> Response:
    """
    Maneja mensajes que contienen datos del lead en formato:
    Nombres; Apellidos; DNI; Teléfono; Correo; Ciudad
    """
    print(f"📥 [WA] Intentando interpretar mensaje como datos de lead: '{incoming_text}'")

    parts = [p.strip() for p in incoming_text.split(";")]
    # Esperamos mínimo: Nombres, Apellidos, DNI, Teléfono, Correo, Ciudad (6 campos)
    if len(parts) < 5:
        msg = (
            "❌ No pude entender tus datos.\n\n"
            "Por favor envíalos en este formato (todo en un solo mensaje):\n"
            "Nombres; Apellidos; DNI; Teléfono; Correo; Ciudad"
        )
        return twiml_response(msg)

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
        return twiml_response(msg)

    # Buscamos un Lead abierto para esta sesión + canal
    lead = session.exec(
        select(Lead).where(
            (Lead.session_id == session_id)
            & (Lead.channel == "whatsapp")
            & (Lead.status == "open")
        )
    ).first()

    if not lead:
        # Si no existía, creamos uno nuevo (asumimos que es caliente,
        # porque solo pedimos datos cuando se detecta alta intención).
        lead = Lead(
            session_id=session_id,
            channel="whatsapp",
            lead_score="caliente",
            status="open",
        )

    # Actualizamos campos estándar (estilo Excel)
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
        f"✅ [WA] Datos de lead registrados/actualizados para session_id={session_id} "
        f"(ID lead={lead.id})"
    )

    # Registramos también esta interacción (como 'sistema')
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

    # Notificamos al asesor AHORA que ya tenemos los datos completos
    notify_advisor_new_hot_lead(
        user_waid=user_phone,
        user_message="Usuario compartió sus datos de contacto por WhatsApp.",
        lead_score=lead.lead_score or "caliente",
    )

    return twiml_response(confirm_msg)


@router.post("/whatsapp")
async def twilio_whatsapp_webhook(
    From: str = Form(...),   # número de WhatsApp (ej: whatsapp:+51...)
    Body: str = Form(...),   # texto del mensaje del usuario
    WaId: str = Form(None),  # id de WhatsApp (número sin prefijo 'whatsapp:')
    session: Session = Depends(get_session),
):
    """
    Webhook para recibir mensajes de WhatsApp vía Twilio.

    Prioridad:
      1) RAG con Chroma
      2) Catálogo vehículos (CSV / tabla Vehicle / API BOB)
      3) Respuesta final

    Lógica de scoring igual que en web.
    """

    # Normalizamos identificadores
    session_id = WaId or From
    user_waid = WaId or From
    raw_contact = From.strip()
    if raw_contact.startswith("whatsapp:"):
        user_phone = raw_contact[len("whatsapp:") :]
    else:
        user_phone = raw_contact

    user_message = (Body or "").strip()

    print(f"\n==============================")
    print(f"💬 [WA] Nuevo mensaje de {user_waid}: {user_message}")
    print(f"🧩 Session ID: {session_id}")
    print("==============================")

    # ---------------------------------
    # 0️⃣ ¿Mensaje con datos de contacto?
    # ---------------------------------
    # Si detectamos ';', asumimos que el usuario está intentando enviar
    # "Nombres; Apellidos; DNI; Teléfono; Correo; Ciudad"
    if ";" in user_message:
        return handle_lead_data_message(
            session=session,
            session_id=session_id,
            user_phone=user_phone,
            incoming_text=user_message,
        )

    # ---------------------------------
    # Historial de la sesión
    # ---------------------------------
    prev_interactions = session.exec(
        select(Interaction)
        .where(Interaction.session_id == session_id)
        .order_by(Interaction.created_at.asc())
    ).all()

    if prev_interactions:
        score_before = prev_interactions[-1].lead_score_numeric or 0
    else:
        score_before = 0

    print(f"📊 Score previo de sesión (WA): {score_before}")

    # Texto conversación para scoring
    conversation_text = build_conversation_text(prev_interactions, user_message)

    # ----------------------------------------
    # 1️⃣ RAG con Chroma (prioridad #1)
    # ----------------------------------------
    start = perf_counter()
    rag_result = await pipeline.answer(user_message, session_id)
    rag_answer = rag_result["answer"]
    rag_used_context = rag_result.get("used_context", False)

    print(f"📚 [WA] Contexto usado por RAG: {'Sí' if rag_used_context else 'No'}")

    final_answer = rag_answer
    used_context = rag_used_context

    # ----------------------------------------
    # 2️⃣ Si RAG no usó contexto → probar vehículos
    # ----------------------------------------
    if not rag_used_context:
        print("🚗 [WA][VEHICLE_QA] RAG no usó contexto, probando módulo de vehículos...")
        handled, vehicle_answer = try_answer_vehicle_question(
            user_message=user_message,
            session=session,
            session_id=session_id,
        )
        if handled:
            print("🚗 [WA][VEHICLE_QA] La pregunta fue respondida con datos tabulares / API BOB.")
            final_answer = vehicle_answer or ""
            used_context = False
        else:
            print("🚗 [WA][VEHICLE_QA] No aplicó vehículo/subastas, se mantiene respuesta de RAG.")

    end = perf_counter()
    response_time_ms = (end - start) * 1000.0

    # ------------------------------
    # Scoring avanzado (conversación)
    # ------------------------------
    detailed = evaluate_lead(conversation_text)

    # 👇 Igual que en el chat web: usamos FALLBACK_SCORE (20) si no hay 'total'
    total = detailed.get("total", FALLBACK_SCORE)
    try:
        total = int(total)
    except Exception:
        total = FALLBACK_SCORE

    session_category = total_points_to_category(total)  # frio/templado/caliente

    print(
        f"🏷️ [WA] Lead (detallado): "
        f"{detailed.get('categoria', 'frio').upper()} ({total} pts)"
    )
    print(f"💡 [WA] Categoría global (simple): {session_category.upper()}")

    # ¿Acaba de cruzar el umbral caliente en este mensaje?
    crossed_hot_now = score_before < HOT_THRESHOLD <= total

    if crossed_hot_now:
        # Mensaje extra al usuario → PEDIR DATOS (no registramos todavía completo)
        final_answer += (
            "\n\n🟢 Veo que tienes **alta intención de compra**. 🙌\n"
            "Para que un asesor de BOB Subastas se ponga en contacto contigo, "
            "por favor responde a este mensaje enviando tus datos en este formato "
            "(todo en un solo mensaje):\n\n"
            "Nombres; Apellidos; DNI; Teléfono; Correo; Ciudad"
        )

        # Creamos (si no existe) un lead parcial con el teléfono, para ir dejando rastro.
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
                f"🚨 [WA] Lead caliente DETECTADO (parcial) registrado: "
                f"{user_phone} (session_id={session_id})"
            )
        else:
            print(
                f"[WA] Lead ya existente para session_id={session_id}, "
                f"no se crea un duplicado (se esperarán los datos completos)."
            )

        # 🔁 IMPORTANTE: ya NO notificamos al asesor aquí.
        # La notificación se hace cuando el usuario manda sus datos
        # en handle_lead_data_message().

    # Guardar interacción en la base de datos (siempre)
    interaction = Interaction(
        session_id=session_id,
        user_message=user_message,
        bot_response=final_answer,
        lead_score=session_category,   # categoría global actual
        lead_score_numeric=total,      # score global 0-100
        response_time_ms=response_time_ms,
        used_context=used_context,
    )
    session.add(interaction)
    session.commit()
    print(f"💾 [WA] Interacción guardada. Score actual: {total} ({session_category})")

    # Twilio espera una respuesta en TwiML
    return twiml_response(final_answer)
