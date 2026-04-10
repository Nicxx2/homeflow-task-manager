from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.models.user_away_period import UserAwayPeriod
from backend.app.models.user_scheduling_preference import UserSchedulingPreference


class SchedulingService:
    WEEKDAY_FIELDS = (
        ("monday", "allow_monday", "Monday"),
        ("tuesday", "allow_tuesday", "Tuesday"),
        ("wednesday", "allow_wednesday", "Wednesday"),
        ("thursday", "allow_thursday", "Thursday"),
        ("friday", "allow_friday", "Friday"),
        ("saturday", "allow_saturday", "Saturday"),
        ("sunday", "allow_sunday", "Sunday"),
    )

    def __init__(self, db: Session):
        self.db = db

    def get_or_create_preferences(self, user_id: int) -> UserSchedulingPreference:
        pref = self.db.get(UserSchedulingPreference, user_id)
        if pref:
            return pref

        pref = UserSchedulingPreference(user_id=user_id)
        self.db.add(pref)
        self.db.commit()
        self.db.refresh(pref)
        return pref

    def purge_expired_away_periods(self, *, user_id: int | None = None, reference_date: date | None = None) -> int:
        today = date.today()
        cutoff = today if reference_date is None else min(reference_date, today)
        stmt = select(UserAwayPeriod).where(UserAwayPeriod.end_date < cutoff)
        if user_id is not None:
            stmt = stmt.where(UserAwayPeriod.user_id == user_id)

        expired = list(self.db.scalars(stmt).all())
        if not expired:
            return 0

        for period in expired:
            self.db.delete(period)
        self.db.commit()
        return len(expired)

    def get_preferences_map(self, user_id: int) -> dict[str, bool]:
        pref = self.get_or_create_preferences(user_id)
        return {key: bool(getattr(pref, column)) for key, column, _label in self.WEEKDAY_FIELDS}

    def update_preferences(self, *, user_id: int, allowed_days: dict[str, bool]) -> UserSchedulingPreference:
        pref = self.get_or_create_preferences(user_id)
        for key, column, _label in self.WEEKDAY_FIELDS:
            setattr(pref, column, bool(allowed_days.get(key, False)))
        self.db.add(pref)
        self.db.commit()
        self.db.refresh(pref)
        return pref

    def list_away_periods(self, user_id: int) -> list[UserAwayPeriod]:
        self.purge_expired_away_periods(user_id=user_id)
        stmt = (
            select(UserAwayPeriod)
            .where(UserAwayPeriod.user_id == user_id)
            .order_by(UserAwayPeriod.start_date.asc(), UserAwayPeriod.end_date.asc(), UserAwayPeriod.id.asc())
        )
        return list(self.db.scalars(stmt).all())

    def add_away_period(self, *, user_id: int, start_date: date, end_date: date, note: str | None) -> UserAwayPeriod:
        period = UserAwayPeriod(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            note=(note or "").strip() or None,
        )
        self.db.add(period)
        self.db.commit()
        self.db.refresh(period)
        return period

    def remove_away_period(self, *, user_id: int, period_id: int) -> bool:
        period = self.db.get(UserAwayPeriod, period_id)
        if not period or period.user_id != user_id:
            return False
        self.db.delete(period)
        self.db.commit()
        return True

    def get_block_for_date(self, *, user_id: int, date_value: date) -> dict | None:
        self.purge_expired_away_periods(user_id=user_id, reference_date=date_value)
        away_period = self.db.scalar(
            select(UserAwayPeriod).where(
                UserAwayPeriod.user_id == user_id,
                UserAwayPeriod.start_date <= date_value,
                UserAwayPeriod.end_date >= date_value,
            )
        )
        if away_period:
            label = away_period.note or "Away"
            return {
                "type": "away",
                "message": f"User is marked away on {date_value.isoformat()} ({label}).",
            }

        pref = self.get_or_create_preferences(user_id)
        weekday_index = date_value.weekday()
        key, column, label = self.WEEKDAY_FIELDS[weekday_index]
        if not getattr(pref, column):
            return {
                "type": "preference",
                "message": f"{label} is blocked by this user's schedule preferences.",
                "weekday": key,
            }
        return None

    def get_schedule_page_context(self, *, user_id: int) -> dict:
        preferences = self.get_preferences_map(user_id)
        return {
            "weekday_options": [
                {"key": key, "label": label, "allowed": preferences[key]}
                for key, _column, label in self.WEEKDAY_FIELDS
            ],
            "away_periods": self.list_away_periods(user_id),
        }
