from fastapi import APIRouter
from app.api.v1.endpoints import auth, profile, chat, history, diagnosis, activities, weather, cooperative

api_router = APIRouter()

api_router.include_router(auth.router,        prefix="/auth",        tags=["🔐 Authentification"])
api_router.include_router(profile.router,     prefix="/profile",     tags=["Profile"])
api_router.include_router(chat.router,        prefix="/chat",        tags=["🤖 Agent IA"])
api_router.include_router(history.router,     prefix="/history",     tags=["📜 Historique"])
api_router.include_router(diagnosis.router,   prefix="/diagnosis",   tags=["📸 Diagnostic Visuel"])
api_router.include_router(activities.router,  prefix="/activities",  tags=["⚡ Activités"])
api_router.include_router(weather.router,     prefix="/weather",     tags=["🌦️ Météo Agricole"])
api_router.include_router(cooperative.router, prefix="/cooperative", tags=["🏢 Gestion Coopérative"])


