import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.app_settings import AppSettings
from backend.app.models.remembered_device import RememberedDevice
from backend.app.core.security import build_access_token, create_access_token, get_password_hash, verify_password
from backend.app.models.user import User
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.schemas.auth import RegisterRequest


class AuthService:
    ALLOWED_THEME_PREFERENCES = {"light", "dark", "system"}
    ALLOWED_SURFACE_STYLES = {"clean", "soft", "contrast"}
    ALLOWED_DENSITY_PREFERENCES = {"comfortable", "compact"}
    ALLOWED_DECORATION_STYLES = {"none", "glow", "petals"}
    ALLOWED_TASK_CATEGORY_BUTTON_COLOR_MODES = {"match", "custom"}
    APPROVAL_PENDING = "pending"
    APPROVAL_APPROVED = "approved"
    APPROVAL_REJECTED = "rejected"
    EASY_LOGON_TOKEN_DAYS = 30

    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email.lower().strip()))

    def get_app_settings(self) -> AppSettings:
        settings = self.db.get(AppSettings, 1)
        if settings:
            return settings

        settings = AppSettings(id=1)
        self.db.add(settings)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def get_auto_approve_registrations(self) -> bool:
        return self.get_app_settings().auto_approve_registrations

    def get_public_registration_enabled(self) -> bool:
        return self.get_app_settings().public_registration_enabled

    def get_login_theme_preference(self) -> str:
        selected = (self.get_app_settings().login_theme_preference or "light").strip().lower()
        return selected if selected in self.ALLOWED_THEME_PREFERENCES else "light"

    def register(
        self,
        payload: RegisterRequest,
        is_admin: bool = False,
        require_approval: bool | None = None,
        show_in_member_lists: bool | None = None,
    ) -> User:
        existing = self.get_by_email(payload.email)
        if existing:
            raise ValueError("Email already exists.")

        if require_approval is None:
            require_approval = not self.get_auto_approve_registrations()

        approved = is_admin or not require_approval
        app_settings = self.get_app_settings()
        user = User(
            email=payload.email.lower().strip(),
            full_name=payload.full_name.strip(),
            hashed_password=get_password_hash(payload.password),
            is_admin=is_admin,
            approval_status=self.APPROVAL_APPROVED if approved else self.APPROVAL_PENDING,
            show_in_member_lists=(not is_admin) if show_in_member_lists is None else show_in_member_lists,
        )
        self.db.add(user)
        self.db.flush()

        default_capacity = app_settings.registration_default_capacity_points
        if not is_admin and default_capacity is not None:
            self.db.add(UserDailyCapacity(user_id=user.id, daily_capacity_points=default_capacity))

        self.db.commit()
        self.db.refresh(user)
        return user

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.get_by_email(email)
        if not user or not user.is_active:
            return None
        if user.approval_status != self.APPROVAL_APPROVED:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def get_login_denial_reason(self, email: str, password: str) -> str | None:
        user = self.get_by_email(email)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return "This account is inactive."
        if user.approval_status == self.APPROVAL_PENDING:
            return "Your account is pending admin approval."
        if user.approval_status == self.APPROVAL_REJECTED:
            return "Your registration request was declined."
        return None

    def issue_token(self, user: User) -> str:
        return create_access_token(subject=str(user.id))

    def issue_token_with_expiry(self, user: User) -> tuple[str, datetime]:
        return build_access_token(subject=str(user.id))

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _hash_remembered_device_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_remembered_device(self, user: User, *, user_agent: str | None = None) -> tuple[str, RememberedDevice]:
        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(48)
        device = RememberedDevice(
            user_id=user.id,
            token_hash=self._hash_remembered_device_token(token),
            user_agent=(user_agent or "")[:500] or None,
            expires_at=now + timedelta(days=self.EASY_LOGON_TOKEN_DAYS),
        )
        self.db.add(device)
        self.db.commit()
        self.db.refresh(device)
        return token, device

    def get_valid_remembered_device(self, token: str | None) -> RememberedDevice | None:
        if not token:
            return None

        device = self.db.scalar(
            select(RememberedDevice).where(
                RememberedDevice.token_hash == self._hash_remembered_device_token(token),
                RememberedDevice.revoked_at.is_(None),
            )
        )
        if not device:
            return None

        now = datetime.now(timezone.utc)
        if self._as_utc(device.expires_at) <= now:
            device.revoked_at = now
            self.db.add(device)
            self.db.commit()
            return None

        user = device.user
        if not user or not user.is_active or user.approval_status != self.APPROVAL_APPROVED:
            return None
        return device

    def authenticate_remembered_device(self, token: str | None) -> User | None:
        device = self.get_valid_remembered_device(token)
        if not device:
            return None

        now = datetime.now(timezone.utc)
        device.last_used_at = now
        device.expires_at = now + timedelta(days=self.EASY_LOGON_TOKEN_DAYS)
        device.user.last_activity_at = now
        self.db.add(device)
        self.db.add(device.user)
        self.db.commit()
        self.db.refresh(device.user)
        return device.user

    def revoke_remembered_device_token(self, token: str | None) -> bool:
        if not token:
            return False

        device = self.db.scalar(
            select(RememberedDevice).where(
                RememberedDevice.token_hash == self._hash_remembered_device_token(token),
                RememberedDevice.revoked_at.is_(None),
            )
        )
        if not device:
            return False

        device.revoked_at = datetime.now(timezone.utc)
        self.db.add(device)
        self.db.commit()
        return True

    def touch_activity(self, user: User) -> None:
        user.last_activity_at = datetime.now(timezone.utc)
        self.db.add(user)
        self.db.commit()

    def update_theme_preference(self, user: User, theme_preference: str) -> User:
        selected = theme_preference.strip().lower()
        if selected not in self.ALLOWED_THEME_PREFERENCES:
            raise ValueError("Invalid theme preference.")
        user.theme_preference = selected
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_appearance_preferences(
        self,
        user: User,
        *,
        theme_preference: str,
        accent_color: str,
        overdue_color: str,
        recurring_color: str,
        in_progress_color: str,
        unassigned_color: str,
        task_category_button_color_mode: str,
        task_category_overdue_color: str,
        task_category_up_next_color: str,
        task_category_later_color: str,
        task_category_unassigned_color: str,
        task_category_in_progress_color: str,
        task_category_completed_color: str,
        surface_style: str,
        density_preference: str,
        decoration_style: str,
    ) -> User:
        selected_theme = theme_preference.strip().lower()
        if selected_theme not in self.ALLOWED_THEME_PREFERENCES:
            raise ValueError("Invalid theme preference.")

        selected_surface_style = surface_style.strip().lower()
        if selected_surface_style not in self.ALLOWED_SURFACE_STYLES:
            raise ValueError("Invalid surface style.")

        selected_density = density_preference.strip().lower()
        if selected_density not in self.ALLOWED_DENSITY_PREFERENCES:
            raise ValueError("Invalid density preference.")

        selected_decoration = decoration_style.strip().lower()
        if selected_decoration not in self.ALLOWED_DECORATION_STYLES:
            raise ValueError("Invalid decoration style.")

        selected_task_button_mode = task_category_button_color_mode.strip().lower()
        if selected_task_button_mode not in self.ALLOWED_TASK_CATEGORY_BUTTON_COLOR_MODES:
            raise ValueError("Invalid tasks category button color mode.")

        user.theme_preference = selected_theme
        user.accent_color = self._normalize_hex_color(accent_color)
        user.overdue_color = self._normalize_hex_color(overdue_color)
        user.recurring_color = self._normalize_hex_color(recurring_color)
        user.in_progress_color = self._normalize_hex_color(in_progress_color)
        user.unassigned_color = self._normalize_hex_color(unassigned_color)
        user.task_category_button_color_mode = selected_task_button_mode
        user.task_category_overdue_color = self._normalize_hex_color(task_category_overdue_color)
        user.task_category_up_next_color = self._normalize_hex_color(task_category_up_next_color)
        user.task_category_later_color = self._normalize_hex_color(task_category_later_color)
        user.task_category_unassigned_color = self._normalize_hex_color(task_category_unassigned_color)
        user.task_category_in_progress_color = self._normalize_hex_color(task_category_in_progress_color)
        user.task_category_completed_color = self._normalize_hex_color(task_category_completed_color)
        user.surface_style = selected_surface_style
        user.density_preference = selected_density
        user.decoration_style = selected_decoration
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    @staticmethod
    def _normalize_hex_color(value: str) -> str:
        selected = value.strip().lower()
        if len(selected) != 7 or not selected.startswith("#"):
            raise ValueError("Colors must use the #RRGGBB format.")
        try:
            int(selected[1:], 16)
        except ValueError as exc:
            raise ValueError("Colors must use the #RRGGBB format.") from exc
        return selected
