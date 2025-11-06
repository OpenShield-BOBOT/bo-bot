import sys
from pathlib import Path

import pandas as pd
from sqlmodel import Session, delete, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from backend.app.db.session import engine, init_db
from backend.app.db.models import Lead


def load_leads_from_excel(xlsx_path: Path, truncate_excel_leads: bool = True) -> None:
    """
    Carga leads ficticios desde un Excel a la tabla Lead.

    - xlsx_path: ruta al archivo datos_ficticios_completo.xlsx
    - truncate_excel_leads: si es True, borra antes todos los Lead con channel="excel_import"
    """

    if not xlsx_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {xlsx_path}")

    print(f"📥 Leyendo Excel: {xlsx_path}")

    df = pd.read_excel(
        xlsx_path,
        dtype={
            "DNI": str,
            "Teléfono": str,
        },
    )

    print(f"   Filas leídas: {len(df)}")
    print(f"   Columnas: {list(df.columns)}")

    expected_cols = [
        "Nombres",
        "Apellidos",
        "DNI",
        "Teléfono",
        "Correo Electrónico",
        "Ciudad",
    ]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        print("⚠️ Faltan estas columnas en el Excel:")
        for c in missing:
            print(f"   - {c}")

    print("🧱 Asegurando que las tablas existan (init_db)...")
    init_db()

    with Session(engine) as session:
        if truncate_excel_leads:
            print('🧹 Borrando leads previos con channel="excel_import"...')
            session.exec(delete(Lead).where(Lead.channel == "excel_import"))
            session.commit()

        print("💾 Insertando leads ficticios en la tabla Lead...")

        for idx, row in df.iterrows():
            nombres = str(row.get("Nombres") or "").strip() or None
            apellidos = str(row.get("Apellidos") or "").strip() or None
            dni = str(row.get("DNI") or "").strip() or None
            telefono = str(row.get("Teléfono") or "").strip() or None
            email = str(row.get("Correo Electrónico") or "").strip() or None
            ciudad = str(row.get("Ciudad") or "").strip() or None

            if dni:
                session_id = f"excel-{dni}"
            else:
                session_id = f"excel-row-{idx}"

            lead = Lead(
                session_id=session_id,
                channel="excel_import",
                nombres=nombres,
                apellidos=apellidos,
                dni=dni,
                telefono=telefono,
                correo_electronico=email,
                ciudad=ciudad,
                lead_score="caliente",
                status="open",
            )

            session.add(lead)

        session.commit()

        all_leads_result = session.exec(select(Lead))
        total = len(list(all_leads_result))

        excel_leads_result = session.exec(
            select(Lead).where(Lead.channel == "excel_import")
        )
        total_excel = len(list(excel_leads_result))

        print(f"✅ Carga completada. Leads totales en la tabla: {total}")
        print(f"✅ Leads importados desde Excel (channel='excel_import'): {total_excel}")


def main():
    xlsx_path = ROOT_DIR / "data" / "datos_ficticios_completo.xlsx"
    load_leads_from_excel(xlsx_path, truncate_excel_leads=True)


if __name__ == "__main__":
    main()
