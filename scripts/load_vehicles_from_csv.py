import sys
from pathlib import Path

import pandas as pd
from sqlmodel import Session, delete

# Aseguramos que el backend sea importable al ejecutar el script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from backend.app.db.session import engine, init_db  # noqa: E402
from backend.app.db.models import Vehicle          # noqa: E402


def load_vehicles_from_csv(csv_path: Path, truncate_before: bool = True) -> None:
    """
    Carga hackathon_data.csv en la tabla Vehicle.

    - csv_path: ruta al CSV.
    - truncate_before: si es True, borra los registros existentes antes de insertar.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {csv_path}")

    print(f"📥 Leyendo CSV: {csv_path}")

    # Ojo: el archivo viene con encoding latin1, no utf-8
    df = pd.read_csv(csv_path, encoding="latin1")
    print(f"   Filas leídas: {len(df)}")

    # Verificación rápida de columnas
    expected_columns = [
        "title",
        "precio_base",
        "tipo_moneda",
        "ubicacion",
        "marca",
        "modelo",
        "placa",
        "kilometraje",
        "anio",
        "procedencia",
        "con_garantia",
        "categoria",
        "tipo_subasta",
        "empresa_proveedora",
    ]
    missing = [c for c in expected_columns if c not in df.columns]
    if missing:
        print("⚠️ Faltan estas columnas en el CSV:")
        for c in missing:
            print(f"   - {c}")
        # Si quieres, aquí puedes hacer raise ValueError

    # Normalización de tipos numéricos
    df["precio_base"] = pd.to_numeric(df.get("precio_base"), errors="coerce")
    df["kilometraje"] = pd.to_numeric(df.get("kilometraje"), errors="coerce")
    df["anio"] = pd.to_numeric(df.get("anio"), errors="coerce")

    # con_garantia ya viene como True / False / NaN en tu archivo,
    # pero igual aseguramos que sea bool / None
    if "con_garantia" in df.columns:
        def normalize_warranty(x):
            # ya viene como bool o NaN, pero por si acaso:
            if isinstance(x, bool):
                return x
            if isinstance(x, str):
                xl = x.strip().lower()
                if xl in ("true", "si", "sí", "yes", "1"):
                    return True
                if xl in ("false", "no", "0"):
                    return False
            return None

        df["con_garantia"] = df["con_garantia"].apply(normalize_warranty)

    # Aseguramos que la tabla exista
    print("🧱 Asegurando que las tablas existan (init_db)...")
    init_db()

    with Session(engine) as session:
        if truncate_before:
            print("🧹 Borrando registros previos de Vehicle...")
            session.exec(delete(Vehicle))
            session.commit()

        print("💾 Insertando vehículos en la base de datos...")

        for _, row in df.iterrows():
            vehicle = Vehicle(
                title=row.get("title"),
                precio_base=float(row["precio_base"]) if not pd.isna(row.get("precio_base")) else None,
                tipo_moneda=row.get("tipo_moneda"),
                ubicacion=row.get("ubicacion"),
                marca=row.get("marca"),
                modelo=row.get("modelo"),
                placa=str(row.get("placa")) if not pd.isna(row.get("placa")) else None,
                kilometraje=float(row["kilometraje"]) if not pd.isna(row.get("kilometraje")) else None,
                anio=int(row["anio"]) if not pd.isna(row.get("anio")) else None,
                procedencia=row.get("procedencia"),
                con_garantia=row.get("con_garantia"),
                categoria=row.get("categoria"),
                tipo_subasta=row.get("tipo_subasta"),
                empresa_proveedora=row.get("empresa_proveedora"),
            )
            session.add(vehicle)

        session.commit()

        # Contador final
        total = session.query(Vehicle).count()
        print(f"✅ Carga completada. Vehículos en la tabla: {total}")


def main():
    # Ruta por defecto: data/hackathon_data.csv (desde la raíz del proyecto)
    csv_path = ROOT_DIR / "data" / "hackathon_data.csv"
    load_vehicles_from_csv(csv_path)


if __name__ == "__main__":
    main()
