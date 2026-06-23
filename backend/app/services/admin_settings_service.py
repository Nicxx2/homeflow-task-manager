from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.ai.services.orchestrator import AIOrchestratorService
from backend.app.core.security import get_password_hash
from backend.app.models.ai_error_log import AIErrorLog
from backend.app.models.ai_model_registry import AIModelRegistry
from backend.app.models.ai_settings import AISettings
from backend.app.models.app_settings import AppSettings
from backend.app.models.enums import EffortLevel
from backend.app.models.remembered_device import RememberedDevice
from backend.app.models.task import Task
from backend.app.models.task_effort_config import TaskEffortConfig
from backend.app.models.user import User
from backend.app.models.user_away_period import UserAwayPeriod
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.models.user_daily_capacity_override import UserDailyCapacityOverride
from backend.app.models.user_scheduling_preference import UserSchedulingPreference
from backend.app.models.user_task_display_preference import UserTaskDisplayPreference


class AdminSettingsService:
    ALLOWED_THEME_PREFERENCES = {"light", "dark", "system"}
    APPROVAL_PENDING = "pending"
    APPROVAL_APPROVED = "approved"
    APPROVAL_REJECTED = "rejected"

    def __init__(self, db: Session):
        self.db = db
        self.ai = AIOrchestratorService(db)

    def get_effort_configs(self) -> list[TaskEffortConfig]:
        stmt = select(TaskEffortConfig).order_by(TaskEffortConfig.level.asc())
        return list(self.db.scalars(stmt).all())

    def upsert_effort_config(self, values: dict[EffortLevel, int]) -> None:
        for level, points in values.items():
            item = self.db.get(TaskEffortConfig, level)
            if item:
                item.points_value = points
            else:
                self.db.add(TaskEffortConfig(level=level, points_value=points))
        self.db.commit()

    def get_users_with_capacities(self) -> list[tuple[User, int | None]]:
        users = list(self.db.scalars(select(User).order_by(User.full_name.asc())).all())
        capacities: list[tuple[User, int | None]] = []
        for user in users:
            cap = self.db.get(UserDailyCapacity, user.id)
            capacities.append((user, cap.daily_capacity_points if cap else None))
        return capacities

    def get_member_users_with_capacities(self) -> list[tuple[User, int | None]]:
        users = list(
            self.db.scalars(
                select(User)
                .where(
                    User.is_active.is_(True),
                    User.approval_status == self.APPROVAL_APPROVED,
                    User.show_in_member_lists.is_(True),
                )
                .order_by(User.full_name.asc())
            ).all()
        )
        capacities: list[tuple[User, int | None]] = []
        for user in users:
            cap = self.db.get(UserDailyCapacity, user.id)
            capacities.append((user, cap.daily_capacity_points if cap else None))
        return capacities

    def get_pending_users(self) -> list[User]:
        return list(
            self.db.scalars(
                select(User).where(User.approval_status == self.APPROVAL_PENDING).order_by(User.created_at.asc())
            ).all()
        )

    def get_app_settings(self) -> AppSettings:
        settings = self.db.get(AppSettings, 1)
        if settings:
            return settings

        settings = AppSettings(id=1)
        self.db.add(settings)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def set_auto_approve_registrations(self, *, enabled: bool) -> AppSettings:
        settings = self.get_app_settings()
        settings.auto_approve_registrations = enabled
        self.db.add(settings)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def update_login_access_settings(
        self,
        *,
        public_registration_enabled: bool,
        auto_approve_registrations: bool,
        login_theme_preference: str,
        registration_default_capacity_points: int | None,
    ) -> AppSettings:
        selected_theme = login_theme_preference.strip().lower()
        if selected_theme not in self.ALLOWED_THEME_PREFERENCES:
            raise ValueError("Choose a valid login page theme.")
        if registration_default_capacity_points is not None and registration_default_capacity_points <= 0:
            raise ValueError("Default capacity for new registrations must be a positive number.")

        settings = self.get_app_settings()
        settings.public_registration_enabled = public_registration_enabled
        settings.auto_approve_registrations = auto_approve_registrations
        settings.login_theme_preference = selected_theme
        settings.registration_default_capacity_points = registration_default_capacity_points
        self.db.add(settings)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def update_task_collaboration_settings(self, *, allow_member_status_updates: bool) -> AppSettings:
        settings = self.get_app_settings()
        settings.allow_member_status_updates = allow_member_status_updates
        self.db.add(settings)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def upsert_user_capacities(self, capacities: dict[int, int]) -> None:
        for user_id, points in capacities.items():
            item = self.db.get(UserDailyCapacity, user_id)
            if item:
                item.daily_capacity_points = points
            else:
                self.db.add(UserDailyCapacity(user_id=user_id, daily_capacity_points=points))
        self.db.commit()

    def create_user(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None,
        is_admin: bool,
        daily_capacity_points: int | None,
        session_timeout_minutes: int | None,
    ) -> User:
        normalized_email = email.lower().strip()
        if not normalized_email:
            raise ValueError("Email is required.")
        if self.db.scalar(select(User).where(User.email == normalized_email)):
            raise ValueError("A user with this email already exists.")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if daily_capacity_points is not None and daily_capacity_points <= 0:
            raise ValueError("Daily capacity must be a positive number.")
        if session_timeout_minutes is not None and session_timeout_minutes <= 0:
            raise ValueError("Session timeout override must be a positive number.")

        user = User(
            email=normalized_email,
            full_name=(full_name or normalized_email.split("@")[0]).strip(),
            hashed_password=get_password_hash(password),
            is_admin=is_admin,
            approval_status=self.APPROVAL_APPROVED,
            show_in_member_lists=not is_admin,
            session_timeout_minutes=session_timeout_minutes,
        )
        self.db.add(user)
        self.db.flush()

        if daily_capacity_points is not None:
            self.db.add(UserDailyCapacity(user_id=user.id, daily_capacity_points=daily_capacity_points))

        self.db.commit()
        self.db.refresh(user)
        return user

    def approve_user(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if not user:
            raise ValueError("User not found.")
        user.approval_status = self.APPROVAL_APPROVED
        if not user.is_admin:
            user.show_in_member_lists = True
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def reject_user(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if not user:
            raise ValueError("User not found.")
        if user.created_tasks or user.assigned_tasks:
            raise ValueError("Cannot delete a user who already has tasks.")

        capacity = self.db.get(UserDailyCapacity, user.id)
        if capacity:
            self.db.delete(capacity)

        for remembered_device in self.db.scalars(
            select(RememberedDevice).where(RememberedDevice.user_id == user.id)
        ).all():
            self.db.delete(remembered_device)

        self.db.delete(user)
        self.db.commit()
        return user

    def delete_user(self, user_id: int, *, acting_admin_id: int) -> User:
        user = self.db.get(User, user_id)
        if not user:
            raise ValueError("User not found.")
        if user.id == acting_admin_id:
            raise ValueError("You cannot remove your own account.")

        if user.is_admin:
            remaining_admins = self.db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.is_admin.is_(True),
                    User.is_active.is_(True),
                    User.id != user.id,
                )
            )
            if int(remaining_admins or 0) == 0:
                raise ValueError("At least one admin account must remain.")

        for task in self.db.scalars(select(Task).where(Task.created_by_id == user.id)).all():
            task.created_by_id = acting_admin_id
            self.db.add(task)

        for task in self.db.scalars(select(Task).where(Task.assignee_id == user.id)).all():
            task.assignee_id = None
            task.assignment_date = None
            self.db.add(task)

        capacity = self.db.get(UserDailyCapacity, user.id)
        if capacity:
            self.db.delete(capacity)

        scheduling_preference = self.db.get(UserSchedulingPreference, user.id)
        if scheduling_preference:
            self.db.delete(scheduling_preference)

        for override in self.db.scalars(
            select(UserDailyCapacityOverride).where(UserDailyCapacityOverride.user_id == user.id)
        ).all():
            self.db.delete(override)

        for away_period in self.db.scalars(select(UserAwayPeriod).where(UserAwayPeriod.user_id == user.id)).all():
            self.db.delete(away_period)

        for display_pref in self.db.scalars(
            select(UserTaskDisplayPreference).where(UserTaskDisplayPreference.user_id == user.id)
        ).all():
            self.db.delete(display_pref)

        for remembered_device in self.db.scalars(
            select(RememberedDevice).where(RememberedDevice.user_id == user.id)
        ).all():
            self.db.delete(remembered_device)

        self.db.delete(user)
        self.db.commit()
        return user

    def set_user_member_visibility(self, user_id: int, *, visible: bool) -> User:
        user = self.db.get(User, user_id)
        if not user:
            raise ValueError("User not found.")
        user.show_in_member_lists = visible
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_ai_settings(self) -> AISettings:
        return self.ai.get_ai_settings()

    def update_ai_settings(
        self,
        *,
        ai_enabled: bool,
        active_provider: str,
        active_model: str,
        fallback_provider: str,
        timeout_seconds: int,
    ) -> AISettings:
        models = self.get_ai_registry_models()
        if ai_enabled and active_provider == "ollama":
            if models:
                ok = any(
                    item.provider_name == "ollama" and item.model_identifier == active_model and item.available
                    for item in models
                )
                if not ok:
                    raise ValueError("Selected Ollama model is not available in registry.")
        return self.ai.update_settings(
            ai_enabled=ai_enabled,
            active_provider=active_provider,
            active_model=active_model,
            fallback_provider=fallback_provider if ai_enabled else "rules",
            timeout_seconds=timeout_seconds,
        )

    def refresh_ai_models(self) -> list[AIModelRegistry]:
        return self.ai.refresh_model_registry()

    def get_ai_registry_models(self, *, auto_refresh_if_empty: bool = False) -> list[AIModelRegistry]:
        models = self.ai.list_registry_models()
        if models or not auto_refresh_if_empty or not self.get_ai_settings().ai_enabled:
            return models
        return self.ai.refresh_model_registry()

    def test_ai_provider(self, *, sample_title: str, sample_description: str) -> dict:
        return self.ai.test_current_provider(sample_title=sample_title, sample_description=sample_description)

    def get_ai_health(self) -> list[dict]:
        return self.ai.provider_health()

    def get_recent_ai_errors(self, limit: int = 15) -> list[AIErrorLog]:
        return self.ai.recent_errors(limit=limit)

    def get_ai_ui_status(self) -> dict:
        """
        UI-oriented simplified status:
        - green: ollama active and healthy
        - amber: fallback/rules mode in use
        - red: AI currently unavailable (manual override only)
        """
        settings = self.get_ai_settings()
        if not settings.ai_enabled:
            return {"level": "amber", "label": "Fallback Active", "message": "AI is disabled. Rules fallback is active."}

        health_rows = self.get_ai_health()
        active = next((row for row in health_rows if row["provider_name"] == settings.active_provider), None)
        if settings.active_provider == "ollama" and active and active.get("ok"):
            return {"level": "green", "label": "AI Ready", "message": "Ollama model is healthy and active."}

        if settings.fallback_provider == "rules":
            return {"level": "amber", "label": "Fallback Active", "message": "Using rules fallback until Ollama is ready."}

        return {"level": "red", "label": "AI Unavailable", "message": "AI unavailable. Use manual effort selection."}

    def log_ai_error(
        self,
        *,
        provider_name: str,
        model_identifier: str | None,
        error_type: str,
        message: str,
        context: str,
    ) -> None:
        self.ai.log_error(
            provider_name=provider_name,
            model_identifier=model_identifier,
            error_type=error_type,
            message=message,
            context=context,
        )
