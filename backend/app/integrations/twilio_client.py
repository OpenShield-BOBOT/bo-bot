# backend/app/integrations/twilio_client.py

from typing import Optional

from twilio.rest import Client

from backend.app.core.config import get_settings

settings = get_settings()


def get_twilio_client() -> Optional[Client]:
    """
    Crea un cliente de Twilio solo si hay credenciales configuradas.
    """
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return None
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _format_whatsapp_number(phone: str) -> str:
    """
    Normaliza el número al formato que espera Twilio:
      - Si ya viene como 'whatsapp:+51...', lo deja igual.
      - Si viene como '+51...' o '5199...', le agrega el prefijo 'whatsapp:'.
    """
    if not phone:
        return phone
    phone = phone.strip()
    if phone.startswith("whatsapp:"):
        return phone
    return f"whatsapp:{phone}"


def send_whatsapp_message(*, to_number: str, body: str) -> None:
    """
    Envía un mensaje de WhatsApp usando la API de Twilio.
    Se usa tanto para responder al usuario final como para notificar al asesor.

    No lanza excepción si falta configuración; solo loguea y termina.
    """
    client = get_twilio_client()
    if client is None:
        # No hay configuración de Twilio, no hacemos nada
        print("[Twilio] twilio_account_sid / twilio_auth_token no configurados. No se envía mensaje.")
        return

    if not settings.twilio_whatsapp_from:
        print("[Twilio] twilio_whatsapp_from no configurado. No se envía mensaje.")
        return

    if not to_number:
        print("[Twilio] Número de destino vacío. No se envía mensaje.")
        return

    to = _format_whatsapp_number(to_number)
    from_ = settings.twilio_whatsapp_from

    try:
        print(f"📨 [Twilio] Enviando WhatsApp\n  From: {from_}\n  To:   {to}\n  Body: {body[:120]}...")
        client.messages.create(
            from_=from_,
            to=to,
            body=body,
        )
    except Exception as e:
        # En demo / dev no queremos que esto rompa nada.
        print(f"⚠️ [Twilio] Error enviando WhatsApp a {to}: {e}")
        return


def notify_advisor_new_hot_lead(
    user_waid: str,
    user_message: str,
    lead_score: str,
) -> None:
    """
    Envía un WhatsApp al asesor cuando se detecta un lead caliente.
    No lanza excepción si falta configuración, solo sale silenciosamente.
    """
    if not settings.twilio_advisor_whatsapp:
        # No hay número de asesor configurado
        return

    body = (
        "🚨 Nuevo lead *CALIENTE* detectado en BOB Subastas\n\n"
        f"- WhatsApp usuario: {user_waid}\n"
        f"- Mensaje inicial: {user_message}\n"
        f"- Lead score: {lead_score}\n\n"
        "Sugiero contactar a este número a la brevedad."
    )

    # Reutilizamos el helper genérico
    send_whatsapp_message(
        to_number=settings.twilio_advisor_whatsapp,
        body=body,
    )
