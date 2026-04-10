from fastapi import APIRouter

from backend.app.api.web.views import router as views_router

web_router = APIRouter()
web_router.include_router(views_router)
