from fastapi import APIRouter

from .chat import router as chat_router
from .metrics import router as metrics_router
from .twilio_whatsapp import router as twilio_router
from .leads import router as leads_router
from .vehicles import router as vehicles_router
from .interactions import router as interactions_router

api_v1_router = APIRouter()
api_v1_router.include_router(chat_router)
api_v1_router.include_router(metrics_router)
api_v1_router.include_router(twilio_router)
api_v1_router.include_router(leads_router)
api_v1_router.include_router(vehicles_router)
api_v1_router.include_router(interactions_router)
