import json
from pathlib import Path
import google.generativeai as genai
from backend.app.core.config import get_settings

settings = get_settings()

# ==============================
# 🔧 CONFIGURACIÓN DE GEMINI
# ==============================
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)
else:
    print("⚠️ Advertencia: GEMINI_API_KEY no configurada. El scoring avanzado no funcionará.")


# ==============================
# 🧠 FUNCIÓN PRINCIPAL DE EVALUACIÓN
# ==============================
def evaluate_lead_detailed(message: str) -> dict:
    """
    Evalúa el mensaje del usuario según los criterios definidos en data/CRITERIOS_DE_SCORE.txt.
    Devuelve un dict con puntaje total, categoría y desglose.
    """
    print("\n------------------------------------")
    print("📊 [SCORING] Iniciando evaluación detallada del lead...")
    print(f"🗨️ Mensaje del usuario: {message}")

    # Ruta al archivo de criterios
    criteria_path = Path("data/CRITERIOS_DE_SCORE.txt")

    if not criteria_path.exists():
        raise FileNotFoundError(f"❌ No se encontró el archivo de criterios: {criteria_path}")

    # Leer criterios del archivo
    system_prompt = criteria_path.read_text(encoding="utf-8")
    print(f"📁 Criterios cargados desde: {criteria_path.name}")

    # Añadir instrucciones fijas al final
    system_prompt += """
    
Asegúrate de devolver EXCLUSIVAMENTE un JSON válido, sin texto adicional ni explicaciones.
Si no puedes evaluar, devuelve:
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

    print("🤖 [Gemini] Enviando mensaje para evaluación avanzada...")

    model = genai.GenerativeModel("gemini-2.5-flash")

    try:
        response = model.generate_content(prompt)
        raw_text = (response.text or "").strip()
        print("✅ [Gemini] Respuesta recibida correctamente.")
    except Exception as e:
        print(f"⚠️ [Gemini] Error durante la evaluación: {e}")
        print("🟡 Fallback → asignando score neutral.")
        return {"total": 50, "categoria": "frio"}

    # Intentar decodificar el JSON
    try:
        data = json.loads(raw_text)
        print("📦 JSON recibido desde Gemini:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"⚠️ No se pudo interpretar el JSON de Gemini: {e}")
        print("🟡 Fallback → asignando score neutral.")
        data = {"total": 50, "categoria": "frio"}

    # Asegurar campos mínimos
    categoria = data.get("categoria", "frio")
    total = data.get("total", 50)

    print(f"🏁 [RESULTADO FINAL] → {categoria.upper()} ({total} pts)")
    print("------------------------------------\n")

    return data
