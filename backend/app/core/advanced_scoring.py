import json
from pathlib import Path
import google.generativeai as genai
from backend.app.core.config import get_settings

settings = get_settings()

if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)
else:
    print("⚠️ Advertencia: GEMINI_API_KEY no configurada. El scoring avanzado no funcionará.")

def evaluate_lead_detailed(message: str) -> dict:
    """
    Evalúa el mensaje del usuario según los criterios definidos en data/CRITERIOS_DE_SCORE.txt.
    Devuelve un dict con puntaje total, categoría y desglose.
    """
    # Ruta al archivo de criterios
    criteria_path = Path("data/CRITERIOS_DE_SCORE.txt")

    if not criteria_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de criterios: {criteria_path}")

    # Leer el texto completo de criterios
    system_prompt = criteria_path.read_text(encoding="utf-8")

    # Añadir instrucciones fijas al final
    system_prompt += """
    
Devuelve SOLO un JSON con este formato:
{
  "perfil_demografico": int,
  "comportamiento_digital": int,
  "capacidad_financiera": int,
  "necesidad_urgencia": int,
  "experiencia_previa": int,
  "engagement_actual": int,
  "contexto_compra": int,
  "boosts": int,
  "penalizaciones": int,
  "total": int,
  "categoria": "frio" | "tibio" | "caliente" | "descartado"
}
    """

    # Prompt final
    prompt = f"{system_prompt}\n\nMENSAJE DEL USUARIO:\n{message}"

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)

    try:
        data = json.loads(response.text)
    except Exception:
        print("⚠️ Gemini no devolvió JSON válido. Fallback a score neutral.")
        data = {"total": 50, "categoria": "frio"}

    return data
