from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.v1 import api_v1_router
from backend.app.db.session import init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title="BOB Subastas - AI Agent",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router, prefix="/api/v1")

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def root():
        return {"message": "BOB Subastas AI backend"}

    return app


app = create_app()
