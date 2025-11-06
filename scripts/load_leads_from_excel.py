import sys
from pathlib import Path

import pandas as pd
from sqlmodel import Session, delete, select

# Aseguramos que el backend sea importable al ejecutar el script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from backend.app.db.session import engine, init_db  # noqa: E402
from backend.app.db.models import Lead             # noqa: E402


def load_leads_from_excel(xlsx_path: Path, truncate_excel_leads: bool = True) -> None:
    """
    Carga leads ficticios desde un Excel a la tabla Lead.

    - xlsx_path: ruta al archivo datos_ficticios_completo.xlsx
    - truncate_excel_leads: si es True, borra antes todos los Lead con channel="excel_import"
    """

    if not xlsx_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {xlsx_path}")

    print(f"📥 Leyendo Excel: {xlsx_path}")

    # Leemos columnas como texto donde importa (DNI, Teléfono)
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
        # Si quieres, podrías hacer: raise ValueError(...)

    print("🧱 Asegurando que las tablas existan (init_db)...")
    init_db()

    with Session(engine) as session:
        if truncate_excel_leads:
            print('🧹 Borrando leads previos con channel="excel_import"...')
            session.exec(delete(Lead).where(Lead.channel == "excel_import"))
            session.commit()

        print("💾 Insertando leads ficticios en la tabla Lead...")

        for idx, row in df.iterrows():
            nombres = str(row.get("Nombres") or "").strip()
            apellidos = str(row.get("Apellidos") or "").strip()
            full_name = f"{nombres} {apellidos}".strip() or None

            dni = str(row.get("DNI") or "").strip()
            telefono = str(row.get("Teléfono") or "").strip()
            email = str(row.get("Correo Electrónico") or "").strip()
            ciudad = str(row.get("Ciudad") or "").strip()

            # Construimos el campo contact
            contact_parts = []
            if telefono:
                contact_parts.append(f"Tel: {telefono}")
            if email:
                contact_parts.append(f"Email: {email}")
            if ciudad:
                contact_parts.append(f"Ciudad: {ciudad}")

            contact = " | ".join(contact_parts) if contact_parts else None

            # session_id: usamos el DNI si existe, si no un fallback
            if dni:
                session_id = f"excel-{dni}"
            else:
                session_id = f"excel-row-{idx}"

            lead = Lead(
                session_id=session_id,
                channel="excel_import",  # 👈 para distinguirlos
                name=full_name,
                contact=contact,
                lead_score="caliente",
            )

            session.add(lead)

        session.commit()

        # Conteo final (usamos len(list(...)) en vez de .count())
        all_leads_result = session.exec(select(Lead))
        total = len(list(all_leads_result))

        excel_leads_result = session.exec(
            select(Lead).where(Lead.channel == "excel_import")
        )
        total_excel = len(list(excel_leads_result))

        print(f"✅ Carga completada. Leads totales en la tabla: {total}")
        print(f"✅ Leads importados desde Excel (channel='excel_import'): {total_excel}")


def main():
    # Ruta por defecto: data/datos_ficticios_completo.xlsx (desde la raíz del proyecto)
    xlsx_path = ROOT_DIR / "data" / "datos_ficticios_completo.xlsx"
    load_leads_from_excel(xlsx_path, truncate_excel_leads=True)


if __name__ == "__main__":
    main()
