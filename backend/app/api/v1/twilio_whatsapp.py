from time import perf_counter

from fastapi import APIRouter, Form, Depends
from fastapi.responses import Response
from sqlmodel import Session, select

from backend.app.rag.pipeline import RAGPipeline
from backend.app.db.session import get_session
from backend.app.db.models import Interaction, Lead
from backend.app.integrations.twilio_client import notify_advisor_new_hot_lead
from backend.app.core.lead_scoring import (
    category_to_points,
    total_points_to_category,
    HOT_THRESHOLD,
)

router = APIRouter(
    prefix="/twilio",
    tags=["twilio-whatsapp"],
)

pipeline = RAGPipeline()


@router.post("/whatsapp")
async def twilio_whatsapp_webhook(
    From: str = Form(...),   # número de WhatsApp (ej: whatsapp:+51...)
    Body: str = Form(...),   # texto del mensaje del usuario
    WaId: str = Form(None),  # id de WhatsApp (número sin prefijo 'whatsapp:')
    session: Session = Depends(get_session),
):
    """
    Webhook para recibir mensajes de WhatsApp vía Twilio.

    Lógica de scoring:
    - Cada mensaje se clasifica (frio/templado/caliente) por IA.
    - Esa etiqueta se traduce a puntos y se suma al score acumulado de la sesión.
    - Cuando el score cruzA HOT_THRESHOLD, el bot:
        * Le dice al usuario que tiene alta intención de compra.
        * Notifica al asesor.
        * Crea un Lead en la tabla Lead (canal='whatsapp') si no existía.
    """
    # Definir un session_id estable por usuario de WhatsApp
    session_id = WaId or From
    user_waid = WaId or From
    user_message = Body.strip()

    # Medir tiempo de respuesta
    start = perf_counter()
    result = await pipeline.answer(user_message, session_id)
    end = perf_counter()
    response_time_ms = (end - start) * 1000.0

    # Resultado del pipeline (lead_score = etiqueta del MENSAJE)
    answer = result["answer"]
    message_label = (result.get("lead_score") or "frio").lower()
    used_context = result.get("used_context", False)

    # 1️⃣ Puntos que aporta este mensaje
    message_points = category_to_points(message_label)

    # 2️⃣ Score acumulado previo de la sesión (sumando interacciones anteriores)
    prev_interactions = session.exec(
        select(Interaction).where(Interaction.session_id == session_id)
    ).all()
    score_before = sum(i.lead_score_numeric or 0 for i in prev_interactions)

    # 3️⃣ Score nuevo de la sesión
    score_after = score_before + message_points

    # 4️⃣ Categoría global de la SESIÓN según el acumulado
    session_category = total_points_to_category(score_after)  # frio/templado/caliente

    # 5️⃣ ¿Acaba de cruzar el umbral caliente en este mensaje?
    crossed_hot_now = score_before < HOT_THRESHOLD <= score_after

    if crossed_hot_now:
        # Mensaje extra al usuario
        answer += (
            "\n\n🟢 Veo que tienes **alta intención de compra**. "
            "Un asesor de BOB Subastas se pondrá en contacto contigo "
            "por este mismo número para ayudarte con los siguientes pasos."
        )

        # Notificar al asesor (si Twilio está configurado)
        notify_advisor_new_hot_lead(
            user_waid=user_waid,
            user_message=user_message,
            lead_score=session_category,  # ahora es el score de la SESIÓN
        )

        # Crear Lead en la BD si no existe uno abierto para esta sesión/canal
        contact = user_waid
        if contact.startswith("whatsapp:"):
            contact = contact[len("whatsapp:") :]

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
                name=None,                # no tenemos nombre desde Twilio
                contact=contact,          # número limpio
                lead_score=session_category,  # normalmente "caliente"
                status="open",
            )
            session.add(new_lead)
            print(
                f"🚨 Nuevo lead CALIENTE (WhatsApp) registrado: "
                f"{contact} (session_id={session_id})"
            )
        else:
            print(
                f"Lead de WhatsApp ya existente para session_id={session_id}, "
                f"no se crea un duplicado."
            )

    # 6️⃣ Guardar interacción en la base de datos (siempre)
    interaction = Interaction(
        session_id=session_id,
        user_message=user_message,
        bot_response=answer,
        lead_score=message_label,          # etiqueta del MENSAJE
        lead_score_numeric=message_points, # puntos que aportó este mensaje
        response_time_ms=response_time_ms,
        used_context=used_context,
    )
    session.add(interaction)
    session.commit()

    # 7️⃣ Twilio espera una respuesta en TwiML (XML simple)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{answer}</Message>
</Response>
"""

    return Response(content=twiml, media_type="application/xml")
