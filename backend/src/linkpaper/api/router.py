from fastapi import APIRouter

from linkpaper.api.routes import chat, conversations, health, papers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
api_router.include_router(
    conversations.router,
    prefix="/conversations",
    tags=["conversations"],
)
