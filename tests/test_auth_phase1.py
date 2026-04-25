from fastapi.testclient import TestClient

from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.schemas.auth import RegisterRequest
from backend.app.services.admin_settings_service import AdminSettingsService
from backend.app.services.auth_service import AuthService


def setup_module():
    Base.metadata.create_all(bind=engine)


def test_register_and_login_api():
    client = TestClient(app)

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "user1@example.com", "full_name": "User One", "password": "securepass123"},
    )
    assert register.status_code == 201
    assert register.json()["email"] == "user1@example.com"
    assert register.json()["approval_status"] == "pending"

    login = client.post("/api/v1/auth/login", json={"email": "user1@example.com", "password": "securepass123"})
    assert login.status_code == 403
    assert login.json()["detail"] == "Your account is pending admin approval."

    db = SessionLocal()
    try:
        admin = AuthService(db).register(
            RegisterRequest(email="approval-admin@example.com", full_name="Approval Admin", password="securepass123"),
            is_admin=True,
            require_approval=False,
            show_in_member_lists=False,
        )
        assert admin.is_admin is True

        pending_user = AuthService(db).get_by_email("user1@example.com")
        AdminSettingsService(db).approve_user(pending_user.id)
    finally:
        db.close()

    approved_login = client.post("/api/v1/auth/login", json={"email": "user1@example.com", "password": "securepass123"})
    assert approved_login.status_code == 200
    payload = approved_login.json()
    assert payload["access_token"]
    assert payload["token_type"] == "bearer"


def test_dashboard_requires_auth_cookie():
    client = TestClient(app)
    response = client.get("/dashboard")
    assert response.status_code == 401


def test_rejecting_pending_user_deletes_the_account():
    db = SessionLocal()
    try:
        email = "reject-me@example.com"
        service = AuthService(db)
        pending_user = service.register(
            RegisterRequest(email=email, full_name="Reject Me", password="securepass123")
        )

        AdminSettingsService(db).reject_user(pending_user.id)

        deleted_user = AuthService(db).get_by_email(email)
        assert deleted_user is None
    finally:
        db.close()


def test_register_auto_approves_when_setting_is_enabled():
    client = TestClient(app)
    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=True,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "auto-approved@example.com", "full_name": "Auto Approved", "password": "securepass123"},
    )
    assert register.status_code == 201
    assert register.json()["approval_status"] == "approved"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "auto-approved@example.com", "password": "securepass123"},
    )
    assert login.status_code == 200

    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()


def test_register_applies_default_capacity_setting():
    client = TestClient(app)
    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=True,
            login_theme_preference="light",
            registration_default_capacity_points=6,
        )
    finally:
        db.close()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "capacity-user@example.com", "full_name": "Capacity User", "password": "securepass123"},
    )
    assert register.status_code == 201
    assert register.json()["approval_status"] == "approved"

    db = SessionLocal()
    try:
        user = AuthService(db).get_by_email("capacity-user@example.com")
        capacity = db.get(UserDailyCapacity, user.id)
        assert capacity is not None
        assert capacity.daily_capacity_points == 6
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()


def test_pending_registration_keeps_default_capacity_setting():
    client = TestClient(app)
    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=4,
        )
    finally:
        db.close()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "pending-capacity-user@example.com", "full_name": "Pending Capacity", "password": "securepass123"},
    )
    assert register.status_code == 201
    assert register.json()["approval_status"] == "pending"

    db = SessionLocal()
    try:
        user = AuthService(db).get_by_email("pending-capacity-user@example.com")
        capacity = db.get(UserDailyCapacity, user.id)
        assert capacity is not None
        assert capacity.daily_capacity_points == 4
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()


def test_register_api_is_closed_when_public_registration_is_disabled():
    client = TestClient(app)
    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=False,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "closed@example.com", "full_name": "Closed User", "password": "securepass123"},
    )
    assert register.status_code == 403
    assert register.json()["detail"] == "Registration is currently closed."

    db = SessionLocal()
    try:
        AdminSettingsService(db).update_login_access_settings(
            public_registration_enabled=True,
            auto_approve_registrations=False,
            login_theme_preference="light",
            registration_default_capacity_points=None,
        )
    finally:
        db.close()
