from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.models.user_task_display_preference import UserTaskDisplayPreference
from backend.app.services.auth_service import AuthService


class UserTaskDisplayService:
    def __init__(self, db: Session):
        self.db = db

    def set_highlight_color(self, *, user: User, task: Task, highlight_color: str | None) -> None:
        existing = self.db.scalar(
            select(UserTaskDisplayPreference).where(
                UserTaskDisplayPreference.user_id == user.id,
                UserTaskDisplayPreference.task_id == task.id,
            )
        )

        if not highlight_color:
            if existing:
                self.db.delete(existing)
                self.db.commit()
            return

        normalized = AuthService._normalize_hex_color(highlight_color)
        if existing:
            existing.highlight_color = normalized
            self.db.add(existing)
        else:
            self.db.add(
                UserTaskDisplayPreference(
                    user_id=user.id,
                    task_id=task.id,
                    highlight_color=normalized,
                )
            )
        self.db.commit()

    def get_highlight_color(self, *, user_id: int, task_id: int) -> str | None:
        preference = self.db.scalar(
            select(UserTaskDisplayPreference.highlight_color).where(
                UserTaskDisplayPreference.user_id == user_id,
                UserTaskDisplayPreference.task_id == task_id,
            )
        )
        return preference

    def get_highlight_map(self, *, user_id: int, task_ids: list[int]) -> dict[int, str]:
        unique_task_ids = sorted({task_id for task_id in task_ids if task_id})
        if not unique_task_ids:
            return {}
        rows = self.db.execute(
            select(UserTaskDisplayPreference.task_id, UserTaskDisplayPreference.highlight_color).where(
                UserTaskDisplayPreference.user_id == user_id,
                UserTaskDisplayPreference.task_id.in_(unique_task_ids),
            )
        ).all()
        return {task_id: highlight_color for task_id, highlight_color in rows}

    def apply_highlights(self, *, user_id: int, tasks: list[Task]) -> None:
        highlight_map = self.get_highlight_map(user_id=user_id, task_ids=[task.id for task in tasks])
        for task in tasks:
            task.personal_highlight_color = highlight_map.get(task.id)
