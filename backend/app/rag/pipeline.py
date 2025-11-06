from typing import Dict, List, Tuple, Optional

import chromadb
import google.generativeai as genai

from backend.app.core.config import get_settings

settings = get_settings()

if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)
else:
    print("⚠️ Advertencia: GEMINI_API_KEY no configurada. El pipeline no podrá generar respuestas.")


class RAGPipeline:
    """
    Pipeline RAG que:
    - Consulta Chroma (retrieval)
    - Construye prompt con contexto (si lo hay) + breve historial de la sesión
    - Llama al modelo de chat en Gemini
    """

    def __init__(self) -> None:
        print("🚀 Inicializando pipeline RAG con Gemini...")
        self.client = chromadb.PersistentClient(path=settings.chroma_db_dir)
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection_name
        )
        print(f"📂 ChromaDB cargada: {settings.chroma_collection_name}")
        print("📄 Documentos en la base:", self.collection.count())

        self.chat_model = getattr(settings, "gemini_model_name", "gemini-2.5-flash")
        self.embedding_model = getattr(settings, "gemini_embedding_model", "models/embedding-001")

        self.top_k = 5
        self.max_distance = 0.8

    # ---------------- EMBEDDING ----------------
    def _embed_query(self, text: str) -> List[float]:
        print("🧠 Generando embedding con Gemini...")
        try:
            result = genai.embed_content(model=self.embedding_model, content=text)
            return result["embedding"]
        except Exception as e:
            raise RuntimeError(f"Error generando embeddings con Gemini: {e}")

    # ---------------- RETRIEVAL ----------------
    def _retrieve_context(self, question: str) -> Tuple[List[str], List[float]]:
        print(f"🔍 Buscando contexto relevante en Chroma para: '{question}'")
        try:
            count = self.collection.count()
        except Exception:
            count = 0

        if not count:
            print("⚠️ Base de conocimiento vacía. Sin contexto.")
            return [], []

        query_embedding = self._embed_query(question)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=self.top_k,
            include=["documents", "distances"],
        )

        docs = result.get("documents", [[]])[0]
        distances = result.get("distances", [[]])[0]

        filtered_docs = [doc for d, doc in zip(distances, docs) if d <= self.max_distance]
        print(f"📚 Fragmentos recuperados: {len(filtered_docs)}")
        return filtered_docs, distances

    # ---------------- PROMPT ----------------
    def _build_prompt(
        self,
        question: str,
        context_chunks: List[str],
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        print("🧩 Construyendo prompt para Gemini...")

        history_text = ""
        if chat_history:
            last_msgs = chat_history[-6:]
            history_text = "\n".join(
                f"{'Usuario' if msg['role']=='user' else 'Asistente'}: {msg['content']}"
                for msg in last_msgs
                if msg.get("content")
            )

        # Prompt base compartido: personalidad de BOBot y reglas
        persona_block = """
Te llamas **BOBot** y eres el asistente virtual oficial de BOB Subastas, una empresa peruana
dedicada a la compra y subasta de autos y maquinaria de segundo uso.

Tu estilo:
- Hablas siempre en español.
- Usas un tono cercano, sencillo y amigable (como un asesor buena onda, pero profesional).
- Explicas las cosas de forma clara y directa.
- Casi siempre terminas tus respuestas con una pregunta corta que invite a seguir conversando,
  salvo que el usuario se despida o diga que ya no tiene más dudas.

Reglas sobre asesores y límites:
- Solo menciona a los asesores humanos de BOB Subastas cuando:
  - El usuario pida explícitamente hablar con alguien / que lo contacten, o
  - El usuario pida más información de un tema que SÍ está en el contexto o en tu respuesta,
    pero ya no tengas más detalles concretos que aportar.
- No menciones asesores por defecto en saludos o respuestas generales.

Límites de información:
- Si la pregunta es claramente sobre temas que NO están relacionados con BOB Subastas,
  autos, maquinaria, subastas, precios, garantías, pagos o procesos de BOB:
  - Responde que no tienes información sobre ese tema.
  - Recalca que eres BOBot, el chatbot de BOB Subastas.
  - Invita a la persona a preguntarte algo sobre BOB Subastas.

- Nunca inventes datos técnicos, precios, fechas, políticas ni condiciones comerciales.
"""

        if context_chunks:
            context_text = "\n\n".join(f"- {chunk.strip()}" for chunk in context_chunks)
            prompt = (
                f"{persona_block}\n\n"
                "Instrucciones específicas para esta respuesta:\n"
                "- Usa EXCLUSIVAMENTE el contexto proporcionado a continuación para responder.\n"
                "- Si el usuario pide más detalle de algo que aparece en el contexto pero no hay más "
                "información, puedes decir que hasta ahí llega la información disponible y que, si lo desea, "
                "un asesor de BOB Subastas puede darle más detalles.\n"
                "- Si el contexto no responde la pregunta y la pregunta no parece estar relacionada con BOB Subastas, "
                "di claramente que no tienes información sobre ese tema y recuérdale que eres BOBot.\n\n"
                f"📚 Contexto relevante:\n{context_text}\n\n"
            )
            if history_text:
                prompt += f"🕓 Historial reciente de conversación:\n{history_text}\n\n"
            prompt += f"Pregunta del usuario:\n{question}"
        else:
            # Sin contexto en Chroma: usa solo conocimiento general sobre BOB Subastas
            prompt = (
                f"{persona_block}\n\n"
                "No tienes contexto adicional de documentos para esta pregunta.\n"
                "Responde usando únicamente lo que sepas sobre BOB Subastas y el sentido común.\n"
                "- Si no estás seguro o no tienes información, dilo claramente.\n"
                "- Si el usuario pide más detalle del proceso pero tú ya explicaste lo que sabes, "
                "puedes mencionar que un asesor de BOB Subastas podría ayudarle con más detalle.\n"
                "- Si la pregunta es claramente ajena a BOB Subastas, indica que no tienes información "
                "sobre ese tema y recuérdale que eres BOBot, el chatbot de BOB Subastas.\n\n"
            )
            if history_text:
                prompt += f"🕓 Historial reciente de conversación:\n{history_text}\n\n"
            prompt += f"Pregunta del usuario:\n{question}"

        return prompt

    # ---------------- LLM CALL ----------------
    def _call_llm(self, prompt: str) -> str:
        print("💬 Llamando a Gemini para generar respuesta...")
        try:
            model = genai.GenerativeModel(self.chat_model)
            response = model.generate_content(prompt)
            text = (response.text or "").strip()
            print("✅ Gemini respondió con texto.")
            return text
        except Exception as e:
            raise RuntimeError(f"Error generando respuesta con Gemini: {e}")

    # ---------------- MAIN PIPELINE ----------------
    async def answer(
        self,
        question: str,
        session_id: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict:
        print(f"\n🗨️ Nueva consulta: {question}")
        print(f"💡 Session ID: {session_id}")

        # 1️⃣ Recuperar contexto
        context_chunks, _ = self._retrieve_context(question)
        used_context = bool(context_chunks)
        print(f"📚 Contexto utilizado: {'sí' if used_context else 'no'}")

        # 2️⃣ Construir prompt
        prompt = self._build_prompt(question, context_chunks, chat_history)

        # 3️⃣ Generar respuesta principal
        try:
            answer_text = self._call_llm(prompt)
        except Exception as e:
            answer_text = (
                f"⚠️ Error al conectar con Gemini ({e}). "
                "Por ahora no puedo responder bien, pero puedes intentar de nuevo más tarde. "
                "¿Te gustaría probar otra pregunta sobre BOB Subastas?"
            )

        print("✅ Respuesta generada y enviada al usuario.")

        return {
            "answer": answer_text,
            "used_context": used_context,
        }
