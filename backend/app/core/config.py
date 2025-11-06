from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "BOB Subastas - AI Agent"
    app_env: str = "dev"

    # === Gemini (Google Generative AI) ===
    gemini_api_key: str | None = None
    gemini_model_name: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "models/embedding-001"

    # === Rutas de datos / RAG ===
    chroma_db_dir: str = str(Path("data/chroma_db").absolute())
    chroma_collection_name: str = "bob_knowledge_base"

    # === Base de datos relacional ===
    sqlite_url: str = "sqlite:///./data/bob_agent.db"

    # === Configuración de Twilio ===
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str | None = None   # ej: "whatsapp:+14155238886"
    twilio_advisor_whatsapp: str | None = None  # ej: "whatsapp:+51TU_NUMERO"

    # === Configuración general de Pydantic Settings ===
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
