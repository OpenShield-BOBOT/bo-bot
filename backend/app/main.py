from fastapi import FastAPI

from backend.app.api.v1 import api_v1_router
from backend.app.db.session import init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title="BOB Subastas - AI Agent",
        version="0.1.0",
    )

    # 👉 Registramos todas las rutas bajo /api/v1
    app.include_router(api_v1_router, prefix="/api/v1")

    @app.on_event("startup")
    def on_startup() -> None:
        # Inicializa la base de datos (crea tablas si no existen)
        init_db()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # Ruta raíz para comprobar que estamos en este main y no en otro
    @app.get("/")
    async def root():
        return {"message": "BOB Subastas AI backend"}

    return app


# 👇 Esta variable es lo que uvicorn usa en backend.app.main:app
app = create_app()
