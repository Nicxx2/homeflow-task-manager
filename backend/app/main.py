from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.app.api.v1.router import api_router
from backend.app.api.web.router import web_router
from backend.app.core.config import get_settings
from backend.app.db.session import SessionLocal
from backend.app.schemas.auth import RegisterRequest
from backend.app.models.enums import EffortLevel
from backend.app.services.admin_settings_service import AdminSettingsService
from backend.app.services.auth_service import AuthService


def seed_initial_admin() -> None:
    settings = get_settings()
    db: Session = SessionLocal()
    try:
        service = AuthService(db)
        existing = service.get_by_email(settings.initial_admin_email)
        if existing:
            return
        service.register(
            RegisterRequest(
                email=settings.initial_admin_email,
                full_name="System Admin",
                password=settings.initial_admin_password,
            ),
            is_admin=True,
            require_approval=False,
            show_in_member_lists=False,
        )
    finally:
        db.close()


def seed_initial_configs() -> None:
    db: Session = SessionLocal()
    try:
        service = AdminSettingsService(db)
        existing = service.get_effort_configs()
        if existing:
            return
        service.upsert_effort_config(
            {
                EffortLevel.LOW: 2,
                EffortLevel.MEDIUM: 5,
                EffortLevel.HIGH: 8,
            }
        )
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_initial_admin()
    seed_initial_configs()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(api_router)
app.include_router(web_router)


@app.exception_handler(FastAPIHTTPException)
async def http_exception_auth_redirect(request: Request, exc: FastAPIHTTPException):
    if exc.status_code == 401 and not request.url.path.startswith("/api"):
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie("access_token")
        return response
    return await http_exception_handler(request, exc)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
