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


def notify_advisor_new_hot_lead(
    user_waid: str,
    user_message: str,
    lead_score: str,
) -> None:
    """
    Envía un WhatsApp al asesor cuando se detecta un lead caliente.
    No lanza excepción si falta configuración, solo sale silenciosamente.
    """
    client = get_twilio_client()
    if client is None:
        # No hay configuración de Twilio, no hacemos nada
        return

    if not settings.twilio_whatsapp_from or not settings.twilio_advisor_whatsapp:
        return

    body = (
        "🚨 Nuevo lead *CALIENTE* detectado en BOB Subastas\n\n"
        f"- WhatsApp usuario: {user_waid}\n"
        f"- Mensaje inicial: {user_message}\n"
        f"- Lead score: {lead_score}\n\n"
        "Sugiero contactar a este número a la brevedad."
    )

    try:
        client.messages.create(
            from_=settings.twilio_whatsapp_from,
            to=settings.twilio_advisor_whatsapp,
            body=body,
        )
    except Exception:
        # En una demo no queremos que esto rompa el flujo del usuario,
        # así que ignoramos errores silenciosamente.
        return
