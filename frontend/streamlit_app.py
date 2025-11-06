import uuid

import requests
import streamlit as st
import pandas as pd  # 👈 NUEVO

BACKEND_URL = "http://localhost:8000"


def get_session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
        # Cuando arrancamos sesión nueva, aseguramos que el chat no esté cerrado
        st.session_state["chat_closed"] = False
        st.session_state["messages"] = []
    return st.session_state["session_id"]


def init_messages_state():
    """
    Inicializa el estado de mensajes.
    Si hay un formato antiguo (lista de tuplas), lo convierte al nuevo formato.
    """
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
        return

    # Migración simple: si es lista de tuplas (role, text), conviértelas.
    new_msgs = []
    for msg in st.session_state["messages"]:
        if isinstance(msg, tuple) and len(msg) == 2:
            role, text = msg
            new_msgs.append({"role": role, "text": text, "meta": {}})
        elif isinstance(msg, dict):
            new_msgs.append(msg)
        else:
            # Formato desconocido, lo ignoramos
            continue
    st.session_state["messages"] = new_msgs


def render_chat_tab():
    st.subheader("💬 Chat con el asistente de BOB Subastas")

    session_id = get_session_id()
    init_messages_state()

    # Flag de sesión: ¿esta conversación ya fue cerrada?
    chat_closed = st.session_state.get("chat_closed", False)

    # Mostrar historial
    for msg in st.session_state["messages"]:
        role = msg.get("role", "assistant")
        text = msg.get("text", "")
        meta = msg.get("meta", {})

        with st.chat_message(role):
            st.markdown(text)

            if role == "assistant" and meta:
                lead_score = meta.get("lead_score")
                lead_score_numeric = meta.get("lead_score_numeric")  # 👈 NUEVO
                response_time_ms = meta.get("response_time_ms")
                used_context = meta.get("used_context")

                info_parts = []
                if lead_score:
                    label = f"🏷️ Lead: **{lead_score.upper()}**"
                    if lead_score_numeric is not None:
                        label += f" ({lead_score_numeric}/100)"
                    info_parts.append(label)
                if response_time_ms is not None:
                    info_parts.append(f"⏱️ {response_time_ms:.0f} ms")
                if used_context is not None:
                    info_parts.append(
                        "📚 Contexto: **sí**" if used_context else "📚 Contexto: **no**"
                    )

                if info_parts:
                    st.caption(" · ".join(info_parts))

    # -----------------------
    # Input del usuario
    # -----------------------
    prompt = None
    if not chat_closed:
        prompt = st.chat_input("Escribe tu pregunta sobre BOB Subastas...")
    else:
        st.info(
            "✅ Ya registramos tus datos y un asesor de BOB Subastas "
            "se pondrá en contacto contigo. Esta conversación está cerrada."
        )

    if prompt:
        user_msg = {"role": "user", "text": prompt, "meta": {}}
        st.session_state["messages"].append(user_msg)

        with st.chat_message("user"):
            st.markdown(prompt)

        payload = {"session_id": session_id, "message": prompt}

        try:
            resp = requests.post(
                f"{BACKEND_URL}/api/v1/chat/", json=payload, timeout=180
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("answer", "Error al leer la respuesta del backend.")
            lead_score = data.get("lead_score")
            lead_score_numeric = data.get("lead_score_numeric")  # 👈 NUEVO
            response_time_ms = data.get("response_time_ms")
            used_context = data.get("used_context", False)
        except Exception as e:
            answer = f"Error al conectar con el backend: {e}"
            lead_score = None
            lead_score_numeric = None
            response_time_ms = None
            used_context = None

        bot_meta = {
            "lead_score": lead_score,
            "lead_score_numeric": lead_score_numeric,  # 👈 NUEVO
            "response_time_ms": response_time_ms,
            "used_context": used_context,
        }

        bot_msg = {"role": "assistant", "text": answer, "meta": bot_meta}
        st.session_state["messages"].append(bot_msg)

        with st.chat_message("assistant"):
            st.markdown(answer)
            info_parts = []
            if lead_score:
                label = f"🏷️ Lead: **{lead_score.upper()}**"
                if lead_score_numeric is not None:
                    label += f" ({lead_score_numeric}/100)"
                info_parts.append(label)
            if response_time_ms is not None:
                info_parts.append(f"⏱️ {response_time_ms:.0f} ms")
            if used_context is not None:
                info_parts.append(
                    "📚 Contexto: **sí**" if used_context else "📚 Contexto: **no**"
                )
            if info_parts:
                st.caption(" · ".join(info_parts))

    # 👉 Bloque de derivación: si el último mensaje del bot es CALIENTE
    # y el chat NO está cerrado todavía
    last_bot_meta = None
    for msg in reversed(st.session_state["messages"]):
        if msg.get("role") == "assistant":
            last_bot_meta = msg.get("meta", {})
            break

    if last_bot_meta and not st.session_state.get("chat_closed", False):
        lead_score = (last_bot_meta.get("lead_score") or "").lower()
        if lead_score == "caliente":
            st.markdown("---")
            st.info(
                "🟢 Parece que tienes **alta intención de compra**. "
                "Para que un asesor comercial te contacte, por favor completa tus datos."
            )

            with st.form("lead_contact_form"):
                col1, col2 = st.columns(2)
                with col1:
                    nombres = st.text_input("Nombres *")
                with col2:
                    apellidos = st.text_input("Apellidos *")

                col3, col4 = st.columns(2)
                with col3:
                    dni = st.text_input("DNI (opcional)")
                with col4:
                    ciudad = st.text_input("Ciudad *")

                telefono = st.text_input("Teléfono *")
                correo_electronico = st.text_input("Correo electrónico *")

                submitted = st.form_submit_button("Quiero que un asesor me contacte")

                if submitted:
                    # Validaciones básicas
                    errores = []
                    if not nombres.strip():
                        errores.append("Debes ingresar tus nombres.")
                    if not apellidos.strip():
                        errores.append("Debes ingresar tus apellidos.")
                    if not ciudad.strip():
                        errores.append("Debes ingresar tu ciudad.")
                    if not telefono.strip():
                        errores.append("Debes ingresar tu teléfono.")
                    if not correo_electronico.strip():
                        errores.append("Debes ingresar tu correo electrónico.")
                    elif "@" not in correo_electronico:
                        errores.append("El correo electrónico no parece válido.")

                    if dni and not dni.isdigit():
                        errores.append("El DNI debe contener solo dígitos.")

                    if errores:
                        for err in errores:
                            st.warning(err)
                    else:
                        payload = {
                            "session_id": session_id,
                            "channel": "web",
                            "lead_score": lead_score,
                            "nombres": nombres.strip(),
                            "apellidos": apellidos.strip(),
                            "dni": dni.strip() or None,
                            "telefono": telefono.strip(),
                            "correo_electronico": correo_electronico.strip(),
                            "ciudad": ciudad.strip(),
                        }
                        try:
                            r = requests.post(
                                f"{BACKEND_URL}/api/v1/leads/",
                                json=payload,
                                timeout=10,
                            )
                            r.raise_for_status()
                            st.success(
                                "✅ Gracias. Un asesor de BOB Subastas "
                                "se pondrá en contacto contigo."
                            )
                            # 👇 Marcamos el chat como cerrado
                            st.session_state["chat_closed"] = True
                        except Exception as e:
                            st.error(f"No se pudo registrar tu lead: {e}")


def render_metrics_tab():
    st.subheader("📊 Métricas del agente")

    st.caption(
        "Resumen calculado a partir de las interacciones guardadas en SQLite "
        "mediante el endpoint `/api/v1/metrics/summary`."
    )

    try:
        resp = requests.get(f"{BACKEND_URL}/api/v1/metrics/summary", timeout=10)
        resp.raise_for_status()
        m = resp.json()
    except Exception as e:
        st.error(f"No se pudieron cargar las métricas: {e}")
        return

    total_interactions = m.get("total_interactions", 0)
    total_sessions = m.get("total_sessions", 0)
    avg_response_time_ms = m.get("avg_response_time_ms")
    pct_hot_leads = m.get("pct_hot_leads", 0.0)
    pct_resolved_without_derivation = m.get("pct_resolved_without_derivation", 0.0)
    context_coverage_rate = m.get("context_coverage_rate", 0.0)
    avg_interactions_per_session = m.get("avg_interactions_per_session")

    # Bloque principal de KPIs
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Interacciones totales", total_interactions)
        st.metric("Sesiones únicas", total_sessions)
    with col2:
        if avg_response_time_ms is not None:
            st.metric(
                "Tiempo prom. de respuesta",
                f"{avg_response_time_ms:.0f} ms",
            )
        else:
            st.metric("Tiempo prom. de respuesta", "N/A")
        if avg_interactions_per_session is not None:
            st.metric(
                "Interacciones por sesión",
                f"{avg_interactions_per_session:.1f}",
            )
        else:
            st.metric("Interacciones por sesión", "N/A")
    with col3:
        st.metric(
            "% leads calientes",
            f"{pct_hot_leads:.1f} %",
        )
        st.metric(
            "% resueltas sin derivar",
            f"{pct_resolved_without_derivation:.1f} %",
        )

    st.markdown("---")

    # Barras de cobertura y contexto
    st.markdown("### Cobertura de contexto y calidad de respuestas")

    col4, col5 = st.columns(2)
    with col4:
        st.write("**Cobertura de contexto**")
        st.write(
            f"Porcentaje de interacciones donde el agente encontró contexto relevante "
            f"en Chroma por encima del umbral: **{context_coverage_rate:.1f} %**"
        )
        st.progress(min(int(context_coverage_rate), 100))

    with col5:
        st.write("**Notas de interpretación**")
        st.markdown(
            """
            - Una **cobertura alta** indica que la base de conocimiento está respondiendo a la mayoría de preguntas.
            - Un **% alto de leads calientes** sugiere que las campañas están trayendo leads con clara intención de compra.
            - El **tiempo promedio de respuesta** es clave para la experiencia del lead.
            """
        )

    st.markdown("---")
    st.caption(
        "Estas métricas se recalculan cada vez que se realiza una nueva interacción "
        "en el endpoint `/api/v1/chat/`."
    )


def render_advisor_tab():
    st.subheader("👨‍💼 Panel de asesor comercial")

    st.caption(
        "Revisa los leads **calientes** (incluyendo los importados desde Excel) "
        "y su historial de conversación con el asistente."
    )

    col_leads, col_chat = st.columns([1, 2])

    # ---------------------------
    # Columna izquierda: LEADS CALIENTES (con filtro por canal)
    # ---------------------------
    with col_leads:
        st.markdown("### Leads calientes")

        filtro_channel = st.selectbox(
            "Canal",
            options=["todos", "web", "whatsapp", "excel_import"],
            format_func=lambda x: "Todos los canales" if x == "todos" else x,
        )

        params = {
            "lead_score": "caliente",  # 👈 solo calientes
            "status": "open",          # 👈 solo abiertos
            "limit": 200,
        }

        if filtro_channel != "todos":
            params["channel"] = filtro_channel

        try:
            resp = requests.get(
                f"{BACKEND_URL}/api/v1/leads",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            leads = resp.json()
        except Exception as e:
            st.error(f"No se pudieron cargar los leads calientes: {e}")
            return

        if not leads:
            st.info("No hay leads calientes con esos filtros.")
            return

        # Dropdown para seleccionar un lead específico
        def build_full_name(l):
            nombres = (l.get("nombres") or "").strip()
            apellidos = (l.get("apellidos") or "").strip()
            full = f"{nombres} {apellidos}".strip()
            return full or "Sin nombre"

        def build_contact_label(l):
            tel = (l.get("telefono") or "").strip()
            mail = (l.get("correo_electronico") or "").strip()
            partes = []
            if tel:
                partes.append(f"Tel: {tel}")
            if mail:
                partes.append(f"Email: {mail}")
            return " / ".join(partes) if partes else "Sin contacto"

        options = [
            f"#{l['id']} · {build_full_name(l)} · "
            f"{l.get('channel')} · {build_contact_label(l)}"
            for l in leads
        ]

        selected_label = st.selectbox("Selecciona un lead", options)
        selected_index = options.index(selected_label)
        selected_lead = leads[selected_index]

        st.markdown("---")
        st.markdown("**Detalle del lead seleccionado:**")
        nombres = (selected_lead.get("nombres") or "").strip()
        apellidos = (selected_lead.get("apellidos") or "").strip()
        full_name = (f"{nombres} {apellidos}".strip()) or "—"

        st.markdown(f"- **ID**: `{selected_lead['id']}`")
        st.markdown(f"- **Session ID**: `{selected_lead['session_id']}`")
        st.markdown(f"- **Canal**: `{selected_lead.get('channel')}`")
        st.markdown(f"- **Nombre**: {full_name}")
        st.markdown(f"- **DNI**: {selected_lead.get('dni') or '—'}")
        st.markdown(f"- **Teléfono**: {selected_lead.get('telefono') or '—'}")
        st.markdown(f"- **Correo**: {selected_lead.get('correo_electronico') or '—'}")
        st.markdown(f"- **Ciudad**: {selected_lead.get('ciudad') or '—'}")
        st.markdown(f"- **Lead score**: {selected_lead.get('lead_score') or '—'}")
        st.markdown(f"- **Estado**: {selected_lead.get('status')}")
        st.markdown(f"- **Creado**: {selected_lead.get('created_at')}")


    # ---------------------------
    # Columna derecha: HISTORIAL DE CHAT
    # ---------------------------
    with col_chat:
        st.markdown("### Historial de conversación")

        session_id = selected_lead.get("session_id")

        try:
            resp_int = requests.get(
                f"{BACKEND_URL}/api/v1/interactions",
                params={"session_id": session_id, "limit": 100},
                timeout=10,
            )
            resp_int.raise_for_status()
            interactions = resp_int.json()
        except Exception as e:
            st.error(f"No se pudo cargar el historial de chat: {e}")
            return

        if not interactions:
            st.info(
                "Este lead no tiene historial de conversación registrado. "
                "Por ejemplo, puede venir del Excel sin haber chateado aún."
            )
            return

        # Ordenar cronológicamente (de más antiguo a más nuevo)
        interactions_sorted = sorted(interactions, key=lambda x: x["created_at"])

        for it in interactions_sorted:
            st.markdown(f"🕒 `{it['created_at']}`")
            st.markdown(f"👤 **Usuario:** {it['user_message']}")
            st.markdown(f"🤖 **Bot:** {it['bot_response']}")
            lead_label = it.get("lead_score") or "-"
            lead_numeric = it.get("lead_score_numeric", None)
            if lead_numeric is not None:
                score_str = f"{lead_label} ({lead_numeric}/100)"
            else:
                score_str = f"{lead_label}"
            st.caption(
                f"Lead score: {score_str} · "
                f"Contexto: {'sí' if it.get('used_context') else 'no'} · "
                f"{it['response_time_ms']:.0f} ms"
            )
            st.markdown("---")


def main():
    st.set_page_config(page_title="BOB Subastas - IA", page_icon="🚗", layout="wide")
    st.title("BOB Subastas - Asistente IA (Demo)")

    tab_chat, tab_metrics, tab_advisor = st.tabs(
        ["💬 Chat", "📊 Métricas", "👨‍💼 Asesor"]
    )

    with tab_chat:
        render_chat_tab()

    with tab_metrics:
        render_metrics_tab()

    with tab_advisor:
        render_advisor_tab()


if __name__ == "__main__":
    main()
