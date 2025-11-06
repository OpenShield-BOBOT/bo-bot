import sys
import uuid
from pathlib import Path
from typing import List, Tuple

import chromadb
import pandas as pd
import google.generativeai as genai

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from backend.app.core.config import get_settings


settings = get_settings()

if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)
else:
    print(
        "⚠️ Advertencia: GEMINI_API_KEY no configurada. "
        "El script de ingesta no podrá generar embeddings."
    )

DATA_RAW_DIR = ROOT_DIR / "data" / "raw"
CHROMA_DIR = Path(settings.chroma_db_dir)
CHROMA_COLLECTION_NAME = settings.chroma_collection_name




def read_txt_files() -> List[Tuple[Path, str]]:
    """Lee todos los .txt en data/raw."""
    if not DATA_RAW_DIR.exists():
        raise FileNotFoundError(f"No existe la carpeta {DATA_RAW_DIR}")

    files = sorted(DATA_RAW_DIR.glob("*.txt"))

    documents: List[Tuple[Path, str]] = []
    if not files:
        print(
            f"⚠️ No se encontraron archivos .txt en {DATA_RAW_DIR}. "
            f"Se continuará solo con otras fuentes (por ejemplo, FAQs CSV)."
        )
        return documents

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        documents.append((path, text))
    return documents


def read_faqs_csv() -> List[Tuple[Path, str]]:
    """
    Lee data/raw/faqs_bob.csv y transforma cada fila en un texto tipo Q&A oficial.

    Se espera un CSV con columnas:
      - Id
      - Categoría
      - Empresa
      - Pregunta
      - Respuesta
    """
    csv_path = DATA_RAW_DIR / "faqs_bob.csv"
    if not csv_path.exists():
        print(f"⚠️ No se encontró {csv_path}, se omiten FAQs.")
        return []

    print(f"📥 Cargando FAQs desde: {csv_path}")
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"⚠️ No se pudo leer {csv_path}: {e}")
        return []

    docs: List[Tuple[Path, str]] = []
    for _, row in df.iterrows():
        pregunta = str(row.get("Pregunta") or "").strip()
        respuesta = str(row.get("Respuesta") or "").strip()
        categoria = str(row.get("Categoría") or "").strip()
        empresa = str(row.get("Empresa") or "").strip()

        if not pregunta or not respuesta:
            continue

        header_parts = []
        if categoria:
            header_parts.append(f"Categoría: {categoria}")
        if empresa and empresa.lower() != "todos":
            header_parts.append(f"Empresa: {empresa}")

        header = " | ".join(header_parts)
        if header:
            texto = (
                f"[{header}]\n\n"
                f"Pregunta frecuente: {pregunta}\n"
                f"Respuesta oficial: {respuesta}"
            )
        else:
            texto = (
                f"Pregunta frecuente: {pregunta}\n"
                f"Respuesta oficial: {respuesta}"
            )

        docs.append((csv_path, texto))

    print(f"✅ FAQs cargadas desde CSV: {len(docs)} filas útiles")
    return docs


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 200) -> List[str]:
    """
    Divide el texto en pedazos (chunks) con solapamiento.
    Ej: chunk_size=800, overlap=200 → cada chunk comparte 200 chars con el anterior.
    """
    chunks: List[str] = []
    start = 0
    n = len(text)

    if not text.strip():
        return []

    while start < n:
        end = min(start + chunk_size, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += max(chunk_size - overlap, 1)

    return chunks


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Genera embeddings usando Gemini (mismo modelo que el pipeline RAG).
    """
    if not texts:
        return []

    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY no está configurada. No se pueden generar embeddings."
        )

    embeddings: List[List[float]] = []

    for text in texts:
        try:
            result = genai.embed_content(
                model=settings.gemini_embedding_model,
                content=text,
            )
            emb = result["embedding"]
            embeddings.append(emb)
        except Exception as e:
            raise RuntimeError(f"Error generando embedding con Gemini: {e}")

    return embeddings


def get_chroma_collection():
    """
    Crea (o recrea) una base de datos Chroma persistente en CHROMA_DIR
    y devuelve la colección configurada en settings.chroma_collection_name.
    """
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    try:
        client.delete_collection(CHROMA_COLLECTION_NAME)
    except Exception:
        pass

    collection = client.get_or_create_collection(name=CHROMA_COLLECTION_NAME)
    return client, collection


def ingest():
    print("📂 Leyendo archivos de texto desde:", DATA_RAW_DIR)
    docs_txt = read_txt_files()
    print(f"   → {len(docs_txt)} archivo(s) .txt encontrado(s).")

    print("📂 Leyendo FAQs desde CSV (faqs_bob.csv)...")
    docs_faqs = read_faqs_csv()
    print(f"   → {len(docs_faqs)} filas de FAQs convertidas a documentos.")

    docs = docs_txt + docs_faqs

    if not docs:
        raise RuntimeError(
            "No hay documentos para ingestar. Asegúrate de tener "
            "archivos .txt en data/raw y/o el archivo faqs_bob.csv."
        )

    print(f"📚 Documentos totales antes de chunking: {len(docs)}")

    client, collection = get_chroma_collection()
    print(f"💾 Usando Chroma en: {CHROMA_DIR}")
    print(f"   → Colección: {CHROMA_COLLECTION_NAME}")

    all_ids: List[str] = []
    all_texts: List[str] = []
    all_metadatas: List[dict] = []

    for file_path, text in docs:
        rel_path = file_path.relative_to(ROOT_DIR)
        chunks = chunk_text(text)
        print(f"   · {file_path.name}: {len(chunks)} chunks")

        for idx, chunk in enumerate(chunks):
            doc_id = f"{file_path.stem}-{idx}-{uuid.uuid4().hex[:8]}"
            all_ids.append(doc_id)
            all_texts.append(chunk)
            all_metadatas.append(
                {
                    "source": str(rel_path),
                    "file_name": file_path.name,
                    "chunk_index": idx,
                }
            )

    print(f"🧠 Total de chunks a indexar: {len(all_texts)}")

    batch_size = 32
    for start in range(0, len(all_texts), batch_size):
        end = start + batch_size
        batch_texts = all_texts[start:end]
        batch_ids = all_ids[start:end]
        batch_metadatas = all_metadatas[start:end]

        print(f"   → Embeddings {start} - {end} ...", end="", flush=True)
        batch_embeddings = embed_texts(batch_texts)

        collection.add(
            ids=batch_ids,
            documents=batch_texts,
            embeddings=batch_embeddings,
            metadatas=batch_metadatas,
        )
        print(" OK")

    try:
        count = collection.count()
    except Exception:
        count = "desconocido"

    print("✅ Ingesta completada.")
    print(f"   → Chunks totales en la colección: {count}")


def main():
    print("🚀 Iniciando ingesta de base de conocimiento de BOB Subastas...")
    ingest()
    print("🎉 Listo.")


if __name__ == "__main__":
    main()
