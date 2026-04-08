from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import create_access_token, get_password_hash, verify_password
from backend.app.models.user import User
from backend.app.schemas.auth import RegisterRequest


class AuthService:
    ALLOWED_THEME_PREFERENCES = {"light", "dark", "system"}
    ALLOWED_SURFACE_STYLES = {"clean", "soft", "contrast"}
    ALLOWED_DENSITY_PREFERENCES = {"comfortable", "compact"}
    ALLOWED_DECORATION_STYLES = {"none", "glow", "petals"}
    APPROVAL_PENDING = "pending"
    APPROVAL_APPROVED = "approved"
    APPROVAL_REJECTED = "rejected"

    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(User.email == email.lower().strip()))

    def register(
        self,
        payload: RegisterRequest,
        is_admin: bool = False,
        require_approval: bool = True,
        show_in_member_lists: bool | None = None,
    ) -> User:
        existing = self.get_by_email(payload.email)
        if existing:
            raise ValueError("Email already exists.")

        approved = is_admin or not require_approval
        user = User(
            email=payload.email.lower().strip(),
            full_name=payload.full_name.strip(),
            hashed_password=get_password_hash(payload.password),
            is_admin=is_admin,
            approval_status=self.APPROVAL_APPROVED if approved else self.APPROVAL_PENDING,
            show_in_member_lists=(not is_admin) if show_in_member_lists is None else show_in_member_lists,
        )
        self.db.add(user)
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

        user.theme_preference = selected_theme
        user.accent_color = self._normalize_hex_color(accent_color)
        user.overdue_color = self._normalize_hex_color(overdue_color)
        user.recurring_color = self._normalize_hex_color(recurring_color)
        user.in_progress_color = self._normalize_hex_color(in_progress_color)
        user.unassigned_color = self._normalize_hex_color(unassigned_color)
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
