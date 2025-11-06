import requests

BOB_API_URL = "https://apiv3.somosbob.com/v3/sublots/details"

def get_live_sublots():
    """Obtiene información en tiempo real de las subastas de BOB."""
    try:
        print("🌐 [BOB API] Consultando sublotes en tiempo real...")
        response = requests.get(BOB_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"✅ [BOB API] {len(data)} registros obtenidos.")
        return data
    except requests.exceptions.RequestException as e:
        print(f"⚠️ [BOB API] Error al conectar con la API: {e}")
        return []

def format_sublot_summary(s):
    """
    Formatea un sublote en texto legible para respuestas del chatbot.
    """
    return (
        f"**{s.get('title', 'Lote sin título')}** "
        f"({s.get('brand', 'Sin marca')})\n"
        f"{s.get('basePriceFormatted', 'Sin precio')} | "
        f"{s.get('location', 'Sin ubicación')} | "
        f"{s.get('company', {}).get('name', 'Sin empresa')}\n"
        f"[Ver más]({s.get('link', 'https://somosbob.com')})"
    )