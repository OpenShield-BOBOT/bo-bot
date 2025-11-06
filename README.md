# 🤖 BOBot AI Agent  
**Hackatón SomosBOB 2025 — Edición Virtual**

> 🚀 Backend del agente conversacional inteligente que atiende, califica y deriva leads de BOB Subastas.

![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Gemini](https://img.shields.io/badge/Google%20Gemini-IA-4285F4?logo=google)
![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG%20Storage-FF69B4)
![Twilio](https://img.shields.io/badge/Twilio-WhatsApp%20Integration-EE0000)

---

## 🧠 Descripción

**BOB Subastas AI Agent** es un **asistente virtual con IA generativa** creado para **automatizar la atención de leads** en las campañas de **autos y maquinaria usada** de [somosbob.com](https://www.somosbob.com/).

El agente interpreta mensajes entrantes (por chat o WhatsApp), **responde preguntas frecuentes**, **evalúa la intención de compra** y **deriva automáticamente los leads calientes** al equipo comercial.

---

## 🎯 Objetivos

- 🗣️ **Responder FAQs** sobre subastas, garantías y pagos.  
- 🤖 **Interpretar mensajes reales** de usuarios desde WhatsApp o web.  
- 🔍 **Recuperar contexto (RAG)** desde la base de conocimiento y catálogo de vehículos.  
- 🔥 **Evaluar la intención de compra (lead scoring)** usando criterios oficiales del hackatón.  
- 📲 **Derivar automáticamente leads calientes** al asesor vía Twilio.

---

## 🧩 Arquitectura General

```
┌────────────────────────────────────────┐
│             Usuario final              │
│ (Web Chat o WhatsApp Twilio)           │
└────────────────────────────────────────┘
                    │
                    ▼
        ┌─────────────────────┐
        │ FastAPI Backend     │
        │  (bo-bot)           │
        ├─────────────────────┤
        │ /chat → RAG + Scoring
        │ /twilio/whatsapp → Webhook
        │ /metrics → KPIs
        │ /vehicles → Catálogo
        └─────────────────────┘
                    │
                    ▼
 ┌──────────────┬──────────────┬──────────────┐
 │ SQLite (DB)  │ ChromaDB (RAG)│ Gemini (LLM) │
 │ Leads + Logs │ Embeddings    │ Respuestas    │
 └──────────────┴──────────────┴──────────────┘
```

---

## ⚙️ Tecnologías Clave

| Área | Tecnología | Rol |
|------|-------------|-----|
| Backend API | **FastAPI** | Framework principal (REST + Webhook) |
| Base de datos | **SQLite / SQLModel** | Leads, Interacciones, Vehículos |
| IA Generativa | **Gemini 2.5 Flash** | Respuestas y scoring |
| Embeddings | **Gemini Embedding 001** | RAG (ChromaDB) |
| Vector Store | **ChromaDB** | Almacenamiento contextual |
| Mensajería | **Twilio WhatsApp API** | Entrada y salida de mensajes |
| Persistencia | **SQLAlchemy + Pydantic** | Modelos y validación |
| Scripts | Python CLI | Ingesta de datos y entrenamiento local |

---

## 🧬 Estructura del Proyecto

```
bo-bot/
├─ backend/
│  ├─ app/
│  │  ├─ api/v1/
│  │  │  ├─ chat.py              # Endpoint de conversación (RAG)
│  │  │  ├─ twilio_whatsapp.py   # Webhook de WhatsApp
│  │  │  ├─ metrics.py           # Indicadores y KPIs
│  │  │  ├─ leads.py             # CRUD de leads
│  │  │  ├─ vehicles.py          # Catálogo de autos/maquinaria
│  │  │  └─ interactions.py      # Historial de sesiones
│  │  ├─ core/                   # Scoring, config y lógica base
│  │  ├─ rag/                    # Pipeline RAG (Gemini + Chroma)
│  │  ├─ integrations/           # Cliente Twilio
│  │  ├─ services/               # Servicios BOB y vehículos
│  │  ├─ db/                     # Modelos y conexión SQLite
│  │  └─ schemas/                # DTOs / Pydantic
├─ data/
│  ├─ chroma_db/                 # Base vectorial
│  ├─ bob_agent.db               # DB SQLite
│  ├─ hackathon_data.csv         # Catálogo de vehículos
│  ├─ criterios_de_score.txt     # Criterios oficiales de scoring
│  └─ raw/faqs_bob.csv           # FAQs originales
├─ scripts/
│  ├─ ingest_knowledge_base.py   # Genera embeddings (RAG)
│  ├─ load_vehicles_from_csv.py  # Carga el catálogo en SQLite
│  └─ load_leads_from_excel.py   # Carga leads ficticios
└─ requirements.txt
```

---

## 🚀 Instalación y Uso

```bash
git clone https://github.com/<tuusuario>/bo-bot.git
cd bo-bot
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Crea un archivo `.env`:

```env
GEMINI_API_KEY=tu_api_key
SQLITE_URL=sqlite:///./data/bob_agent.db
CHROMA_DB_DIR=./data/chroma_db
CHROMA_COLLECTION_NAME=bob_knowledge_base
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
```

Inicializa datos:

```bash
python scripts/load_vehicles_from_csv.py
python scripts/ingest_knowledge_base.py
uvicorn backend.app.main:app --reload
```

---

## 💬 Endpoints Principales

| Endpoint | Descripción |
|-----------|--------------|
| `POST /api/v1/chat` | Chat principal (RAG + Scoring) |
| `POST /api/v1/twilio/whatsapp` | Webhook para mensajes de WhatsApp |
| `GET /api/v1/metrics/summary` | Métricas generales del agente |
| `GET /api/v1/leads` | Listado y filtro de leads |
| `GET /api/v1/vehicles/list` | Catálogo de autos/maquinaria |

---

## 📈 Roadmap

- ✅ Módulo de RAG embebido (Chroma + Gemini)  
- ✅ Lead Scoring dinámico (criterios .txt)  
- ✅ Integración Twilio  
- 🔜 Dashboard de métricas (Streamlit)  
- 🔜 Autenticación JWT para asesores  

---

## 🧑‍💻 Autor

**Camilo Parraga Piñin**
**Gerardo Chavez Ayala**
**Alexander Aquino Pérez**
Proyecto presentado en la **Hackatón SomosBOB 2025**
