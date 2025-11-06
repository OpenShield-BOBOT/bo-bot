from typing import Dict, List, Tuple, Optional

import chromadb
import google.generativeai as genai

from backend.app.core.advanced_scoring import evaluate_lead_detailed
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
    - Calcula lead_score simple (por MENSAJE)
    """

    def __init__(self) -> None:
        self.client = chromadb.PersistentClient(path=settings.chroma_db_dir)
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection_name
        )


        self.chat_model = getattr(settings, "gemini_model_name", "gemini-1.5-flash")
        self.embedding_model = getattr(settings, "gemini_embedding_model", "models/embedding-001")

        self.top_k = 5
        self.max_distance = 0.8

    def _embed_query(self, text: str) -> List[float]:
        """
        Genera embeddings usando Gemini.
        """
        try:
            result = genai.embed_content(
                model=self.embedding_model,
                content=text
            )
            return result["embedding"]
        except Exception as e:
            raise RuntimeError(f"Error generando embeddings con Gemini: {e}")

    def _retrieve_context(self, question: str) -> Tuple[List[str], List[float]]:
        try:
            count = self.collection.count()
        except Exception:
            count = 0

        if not count:
            return [], []

        query_embedding = self._embed_query(question)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=self.top_k,
            include=["documents", "distances"],
        )

        docs = result.get("documents", [[]])[0]
        distances = result.get("distances", [[]])[0]

        filtered_docs, filtered_distances = [], []
        for d, doc in zip(distances, docs):
            if d <= self.max_distance:
                filtered_docs.append(doc)
                filtered_distances.append(d)

        return filtered_docs, filtered_distances

    def _build_prompt(
        self,
        question: str,
        context_chunks: List[str],
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        chat_history: lista de dicts tipo {"role": "user"/"assistant", "content": "..."}
        Se usa como contexto conversacional adicional.
        """
        history_text = ""
        if chat_history:
            last_msgs = chat_history[-6:]
            lines: List[str] = []
            for msg in last_msgs:
                role = msg.get("role")
                content = (msg.get("content") or "").strip()
                if not content:
                    continue
                prefix = "Usuario" if role == "user" else "Asistente"
                lines.append(f"{prefix}: {content}")
            if lines:
                history_text = "\n".join(lines)

        if context_chunks:
            context_text = "\n\n".join(f"- {chunk.strip()}" for chunk in context_chunks)
            prompt = (
                "Eres un asistente de BOB Subastas, una plataforma peruana de "
                "compra y subasta de autos y maquinaria de segundo uso.\n\n"
                "Responde de forma clara y amable usando **exclusivamente** la "
                "información del contexto proporcionado y, cuando sea útil, el historial de la conversación.\n"
                "Si algo importante no está en el contexto, di que no tienes información suficiente "
                "y sugiere contactar a un asesor.\n\n"
                f"Contexto de la base de conocimiento:\n{context_text}\n\n"
            )
            if history_text:
                prompt += (
                    "Historial breve de la conversación (no lo repitas literal, "
                    "úsalo solo como referencia):\n"
                    f"{history_text}\n\n"
                )
        else:
            prompt = (
                "Eres un asistente de BOB Subastas. No tienes contexto fiable de la base de conocimiento.\n\n"
                "Puedes apoyarte SOLO en el historial de la conversación si ayuda, "
                "pero si falta información clave, sé honesto y sugiere contactar a un asesor.\n\n"
            )
            if history_text:
                prompt += f"Historial breve de la conversación:\n{history_text}\n\n"

        prompt += (
            f"Pregunta actual del usuario:\n{question}\n\n"
            "Responde en español, en un tono profesional pero cercano."
        )
        return prompt

    def _call_llm(self, prompt: str) -> str:
        """
        Llama al modelo de Gemini para generar la respuesta.
        """
        try:
            model = genai.GenerativeModel(self.chat_model)
            response = model.generate_content(prompt)
            return (response.text or "").strip()
        except Exception as e:
            raise RuntimeError(f"Error generando respuesta con Gemini: {e}")

    async def answer(
        self,
        question: str,
        session_id: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict:
        """
        Devuelve:
        - answer: texto de respuesta
        - lead_score: etiqueta frio/templado/caliente (por mensaje)
        - used_context: si se usó contexto Chroma
        """
        context_chunks, _ = self._retrieve_context(question)
        used_context = bool(context_chunks)

        prompt = self._build_prompt(question, context_chunks, chat_history=chat_history)

        try:
            answer_text = self._call_llm(prompt)
        except Exception as e:
            answer_text = (
                "⚠️ En este momento tengo problemas para conectarme con el modelo de IA. "
                "Por favor, intenta nuevamente más tarde o contacta a un asesor. "
                f"(Detalle técnico: {e})"
            )

        detailed = evaluate_lead_detailed(question)
        lead_score = detailed["categoria"]
        lead_score_numeric = detailed["total"]

        return {
            "answer": answer_text,
            "lead_score": lead_score,
            "lead_score_numeric": lead_score_numeric,
            "used_context": used_context,
        }
