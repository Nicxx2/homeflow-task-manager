from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.api.web.views import EASY_LOGON_COOKIE_NAME
from backend.app.core.security import get_password_hash
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.main import app
from backend.app.models.remembered_device import RememberedDevice
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.schemas.auth import RegisterRequest
from backend.app.services.admin_settings_service import AdminSettingsService
from backend.app.services.auth_service import AuthService


WEB_AUTH_TEST_PASSWORD = "securepass123"


def _ensure_web_auth_user(email: str, full_name: str) -> None:
    db = SessionLocal()
    try:
        service = AuthService(db)
        user = service.get_by_email(email)
        if user is None:
            user = service.register(
                RegisterRequest(email=email, full_name=full_name, password=WEB_AUTH_TEST_PASSWORD),
                require_approval=False,
            )
        else:
            user.full_name = full_name
            user.hashed_password = get_password_hash(WEB_AUTH_TEST_PASSWORD)
            user.is_active = True
            user.approval_status = AuthService.APPROVAL_APPROVED
            db.add(user)
            db.flush()

        for remembered_device in db.scalars(
            select(RememberedDevice).where(RememberedDevice.user_id == user.id)
        ).all():
            db.delete(remembered_device)
        db.commit()
    finally:
        db.close()


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
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


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


def test_web_easy_logon_profile_can_continue_replace_and_remove():
    first_email = "easy-web-one@example.com"
    second_email = "easy-web-two@example.com"
    _ensure_web_auth_user(first_email, "Easy Web One")
    _ensure_web_auth_user(second_email, "Easy Web Two")
    client = TestClient(app)

    login = client.post(
        "/login",
        data={"email": first_email, "password": WEB_AUTH_TEST_PASSWORD, "enable_easy_logon": "on"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    first_easy_logon_token = client.cookies.get(EASY_LOGON_COOKIE_NAME)
    assert first_easy_logon_token

    client.post("/logout", follow_redirects=False)
    profile = client.get("/login")
    assert profile.status_code == 200
    assert "Easy Web One" in profile.text
    assert "Use another account" in profile.text
    assert 'id="email"' not in profile.text

    manual = client.get("/login?manual=1")
    assert manual.status_code == 200
    assert 'id="email"' in manual.text

    second_login_without_opt_in = client.post(
        "/login",
        data={"email": second_email, "password": WEB_AUTH_TEST_PASSWORD},
        follow_redirects=False,
    )
    assert second_login_without_opt_in.status_code == 302
    client.post("/logout", follow_redirects=False)
    still_first_profile = client.get("/login")
    assert "Easy Web One" in still_first_profile.text
    assert "Easy Web Two" not in still_first_profile.text

    second_login_with_opt_in = client.post(
        "/login",
        data={"email": second_email, "password": WEB_AUTH_TEST_PASSWORD, "enable_easy_logon": "on"},
        follow_redirects=False,
    )
    assert second_login_with_opt_in.status_code == 302
    second_easy_logon_token = client.cookies.get(EASY_LOGON_COOKIE_NAME)
    assert second_easy_logon_token and second_easy_logon_token != first_easy_logon_token
    db = SessionLocal()
    try:
        assert AuthService(db).get_valid_remembered_device(first_easy_logon_token) is None
    finally:
        db.close()
    client.post("/logout", follow_redirects=False)
    replaced_profile = client.get("/login")
    assert "Easy Web Two" in replaced_profile.text
    assert "Easy Web One" not in replaced_profile.text

    easy_login = client.post("/login/easy", follow_redirects=False)
    assert easy_login.status_code == 302
    assert client.cookies.get("access_token")

    remove = client.post("/login/easy/remove", follow_redirects=False)
    assert remove.status_code == 302
    assert not client.cookies.get(EASY_LOGON_COOKIE_NAME)
    db = SessionLocal()
    try:
        assert AuthService(db).get_valid_remembered_device(second_easy_logon_token) is None
    finally:
        db.close()
    no_profile = client.get("/login")
    assert 'id="email"' in no_profile.text
    assert "Easy Web Two" not in no_profile.text


def test_web_easy_logon_success_renews_expiry_and_cookie():
    email = "easy-web-renew@example.com"
    _ensure_web_auth_user(email, "Easy Web Renew")
    client = TestClient(app)

    login = client.post(
        "/login",
        data={"email": email, "password": WEB_AUTH_TEST_PASSWORD, "enable_easy_logon": "on"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    easy_logon_token = client.cookies.get(EASY_LOGON_COOKIE_NAME)
    assert easy_logon_token
    client.post("/logout", follow_redirects=False)

    db = SessionLocal()
    try:
        service = AuthService(db)
        device = service.get_valid_remembered_device(easy_logon_token)
        assert device is not None
        device.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        db.add(device)
        db.commit()
    finally:
        db.close()

    easy_login = client.post("/login/easy", follow_redirects=False)
    assert easy_login.status_code == 302
    set_cookie_headers = easy_login.headers.get_list("set-cookie")
    assert any(
        header.startswith(f"{EASY_LOGON_COOKIE_NAME}=") and "Max-Age=2592000" in header
        for header in set_cookie_headers
    )

    db = SessionLocal()
    try:
        device = AuthService(db).get_valid_remembered_device(easy_logon_token)
        assert device is not None
        assert AuthService._as_utc(device.expires_at) > datetime.now(timezone.utc) + timedelta(days=29)
        assert device.last_used_at is not None
    finally:
        db.close()


def test_web_easy_logon_failed_password_does_not_create_device():
    email = "easy-web-failed@example.com"
    _ensure_web_auth_user(email, "Easy Web Failed")
    client = TestClient(app)

    failed = client.post(
        "/login",
        data={"email": email, "password": "wrongpass123", "enable_easy_logon": "on"},
        follow_redirects=False,
    )
    assert failed.status_code == 401
    assert not client.cookies.get(EASY_LOGON_COOKIE_NAME)

    db = SessionLocal()
    try:
        user = AuthService(db).get_by_email(email)
        device_count = db.scalar(
            select(func.count()).select_from(RememberedDevice).where(RememberedDevice.user_id == user.id)
        )
        assert device_count == 0
    finally:
        db.close()


def test_web_easy_logon_inactive_user_falls_back_to_password_login():
    email = "easy-web-inactive@example.com"
    _ensure_web_auth_user(email, "Easy Web Inactive")
    client = TestClient(app)

    login = client.post(
        "/login",
        data={"email": email, "password": WEB_AUTH_TEST_PASSWORD, "enable_easy_logon": "on"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    first_easy_logon_token = client.cookies.get(EASY_LOGON_COOKIE_NAME)
    assert first_easy_logon_token
    client.post("/logout", follow_redirects=False)

    db = SessionLocal()
    try:
        user = AuthService(db).get_by_email(email)
        user.is_active = False
        db.add(user)
        db.commit()
    finally:
        db.close()

    profile = client.get("/login")
    assert profile.status_code == 200
    assert "Easy Web Inactive" not in profile.text
    assert 'id="email"' in profile.text
    assert not client.cookies.get(EASY_LOGON_COOKIE_NAME)

def test_web_easy_logon_manual_switch_keeps_existing_profile():
    email = "easy-web-manual@example.com"
    _ensure_web_auth_user(email, "Easy Web Manual")
    client = TestClient(app)

    login = client.post(
        "/login",
        data={"email": email, "password": WEB_AUTH_TEST_PASSWORD, "enable_easy_logon": "on"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    easy_logon_token = client.cookies.get(EASY_LOGON_COOKIE_NAME)
    assert easy_logon_token
    client.post("/logout", follow_redirects=False)

    manual = client.get("/login?manual=1")
    assert manual.status_code == 200
    assert 'id="email"' in manual.text
    assert "Easy Web Manual" not in manual.text

    profile = client.get("/login")
    assert profile.status_code == 200
    assert "Easy Web Manual" in profile.text
    assert 'id="email"' not in profile.text


def test_web_easy_logon_expired_token_is_revoked_and_cleared():
    email = "easy-web-expired@example.com"
    _ensure_web_auth_user(email, "Easy Web Expired")
    client = TestClient(app)

    login = client.post(
        "/login",
        data={"email": email, "password": WEB_AUTH_TEST_PASSWORD, "enable_easy_logon": "on"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    easy_logon_token = client.cookies.get(EASY_LOGON_COOKIE_NAME)
    assert easy_logon_token
    client.post("/logout", follow_redirects=False)

    db = SessionLocal()
    try:
        device = AuthService(db).get_valid_remembered_device(easy_logon_token)
        assert device is not None
        device.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.add(device)
        db.commit()
    finally:
        db.close()

    profile = client.get("/login")
    assert profile.status_code == 200
    assert "Easy Web Expired" not in profile.text
    assert 'id="email"' in profile.text
    assert not client.cookies.get(EASY_LOGON_COOKIE_NAME)

    db = SessionLocal()
    try:
        assert AuthService(db).get_valid_remembered_device(easy_logon_token) is None
    finally:
        db.close()


def test_web_easy_logon_missing_or_invalid_token_falls_back_to_password_login():
    client = TestClient(app)

    missing = client.post("/login/easy", follow_redirects=False)
    assert missing.status_code == 401
    assert 'id="email"' in missing.text

    client.cookies.set(EASY_LOGON_COOKIE_NAME, "not-a-valid-token", domain="testserver.local", path="/")
    invalid = client.post("/login/easy", follow_redirects=False)
    assert invalid.status_code == 401
    assert 'id="email"' in invalid.text
    assert not client.cookies.get(EASY_LOGON_COOKIE_NAME)
