from sqlmodel import SQLModel, create_engine, Session

from backend.app.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.sqlite_url, echo=False)


def init_db() -> None:
    """
    Inicializa las tablas en la base de datos.
    Se llamará en el evento de startup de FastAPI.
    """
    import backend.app.db.models
    SQLModel.metadata.create_all(bind=engine)


def get_session():
    """
    Dependency de FastAPI para obtener una sesión de base de datos.
    """
    with Session(engine) as session:
        yield session
