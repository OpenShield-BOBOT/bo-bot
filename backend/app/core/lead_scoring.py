import re
import json
from pathlib import Path
from typing import Literal

import google.generativeai as genai
from backend.app.core.config import get_settings

# ==============================
# 🔧 CONFIGURACIÓN GLOBAL
# ==============================
settings = get_settings()

if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)
else:
    print("⚠️ Advertencia: no se ha configurado GEMINI_API_KEY en el .env")

# ---------------------------------------------------
# 🧱 Tipos y constantes
# ---------------------------------------------------
LeadScore = Literal["frio", "templado", "caliente"]

# Rangos oficiales según criterios_de_score.txt:
# - CALIENTE: 85-100 puntos
# - TIBIO:    65-84 puntos
# - FRÍO:     45-64 puntos
# - DESCARTADO: <45 puntos
CALIENTE_MIN = 85
TIBIO_MIN = 65
FRIO_MIN = 45
MIN_SCORE = 0
MAX_SCORE = 100

HOT_THRESHOLD = CALIENTE_MIN
WARM_THRESHOLD = TIBIO_MIN

# Puntaje neutro / fallback cuando NO se puede evaluar bien
FALLBACK_SCORE = 20  # 👈 AHORA 20, no 50/30


# ---------------------------------------------------
# 🧠 Funciones internas
# ---------------------------------------------------
def _get_criteria_path() -> Path:
    """Devuelve la ruta correcta al archivo de criterios."""
    candidates = [
        Path("data/criterios_de_score.txt"),
        Path("data/CRITERIOS_DE_SCORE.txt"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "❌ No se encontró 'data/criterios_de_score.txt' o 'data/CRITERIOS_DE_SCORE.txt'"
    )


def total_to_categoria(total: int) -> str:
    """Convierte un score 0-100 en 'caliente', 'tibio', 'frio' o 'descartado'."""
    if total >= CALIENTE_MIN:
        return "caliente"
    if total >= TIBIO_MIN:
        return "tibio"
    if total >= FRIO_MIN:
        return "frio"
    return "descartado"


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------
# 🤖 Evaluación detallada con Gemini (criterios TXT)
# ---------------------------------------------------
def evaluate_lead(message: str) -> dict:
    """
    Evalúa el mensaje del usuario según los criterios oficiales definidos en
    data/criterios_de_score.txt. Devuelve un dict con totales y categoría.
    """
    print("\n------------------------------------")
    print("📊 [SCORING] Iniciando evaluación detallada del lead...")
    print(f"🗨️ Texto evaluado: {message}")

    # 🔹 Regla explícita para saludos muy genéricos (ej. "hola", "buenas", etc.)
    norm = _normalize_text(message)
    saludos_simples = {
        "hola",
        "buenas",
        "buenas tardes",
        "buenos dias",
        "buenos días",
        "buenas noches",
        "hola buenos dias",
        "hola buenos días",
        "hola buenas tardes",
        "hola buenas noches",
        "hi",
        "hey",
        "hello",
    }
    if norm in saludos_simples:
        print("🟢 [SCORING] Detectado saludo simple → score 20 FRÍO.")
        data = {
            "total": FALLBACK_SCORE,
            "categoria": "frio",  # en detallado sería <45 = 'descartado', pero usamos 'frio' en simple
            "detalle": {"motivo": "solo_saludo_sin_intencion"},
        }
        print(f"🏁 [RESULTADO FINAL] → FRIO ({FALLBACK_SCORE} pts, saludo simple)\n")
        return data

    criteria_path = _get_criteria_path()
    system_prompt = criteria_path.read_text(encoding="utf-8")

    print(f"📁 Criterios cargados desde: {criteria_path.name}")

    system_prompt += """
    
Asegúrate de devolver EXCLUSIVAMENTE un JSON válido, sin texto adicional ni explicaciones.
Si no puedes evaluar, devuelve un JSON con esta estructura (usa valores enteros):
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

    prompt = f"{system_prompt}\n\nTEXTO_DEL_USUARIO_O_CONVERSACION:\n{message}"

    if not settings.gemini_api_key:
        print("⚠️ [SCORING] No hay GEMINI_API_KEY, devolviendo score fallback (20).")
        return {
            "total": FALLBACK_SCORE,
            "categoria": "frio",
            "detalle": {},
        }

    print("🤖 [Gemini] Enviando mensaje para evaluación avanzada...")

    model_name = getattr(settings, "gemini_model_name", "gemini-2.5-flash") or "gemini-2.5-flash"
    model = genai.GenerativeModel(model_name)

    try:
        # 👇 Forzamos salida JSON
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
            },
        )
        raw_text = (response.text or "").strip()
        print("✅ [Gemini] Respuesta recibida correctamente.")

    except Exception as e:
        print(f"⚠️ [Gemini] Error durante la evaluación: {e}")
        print("🟡 Fallback → asignando score 20 FRÍO.")
        return {
            "total": FALLBACK_SCORE,
            "categoria": "frio",
            "detalle": {},
        }

    # Intentamos parsear el JSON de forma robusta
    try:
        try:
            data = json.loads(raw_text)
        except Exception:
            # Por si el modelo mete algo extra: recortamos al primer/último { }
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(raw_text[start : end + 1])
            else:
                raise
        print("📦 JSON recibido desde Gemini:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"⚠️ No se pudo interpretar el JSON de Gemini: {e}")
        print("🟡 Fallback → asignando score 20 FRÍO.")
        data = {"total": FALLBACK_SCORE, "categoria": "frio"}

    # Normalización
    try:
        total = int(data.get("total", FALLBACK_SCORE) or FALLBACK_SCORE)
    except Exception:
        total = FALLBACK_SCORE

    total = max(MIN_SCORE, min(MAX_SCORE, total))

    categoria_oficial = total_to_categoria(total)
    data["total"] = total
    data["categoria"] = categoria_oficial

    print(f"🏁 [RESULTADO FINAL] → {categoria_oficial.upper()} ({total} pts)")
    print("------------------------------------\n")

    return data


# ---------------------------------------------------
# 🔹 Mapeos y helpers para integración
# ---------------------------------------------------
def _categoria_detallada_a_simple(categoria: str) -> LeadScore:
    """
    Convierte categoría detallada ('caliente', 'tibio', 'frio', 'descartado')
    a la escala simple ('caliente', 'templado', 'frio').
    """
    cat = (categoria or "").strip().lower()
    if cat == "caliente":
        return "caliente"
    if cat in ("tibio", "templado"):
        return "templado"
    # 'frio' y 'descartado' → 'frio' en la escala simple
    return "frio"


def total_points_to_category(total: int) -> LeadScore:
    """Usa los mismos umbrales oficiales para mapear un total (0-100) a frío/templado/caliente."""
    if total >= HOT_THRESHOLD:
        return "caliente"
    if total >= WARM_THRESHOLD:
        return "templado"
    return "frio"


def category_to_points(label: str) -> int:
    """
    Compatibilidad hacia atrás: traduce una categoría simple a un número
    representativo de la escala (45/65/85).
    """
    lab = (label or "").strip().lower()
    if lab == "caliente":
        return HOT_THRESHOLD
    if lab == "templado":
        return WARM_THRESHOLD
    return FRIO_MIN


# ---------------------------------------------------
# 🔹 Fallback por reglas simples (solo si Gemini falla)
# ---------------------------------------------------
def classify_lead_rule_based(message: str) -> LeadScore:
    """Clasificación por reglas muy básicas (solo respaldo)."""
    print("[LeadScoring] Usando método por REGLAS (fallback)")
    msg = _normalize_text(message)
    if any(word in msg for word in ["comprar", "ofertar", "subasta", "pago", "transferi"]):
        return "caliente"
    if any(word in msg for word in ["precio", "garantia", "financiamiento", "credito", "disponible"]):
        return "templado"
    return "frio"


# ---------------------------------------------------
# 🔹 Función pública principal
# ---------------------------------------------------
def classify_lead(text: str) -> LeadScore:
    """
    Clasifica el lead usando EXCLUSIVAMENTE los criterios oficiales del TXT,
    aplicados al texto completo (mensaje o conversación).
    Si algo falla, usa reglas simples como respaldo.
    """
    try:
        detailed = evaluate_lead(text)
        categoria_detallada = detailed.get("categoria", "frio")
        lead_label = _categoria_detallada_a_simple(categoria_detallada)
        print(f"[LeadScoring] Avanzado → {categoria_detallada} → {lead_label}")
        return lead_label
    except Exception as e:
        print(f"[LeadScoring] ⚠️ Error en scoring avanzado, fallback a reglas: {e}")
        return classify_lead_rule_based(text)
