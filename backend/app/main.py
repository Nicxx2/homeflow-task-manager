from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
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
        service.get_app_settings()
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


def _api_error_code(status_code: int, detail) -> str:
    detail_text = detail if isinstance(detail, str) else ""
    if status_code == 401:
        detail_map = {
            "Invalid credentials.": "invalid_credentials",
            "Not authenticated.": "not_authenticated",
            "Invalid token.": "invalid_token",
            "Session expired due to inactivity.": "session_expired",
            "User inactive.": "user_inactive",
        }
        return detail_map.get(detail_text, "unauthenticated")
    if status_code == 403:
        detail_map = {
            "Your account is pending admin approval.": "approval_pending",
            "Your registration request was declined.": "registration_rejected",
        }
        return detail_map.get(detail_text, "forbidden")
    mapping = {
        400: "invalid_request",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
    }
    return mapping.get(status_code, "server_error" if status_code >= 500 else "api_error")


def _api_error_payload(*, status_code: int, detail, errors: list[dict] | None = None) -> dict:
    payload = {
        "detail": detail,
        "code": _api_error_code(status_code, detail),
        "retryable": status_code >= 500,
    }
    if errors:
        payload["errors"] = errors
    return payload


@app.exception_handler(FastAPIHTTPException)
async def http_exception_auth_redirect(request: Request, exc: FastAPIHTTPException):
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exc.status_code,
            content=_api_error_payload(status_code=exc.status_code, detail=exc.detail),
        )
    if exc.status_code == 401 and not request.url.path.startswith("/api"):
        response = RedirectResponse(url="/login", status_code=302)
        response.delete_cookie("access_token")
        return response
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=422,
            content=_api_error_payload(
                status_code=422,
                detail="Validation failed.",
                errors=exc.errors(),
            ),
        )
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, _exc: Exception):
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=500,
            content=_api_error_payload(status_code=500, detail="Internal server error."),
        )
    return PlainTextResponse("Internal Server Error", status_code=500)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
