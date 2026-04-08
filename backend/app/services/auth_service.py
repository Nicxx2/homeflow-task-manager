from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import create_access_token, get_password_hash, verify_password
from backend.app.models.user import User
from backend.app.schemas.auth import RegisterRequest


class AuthService:
    ALLOWED_THEME_PREFERENCES = {"light", "dark", "system"}
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
