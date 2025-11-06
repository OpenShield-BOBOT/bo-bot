import re
from typing import Literal

import google.generativeai as genai
from backend.app.core.config import get_settings

# ==============================
# 🔧 CONFIGURACIÓN GLOBAL
# ==============================
settings = get_settings()

# Configura Gemini solo una vez
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)
else:
    print("⚠️ Advertencia: no se ha configurado GEMINI_API_KEY en el .env")

LeadScore = Literal["frio", "templado", "caliente"]

POINTS_BY_CATEGORY = {
    "frio": 1,
    "templado": 3,
    "caliente": 6,
}

# Umbrales sobre el acumulado por sesión
HOT_THRESHOLD = 12      # >= 12 puntos → sesión caliente
WARM_THRESHOLD = 6      # >= 6 y < 12   → sesión templada


# ==============================
# 🔹 UTILIDADES DE SCORE
# ==============================
def category_to_points(label: str) -> int:
    """Convierte una etiqueta ('frio', 'templado', 'caliente') en puntos."""
    return POINTS_BY_CATEGORY.get(label.lower(), 0)


def total_points_to_category(total: int) -> LeadScore:
    """Dado el score acumulado, devuelve la categoría global."""
    if total >= HOT_THRESHOLD:
        return "caliente"
    if total >= WARM_THRESHOLD:
        return "templado"
    return "frio"


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ==============================
# 🔹 CLASIFICADOR POR REGLAS (BACKUP)
# ==============================
def classify_lead_rule_based(message: str) -> LeadScore:
    """Versión simple por reglas."""
    print("[LeadScoring] Usando método por REGLAS")

    msg = normalize(message)

    hot_phrases = [
        "quiero comprar", "deseo comprar", "ya hice el pago",
        "ya pague", "ya pagué", "ya transferí", "ya transfiri",
        "quiero ofertar", "quiero hacer una oferta", "quiero cerrar la compra",
        "cerrar trato", "puedo recoger el auto", "puedo recoger el vehículo",
        "separar el auto", "reservar el auto",
    ]

    hot_word_combos = [
        ["participar", "subasta"],
        ["ofertar", "subasta"],
        ["pujar", "subasta"],
    ]

    warm_keywords = [
        "precio", "cuánto cuesta", "cuanto cuesta", "costo",
        "disponible", "disponibilidad", "financiamiento", "crédito",
        "credito", "garantía", "garantias", "estado del auto",
        "estado del vehículo", "kilometraje", "km",
    ]

    interest_phrases = [
        "estoy interesado", "estoy muy interesado", "me interesa",
        "me llama la atención", "me llama la atencion",
    ]

    score = 0

    if any(p in msg for p in hot_phrases):
        score += 3

    if any(all(w in msg for w in combo) for combo in hot_word_combos):
        score += 3

    if any(p in msg for p in warm_keywords):
        score += 1

    if any(p in msg for p in interest_phrases):
        score += 1

    if score >= 3:
        return "caliente"
    if score >= 1:
        return "templado"
    return "frio"


# ==============================
# 🤖 CLASIFICADOR CON GEMINI
# ==============================
def classify_lead_llm(message: str) -> LeadScore:
    """
    Usa el modelo de Gemini para clasificar el lead.
    Devuelve: "frio", "templado" o "caliente".
    """
    system_prompt = (
        "Eres un clasificador de intención de compra para BOB Subastas.\n\n"
        "Debes analizar el MENSAJE DEL USUARIO y clasificarlo en una sola etiqueta:\n"
        "- 'frio'      → saludo, dudas generales, sin intención clara de comprar u ofertar.\n"
        "- 'templado'  → muestra interés, hace preguntas sobre precio, disponibilidad, "
        "  estado del vehículo o financiamiento, pero no dice explícitamente que quiera ofertar o comprar.\n"
        "- 'caliente'  → el usuario quiere participar en una subasta, ofertar, pujar, "
        "  reservar, cerrar la compra o indica que ya pagó/transferió.\n\n"
        "Responde SOLO con una de estas palabras, en minúsculas: frio, templado o caliente.\n"
        "No agregues explicaciones ni texto adicional."
    )

    try:
        print("[LeadScoring] Llamando a Gemini para clasificar lead...")

        model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"{system_prompt}\n\nMENSAJE DEL USUARIO:\n{message}"
        response = model.generate_content(prompt)
        content = response.text.strip().lower()

        print(f"[LeadScoring] Gemini respondió: {content}")

    except Exception as e:
        print(f"[LeadScoring] ⚠️ Error con Gemini, fallback a REGLAS: {e}")
        return classify_lead_rule_based(message)

    # Limpieza: validamos que la respuesta contenga algo válido
    if "caliente" in content:
        return "caliente"
    if "templado" in content:
        return "templado"
    if "frio" in content or "frío" in content:
        return "frio"

    print("[LeadScoring] ⚠️ Respuesta Gemini no válida, fallback a REGLAS")
    return classify_lead_rule_based(message)


# ==============================
# 🔹 FUNCIÓN PÚBLICA
# ==============================
def classify_lead(message: str) -> LeadScore:
    """Usa primero la IA y, si algo falla, las reglas."""
    return classify_lead_llm(message)
