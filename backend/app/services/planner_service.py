import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.enums import TaskStatus
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.models.user_away_period import UserAwayPeriod
from backend.app.models.user_daily_capacity import UserDailyCapacity
from backend.app.models.user_daily_capacity_override import UserDailyCapacityOverride
from backend.app.models.user_scheduling_preference import UserSchedulingPreference
from backend.app.services.scheduling_service import SchedulingService


class PlannerService:
    MAX_BATCH_SIZE = 50

    def __init__(self, db: Session):
        self.db = db
        self.scheduling = SchedulingService(db)

    def get_calendar_days(
        self,
        *,
        members: list[User],
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        member_ids = [member.id for member in members]
        if not member_ids:
            return []

        tasks = list(
            self.db.scalars(
                select(Task)
                .where(
                    Task.assignee_id.in_(member_ids),
                    Task.assignment_date >= start_date,
                    Task.assignment_date <= end_date,
                )
                .order_by(Task.assignment_date.asc(), Task.status.asc(), Task.due_date.asc(), Task.id.asc())
            ).all()
        )
        capacities = {
            row.user_id: row.daily_capacity_points
            for row in self.db.scalars(
                select(UserDailyCapacity).where(UserDailyCapacity.user_id.in_(member_ids))
            ).all()
        }
        overrides = {
            (row.user_id, row.override_date): row.extra_capacity_points
            for row in self.db.scalars(
                select(UserDailyCapacityOverride).where(
                    UserDailyCapacityOverride.user_id.in_(member_ids),
                    UserDailyCapacityOverride.override_date >= start_date,
                    UserDailyCapacityOverride.override_date <= end_date,
                )
            ).all()
        }
        preferences = {
            row.user_id: row
            for row in self.db.scalars(
                select(UserSchedulingPreference).where(UserSchedulingPreference.user_id.in_(member_ids))
            ).all()
        }
        away_periods = defaultdict(list)
        for period in self.db.scalars(
            select(UserAwayPeriod).where(
                UserAwayPeriod.user_id.in_(member_ids),
                UserAwayPeriod.end_date >= start_date,
                UserAwayPeriod.start_date <= end_date,
            )
        ).all():
            away_periods[period.user_id].append(period)

        tasks_by_member_day = defaultdict(list)
        for task in tasks:
            tasks_by_member_day[(task.assignee_id, task.assignment_date)].append(task)

        days = []
        current = start_date
        while current <= end_date:
            member_rows = []
            day_tasks = []
            all_capacities_configured = True
            total_capacity = 0
            total_points = 0

            for member in members:
                assigned_tasks = tasks_by_member_day[(member.id, current)]
                points = sum(task.points_value for task in assigned_tasks)
                base_capacity = capacities.get(member.id)
                capacity = None
                if base_capacity is not None:
                    capacity = base_capacity + overrides.get((member.id, current), 0)
                    total_capacity += capacity
                else:
                    all_capacities_configured = False
                total_points += points
                block = self._range_schedule_block(
                    preference=preferences.get(member.id),
                    away_periods=away_periods.get(member.id, []),
                    date_value=current,
                )
                member_rows.append(
                    {
                        "member": member,
                        "tasks": assigned_tasks,
                        "points": points,
                        "capacity": capacity,
                        "remaining": None if capacity is None else capacity - points,
                        "schedule_block": block,
                    }
                )
                day_tasks.extend(assigned_tasks)

            combined_capacity = total_capacity if all_capacities_configured else None
            remaining = None if combined_capacity is None else combined_capacity - total_points
            days.append(
                {
                    "date": current,
                    "is_today": current == date.today(),
                    "is_past": current < date.today(),
                    "tasks": sorted(
                        day_tasks,
                        key=lambda task: (
                            task.status == TaskStatus.COMPLETED,
                            task.due_date,
                            task.title.lower(),
                            task.id,
                        ),
                    ),
                    "member_rows": member_rows,
                    "points": total_points,
                    "capacity": combined_capacity,
                    "remaining": remaining,
                    "tone": self._capacity_tone(
                        is_past=current < date.today(),
                        member_rows=member_rows,
                        remaining=remaining,
                    ),
                }
            )
            current = date.fromordinal(current.toordinal() + 1)

        return days

    def preview_move(self, *, task_ids: list[int], assignment_date: date, viewer: User) -> dict:
        tasks = self._load_tasks(task_ids)
        return self._build_move_preview(
            tasks=tasks,
            requested_task_ids=task_ids,
            assignment_date=assignment_date,
            viewer=viewer,
        )

    def commit_move(
        self,
        *,
        task_ids: list[int],
        assignment_date: date,
        fingerprint: str,
        viewer: User,
        add_extra_capacity: bool = False,
    ) -> dict:
        tasks = self._load_tasks(task_ids, lock=True)
        assignee_ids = sorted({task.assignee_id for task in tasks if task.assignee_id is not None})
        if assignee_ids:
            list(
                self.db.scalars(
                    select(UserDailyCapacity)
                    .where(UserDailyCapacity.user_id.in_(assignee_ids))
                    .with_for_update()
                ).all()
            )
            list(
                self.db.scalars(
                    select(UserDailyCapacityOverride)
                    .where(
                        UserDailyCapacityOverride.user_id.in_(assignee_ids),
                        UserDailyCapacityOverride.override_date == assignment_date,
                    )
                    .with_for_update()
                ).all()
            )

        preview = self._build_move_preview(
            tasks=tasks,
            requested_task_ids=task_ids,
            assignment_date=assignment_date,
            viewer=viewer,
        )
        extra_capacity_added = 0
        if preview["ok"]:
            if not fingerprint or fingerprint != preview["fingerprint"]:
                self.db.rollback()
                return {
                    "ok": False,
                    "conflict": True,
                    "message": "The plan changed while you were confirming. Refresh and try again.",
                    "errors": ["Task or capacity details changed."],
                }
        elif add_extra_capacity and preview.get("can_add_extra_capacity"):
            if not fingerprint or fingerprint != preview["fingerprint"]:
                self.db.rollback()
                return {
                    "ok": False,
                    "conflict": True,
                    "message": "The plan changed while you were confirming. Refresh and try again.",
                    "errors": ["Task or capacity details changed."],
                }
            extra_capacity_added = int(preview.get("extra_capacity_required") or 0)
            self._increase_extra_capacity_points(
                user_id=viewer.id,
                date_value=assignment_date,
                extra_points=extra_capacity_added,
            )
            self.db.flush()
            preview = self._build_move_preview(
                tasks=tasks,
                requested_task_ids=task_ids,
                assignment_date=assignment_date,
                viewer=viewer,
            )
            if not preview["ok"]:
                self.db.rollback()
                return preview
        else:
            self.db.rollback()
            return preview

        moved_count = 0
        for task in tasks:
            if task.assignment_date == assignment_date:
                continue
            task.assignment_date = assignment_date
            self.db.add(task)
            moved_count += 1

        self.db.commit()
        message = f"{moved_count} task{'s' if moved_count != 1 else ''} moved."
        if extra_capacity_added:
            message = (
                f"{moved_count} task{'s' if moved_count != 1 else ''} moved. "
                f"Added {extra_capacity_added} extra capacity point{'s' if extra_capacity_added != 1 else ''}."
            )
        return {
            **preview,
            "moved": True,
            "moved_count": moved_count,
            "extra_capacity_added": extra_capacity_added,
            "message": message,
        }

    def preview_prioritize(
        self,
        *,
        task_ids: list[int],
        assignment_date: date,
        viewer: User,
        move_out: list[dict] | None = None,
    ) -> dict:
        move_out = move_out or []
        tasks = self._load_tasks(task_ids)
        move_out_tasks = self._load_tasks([item["task_id"] for item in move_out]) if move_out else []
        return self._build_prioritize_preview(
            priority_tasks=tasks,
            requested_task_ids=task_ids,
            move_out_tasks=move_out_tasks,
            move_out_moves=move_out,
            assignment_date=assignment_date,
            viewer=viewer,
        )

    def commit_prioritize(
        self,
        *,
        task_ids: list[int],
        assignment_date: date,
        fingerprint: str,
        viewer: User,
        move_out: list[dict] | None = None,
        add_extra_capacity: bool = False,
    ) -> dict:
        move_out = move_out or []
        all_task_ids = list(dict.fromkeys([*task_ids, *[item["task_id"] for item in move_out]]))
        locked_tasks = self._load_tasks(all_task_ids, lock=True)
        locked_by_id = {task.id: task for task in locked_tasks}
        priority_tasks = [locked_by_id[task_id] for task_id in task_ids if task_id in locked_by_id]
        move_out_tasks = [locked_by_id[item["task_id"]] for item in move_out if item["task_id"] in locked_by_id]

        involved_dates = {assignment_date, *[item["assignment_date"] for item in move_out]}
        involved_user_ids = sorted(
            {
                task.assignee_id
                for task in [*priority_tasks, *move_out_tasks]
                if task.assignee_id is not None
            }
        )
        if involved_user_ids:
            list(
                self.db.scalars(
                    select(UserDailyCapacity)
                    .where(UserDailyCapacity.user_id.in_(involved_user_ids))
                    .with_for_update()
                ).all()
            )
            list(
                self.db.scalars(
                    select(UserDailyCapacityOverride)
                    .where(
                        UserDailyCapacityOverride.user_id.in_(involved_user_ids),
                        UserDailyCapacityOverride.override_date.in_(list(involved_dates)),
                    )
                    .with_for_update()
                ).all()
            )

        preview = self._build_prioritize_preview(
            priority_tasks=priority_tasks,
            requested_task_ids=task_ids,
            move_out_tasks=move_out_tasks,
            move_out_moves=move_out,
            assignment_date=assignment_date,
            viewer=viewer,
        )
        extra_capacity_added = 0
        if preview["ok"]:
            if not fingerprint or fingerprint != preview["fingerprint"]:
                self.db.rollback()
                return self._conflict_response()
        elif add_extra_capacity and preview.get("can_add_extra_capacity"):
            if not fingerprint or fingerprint != preview["fingerprint"]:
                self.db.rollback()
                return self._conflict_response()
            extra_capacity_added = int(preview.get("extra_capacity_required") or 0)
            self._increase_extra_capacity_points(
                user_id=viewer.id,
                date_value=assignment_date,
                extra_points=extra_capacity_added,
            )
            self.db.flush()
            preview = self._build_prioritize_preview(
                priority_tasks=priority_tasks,
                requested_task_ids=task_ids,
                move_out_tasks=move_out_tasks,
                move_out_moves=move_out,
                assignment_date=assignment_date,
                viewer=viewer,
            )
            if not preview["ok"]:
                self.db.rollback()
                return preview
        else:
            self.db.rollback()
            return preview

        moved_in_count = 0
        for task in priority_tasks:
            if task.assignment_date != assignment_date:
                task.assignment_date = assignment_date
                self.db.add(task)
                moved_in_count += 1

        move_out_by_id = {item["task_id"]: item["assignment_date"] for item in move_out}
        moved_out_count = 0
        for task in move_out_tasks:
            destination = move_out_by_id.get(task.id)
            if destination and task.assignment_date != destination:
                task.assignment_date = destination
                self.db.add(task)
                moved_out_count += 1

        self.db.commit()
        message = f"Moved {moved_in_count} selected task{'s' if moved_in_count != 1 else ''}."
        if moved_out_count:
            message += f" Moved out {moved_out_count} task{'s' if moved_out_count != 1 else ''}."
        if extra_capacity_added:
            message += f" Added {extra_capacity_added} extra capacity point{'s' if extra_capacity_added != 1 else ''}."
        return {
            **preview,
            "moved": True,
            "moved_count": moved_in_count,
            "moved_out_count": moved_out_count,
            "extra_capacity_added": extra_capacity_added,
            "message": message,
        }

    def _load_tasks(self, task_ids: list[int], *, lock: bool = False) -> list[Task]:
        stmt = select(Task).where(Task.id.in_(task_ids))
        if lock:
            stmt = stmt.with_for_update()
        tasks = list(self.db.scalars(stmt).all())
        task_order = {task_id: index for index, task_id in enumerate(task_ids)}
        return sorted(tasks, key=lambda task: task_order.get(task.id, len(task_order)))

    def _build_move_preview(
        self,
        *,
        tasks: list[Task],
        requested_task_ids: list[int],
        assignment_date: date,
        viewer: User,
    ) -> dict:
        errors = []
        warnings = []
        capacity_errors = []
        capacity_deficits = []
        loaded_ids = {task.id for task in tasks}
        missing_ids = [task_id for task_id in requested_task_ids if task_id not in loaded_ids]
        if missing_ids:
            errors.append("One or more selected tasks no longer exist.")
        if assignment_date < date.today():
            errors.append("Tasks cannot be moved to a past date.")
        if not viewer.is_active:
            errors.append("Your account cannot change task schedules.")

        movable_tasks = []
        unchanged_count = 0
        for task in tasks:
            if task.status == TaskStatus.COMPLETED:
                errors.append(f"{task.title}: completed tasks cannot be moved.")
                continue
            if task.recurrence_parent_id is not None:
                errors.append(f"{task.title}: completed recurring history cannot be moved.")
                continue
            if task.assignee_id is None:
                errors.append(f"{task.title}: assign this task before moving it in Planner.")
                continue
            if not self._can_move_task_in_planner(task=task, viewer=viewer):
                errors.append(f"{task.title}: only approved active members can move this task in Planner.")
                continue
            if task.assignment_date == assignment_date:
                unchanged_count += 1
            else:
                movable_tasks.append(task)
            if task.status == TaskStatus.IN_PROGRESS and task.assignment_date != assignment_date:
                warnings.append(f"{task.title} is already in progress.")
            if task.due_date < assignment_date and task.assignment_date != assignment_date:
                warnings.append(f"{task.title} will be planned after its due date.")

        if not movable_tasks and not errors:
            errors.append("The selected tasks are already on this date.")

        moving_ids = [task.id for task in movable_tasks]
        tasks_by_assignee = defaultdict(list)
        for task in movable_tasks:
            tasks_by_assignee[task.assignee_id].append(task)

        member_summaries = []
        fingerprint_rows = []
        for assignee_id, selected_tasks in tasks_by_assignee.items():
            assignee = self.db.get(User, assignee_id)
            if not assignee or not assignee.is_active:
                errors.append("One selected task has an inactive assignee.")
                continue

            block = self._move_schedule_block(user_id=assignee_id, date_value=assignment_date)
            if block:
                errors.append(f"{assignee.full_name}: {block['message']}")

            capacity_row = self.db.get(UserDailyCapacity, assignee_id)
            if capacity_row is None:
                errors.append(f"{assignee.full_name}: daily capacity is not configured.")
                capacity = None
            else:
                override = self.db.get(
                    UserDailyCapacityOverride,
                    {"user_id": assignee_id, "override_date": assignment_date},
                )
                capacity = capacity_row.daily_capacity_points + (override.extra_capacity_points if override else 0)

            current_points = int(
                self.db.scalar(
                    select(func.coalesce(func.sum(Task.points_value), 0)).where(
                        Task.assignee_id == assignee_id,
                        Task.assignment_date == assignment_date,
                        Task.id.not_in(moving_ids),
                    )
                )
                or 0
            )
            selected_points = sum(task.points_value for task in selected_tasks)
            projected_points = current_points + selected_points
            remaining = None if capacity is None else capacity - projected_points
            if capacity is not None and projected_points > capacity:
                deficit = projected_points - capacity
                capacity_errors.append(
                    f"{assignee.full_name}: needs {projected_points} points but only has {capacity} capacity."
                )
                capacity_deficits.append(
                    {
                        "user_id": assignee_id,
                        "name": assignee.full_name,
                        "points": deficit,
                    }
                )

            member_summaries.append(
                {
                    "user_id": assignee_id,
                    "name": assignee.full_name,
                    "current_points": current_points,
                    "selected_points": selected_points,
                    "projected_points": projected_points,
                    "capacity": capacity,
                    "remaining": remaining,
                }
            )
            fingerprint_rows.append(
                {
                    "user_id": assignee_id,
                    "current_points": current_points,
                    "projected_points": projected_points,
                    "capacity": capacity,
                    "blocked": block["type"] if block else None,
                }
            )

        task_fingerprint_rows = [
            {
                "id": task.id,
                "status": task.status.value,
                "assignee_id": task.assignee_id,
                "assignment_date": task.assignment_date.isoformat() if task.assignment_date else None,
                "due_date": task.due_date.isoformat(),
                "points": task.points_value,
                "updated_at": task.updated_at.isoformat(),
            }
            for task in tasks
        ]
        fingerprint_payload = {
            "assignment_date": assignment_date.isoformat(),
            "tasks": task_fingerprint_rows,
            "members": sorted(fingerprint_rows, key=lambda row: row["user_id"]),
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        unique_capacity_deficits = {
            item["user_id"]: item
            for item in capacity_deficits
        }
        extra_capacity_user = next(iter(unique_capacity_deficits.values()), None)
        can_add_extra_capacity = bool(
            not errors
            and len(unique_capacity_deficits) == 1
            and extra_capacity_user is not None
            and extra_capacity_user["user_id"] == viewer.id
            and all(task.assignee_id == viewer.id for task in movable_tasks)
        )
        extra_capacity_required = int(extra_capacity_user["points"]) if can_add_extra_capacity else 0
        all_errors = list(dict.fromkeys(errors + capacity_errors))
        ok = not all_errors
        moving_count = len(movable_tasks)
        if ok:
            message = f"Move {moving_count} task{'s' if moving_count != 1 else ''} to {assignment_date.strftime('%A, %d %B')}?"
        elif can_add_extra_capacity:
            message = (
                f"This day is full by {extra_capacity_required} point"
                f"{'s' if extra_capacity_required != 1 else ''}. Add extra capacity to move anyway?"
            )
        else:
            message = "These tasks cannot be moved to the selected date."
        return {
            "ok": ok,
            "message": message,
            "assignment_date": assignment_date.isoformat(),
            "task_count": moving_count,
            "unchanged_count": unchanged_count,
            "total_points": sum(task.points_value for task in movable_tasks),
            "members": member_summaries,
            "warnings": list(dict.fromkeys(warnings)),
            "errors": all_errors,
            "fingerprint": fingerprint,
            "can_add_extra_capacity": can_add_extra_capacity,
            "extra_capacity_required": extra_capacity_required,
            "extra_capacity_user_id": viewer.id if can_add_extra_capacity else None,
            "extra_capacity_user_name": viewer.full_name if can_add_extra_capacity else None,
        }

    def _build_prioritize_preview(
        self,
        *,
        priority_tasks: list[Task],
        requested_task_ids: list[int],
        move_out_tasks: list[Task],
        move_out_moves: list[dict],
        assignment_date: date,
        viewer: User,
    ) -> dict:
        today = date.today()
        errors: list[str] = []
        warnings: list[str] = []
        target_capacity_errors: list[str] = []
        destination_errors: list[str] = []
        loaded_ids = {task.id for task in priority_tasks}
        missing_ids = [task_id for task_id in requested_task_ids if task_id not in loaded_ids]
        if missing_ids:
            errors.append("One or more selected tasks no longer exist.")
        if assignment_date < today:
            errors.append("Tasks cannot be moved to a past date.")
        if not viewer.is_active:
            errors.append("Your account cannot change task schedules.")

        priority_valid: list[Task] = []
        unchanged_count = 0
        for task in priority_tasks:
            if task.status == TaskStatus.COMPLETED:
                errors.append(f"{task.title}: completed tasks cannot be moved.")
                continue
            if task.recurrence_parent_id is not None:
                errors.append(f"{task.title}: recurring history cannot be moved.")
                continue
            if task.assignee_id is None:
                errors.append(f"{task.title}: assign this task before moving it in Planner.")
                continue
            if not self._can_move_task_in_planner(task=task, viewer=viewer):
                errors.append(f"{task.title}: only approved active members can move this task in Planner.")
                continue
            if task.assignment_date == assignment_date:
                unchanged_count += 1
            if task.status == TaskStatus.IN_PROGRESS and task.assignment_date != assignment_date:
                warnings.append(f"{task.title} is already in progress.")
            if task.due_date < assignment_date and task.assignment_date != assignment_date:
                warnings.append(f"{task.title} will be planned after its due date.")
            priority_valid.append(task)

        if not priority_valid and not errors:
            errors.append("Select at least one movable task.")
        elif not any(task.assignment_date != assignment_date for task in priority_valid) and not errors:
            errors.append("The selected tasks are already on this date.")

        priority_ids = [task.id for task in priority_valid]
        priority_id_set = set(priority_ids)
        move_out_by_id = {item["task_id"]: item["assignment_date"] for item in move_out_moves}
        loaded_move_out_ids = {task.id for task in move_out_tasks}
        missing_move_out_ids = [task_id for task_id in move_out_by_id if task_id not in loaded_move_out_ids]
        if missing_move_out_ids:
            errors.append("One or more move-out tasks no longer exist.")

        target_assignee_ids = {task.assignee_id for task in priority_valid if task.assignee_id is not None}
        move_out_valid: list[tuple[Task, date]] = []
        for task in move_out_tasks:
            destination = move_out_by_id.get(task.id)
            if destination is None:
                continue
            if task.id in priority_id_set:
                errors.append(f"{task.title}: a selected task cannot also be moved out.")
                continue
            if task.status == TaskStatus.COMPLETED:
                errors.append(f"{task.title}: completed tasks cannot be moved out.")
                continue
            if task.recurrence_parent_id is not None:
                errors.append(f"{task.title}: recurring history cannot be moved out.")
                continue
            if task.assignee_id is None:
                errors.append(f"{task.title}: unassigned tasks do not create capacity room.")
                continue
            if task.assignee_id not in target_assignee_ids:
                errors.append(f"{task.title}: move out tasks for the same person as the selected work.")
                continue
            if not self._can_move_task_in_planner(task=task, viewer=viewer):
                errors.append(f"{task.title}: only approved active members can move this task in Planner.")
                continue
            if task.assignment_date != assignment_date:
                errors.append(f"{task.title}: only tasks already on the target date can make room.")
                continue
            if destination < today:
                errors.append(f"{task.title}: move-out date cannot be in the past.")
                continue
            if destination == assignment_date:
                errors.append(f"{task.title}: choose a different date to move this task out.")
                continue
            if task.status == TaskStatus.IN_PROGRESS:
                warnings.append(f"{task.title} is in progress and will be moved out.")
            if task.due_date < destination:
                warnings.append(f"{task.title} will be planned after its due date.")
            move_out_valid.append((task, destination))

        move_out_ids = [task.id for task, _destination in move_out_valid]
        target_exclude_ids = list(dict.fromkeys([*priority_ids, *move_out_ids]))
        priority_by_assignee: dict[int, list[Task]] = defaultdict(list)
        for task in priority_valid:
            priority_by_assignee[task.assignee_id].append(task)

        member_summaries = []
        target_deficits = []
        fingerprint_rows = []
        for assignee_id, selected_tasks in priority_by_assignee.items():
            assignee = self.db.get(User, assignee_id)
            if not assignee or not assignee.is_active:
                errors.append("One selected task has an inactive assignee.")
                continue
            block = self._move_schedule_block(user_id=assignee_id, date_value=assignment_date)
            if block:
                errors.append(f"{assignee.full_name}: {block['message']}")
            capacity = self._capacity_for_day(user_id=assignee_id, date_value=assignment_date)
            if capacity is None:
                errors.append(f"{assignee.full_name}: daily capacity is not configured.")
            current_points = self._day_points(user_id=assignee_id, date_value=assignment_date, exclude_task_ids=target_exclude_ids)
            selected_points = sum(task.points_value for task in selected_tasks)
            moved_out_points = sum(task.points_value for task, _destination in move_out_valid if task.assignee_id == assignee_id)
            projected_points = current_points + selected_points
            remaining = None if capacity is None else capacity - projected_points
            if capacity is not None and projected_points > capacity:
                deficit = projected_points - capacity
                target_capacity_errors.append(
                    f"{assignee.full_name}: needs {projected_points} points but only has {capacity} capacity."
                )
                target_deficits.append({"user_id": assignee_id, "name": assignee.full_name, "points": deficit})
            member_summaries.append(
                {
                    "user_id": assignee_id,
                    "name": assignee.full_name,
                    "current_points": current_points,
                    "selected_points": selected_points,
                    "moved_out_points": moved_out_points,
                    "projected_points": projected_points,
                    "capacity": capacity,
                    "remaining": remaining,
                }
            )
            fingerprint_rows.append(
                {
                    "user_id": assignee_id,
                    "date": assignment_date.isoformat(),
                    "current_points": current_points,
                    "selected_points": selected_points,
                    "moved_out_points": moved_out_points,
                    "projected_points": projected_points,
                    "capacity": capacity,
                    "blocked": block["type"] if block else None,
                }
            )

        destination_summaries = []
        move_out_by_destination: dict[tuple[int, date], list[Task]] = defaultdict(list)
        for task, destination in move_out_valid:
            move_out_by_destination[(task.assignee_id, destination)].append(task)
        destination_exclude_ids = list(dict.fromkeys([*priority_ids, *move_out_ids]))
        for (assignee_id, destination), tasks_for_day in move_out_by_destination.items():
            assignee = self.db.get(User, assignee_id)
            if not assignee or not assignee.is_active:
                destination_errors.append("One move-out task has an inactive assignee.")
                continue
            block = self._move_schedule_block(user_id=assignee_id, date_value=destination)
            if block:
                destination_errors.append(f"{assignee.full_name} on {destination.isoformat()}: {block['message']}")
            capacity = self._capacity_for_day(user_id=assignee_id, date_value=destination)
            if capacity is None:
                destination_errors.append(f"{assignee.full_name} on {destination.isoformat()}: daily capacity is not configured.")
            current_points = self._day_points(user_id=assignee_id, date_value=destination, exclude_task_ids=destination_exclude_ids)
            moved_points = sum(task.points_value for task in tasks_for_day)
            projected_points = current_points + moved_points
            remaining = None if capacity is None else capacity - projected_points
            if capacity is not None and projected_points > capacity:
                destination_errors.append(
                    f"{assignee.full_name} on {destination.isoformat()}: needs {projected_points} points but only has {capacity} capacity."
                )
            destination_summaries.append(
                {
                    "user_id": assignee_id,
                    "name": assignee.full_name,
                    "assignment_date": destination.isoformat(),
                    "current_points": current_points,
                    "moved_points": moved_points,
                    "projected_points": projected_points,
                    "capacity": capacity,
                    "remaining": remaining,
                    "tasks": [self._planner_task_summary(task) for task in tasks_for_day],
                }
            )
            fingerprint_rows.append(
                {
                    "user_id": assignee_id,
                    "date": destination.isoformat(),
                    "current_points": current_points,
                    "moved_points": moved_points,
                    "projected_points": projected_points,
                    "capacity": capacity,
                    "blocked": block["type"] if block else None,
                }
            )

        candidates = []
        if target_deficits:
            excluded_candidate_ids = set([*priority_ids, *move_out_ids])
            for deficit in target_deficits:
                candidates.extend(
                    self._make_room_candidates(
                        user_id=deficit["user_id"],
                        assignment_date=assignment_date,
                        viewer=viewer,
                        exclude_task_ids=excluded_candidate_ids,
                    )
                )

        task_fingerprint_rows = [self._task_fingerprint_row(task) for task in [*priority_tasks, *move_out_tasks]]
        move_out_rows = [
            {"task_id": task.id, "assignment_date": destination.isoformat()}
            for task, destination in move_out_valid
        ]
        fingerprint_payload = {
            "type": "prioritize",
            "assignment_date": assignment_date.isoformat(),
            "tasks": task_fingerprint_rows,
            "move_out": sorted(move_out_rows, key=lambda row: row["task_id"]),
            "capacity": sorted(fingerprint_rows, key=lambda row: (row["user_id"], row["date"])),
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        unique_target_deficits = {item["user_id"]: item for item in target_deficits}
        extra_capacity_user = next(iter(unique_target_deficits.values()), None)
        can_add_extra_capacity = bool(
            not errors
            and not destination_errors
            and len(unique_target_deficits) == 1
            and extra_capacity_user is not None
            and extra_capacity_user["user_id"] == viewer.id
            and all(task.assignee_id == viewer.id for task in priority_valid)
        )
        extra_capacity_required = int(extra_capacity_user["points"]) if can_add_extra_capacity else 0
        all_errors = list(dict.fromkeys([*errors, *destination_errors, *target_capacity_errors]))
        ok = not all_errors
        usable_candidates = candidates if not errors and not destination_errors else []
        priority_count = len([task for task in priority_valid if task.assignment_date != assignment_date])
        if ok:
            message = f"Move {priority_count} task{'s' if priority_count != 1 else ''} to {assignment_date.strftime('%A, %d %B')}?"
        elif usable_candidates:
            message = "Choose tasks to move out, then review again."
        elif can_add_extra_capacity:
            message = (
                f"This day is full by {extra_capacity_required} point"
                f"{'s' if extra_capacity_required != 1 else ''}. Add extra capacity to move anyway?"
            )
        else:
            message = "These tasks cannot be moved to the selected date."

        return {
            "ok": ok,
            "message": message,
            "mode": "prioritize",
            "assignment_date": assignment_date.isoformat(),
            "task_count": priority_count,
            "unchanged_count": unchanged_count,
            "total_points": sum(task.points_value for task in priority_valid),
            "priority_tasks": [
                self._planner_task_summary(task)
                for task in priority_valid
                if task.assignment_date != assignment_date
            ],
            "move_out": move_out_rows,
            "move_out_count": len(move_out_valid),
            "members": member_summaries,
            "destinations": destination_summaries,
            "make_room_candidates": usable_candidates,
            "capacity_gap": sum(item["points"] for item in target_deficits),
            "capacity_gaps": list(unique_target_deficits.values()),
            "warnings": list(dict.fromkeys(warnings)),
            "errors": all_errors,
            "fingerprint": fingerprint,
            "can_add_extra_capacity": can_add_extra_capacity,
            "extra_capacity_required": extra_capacity_required,
            "extra_capacity_user_id": viewer.id if can_add_extra_capacity else None,
            "extra_capacity_user_name": viewer.full_name if can_add_extra_capacity else None,
        }

    def _conflict_response(self) -> dict:
        return {
            "ok": False,
            "conflict": True,
            "message": "The plan changed while you were confirming. Refresh and try again.",
            "errors": ["Task or capacity details changed."],
        }

    def _planner_task_summary(self, task: Task) -> dict:
        return {
            "id": task.id,
            "title": task.title,
            "points": task.points_value,
            "status": task.status.value,
            "assignee_id": task.assignee_id,
            "assignee_name": task.assignee.full_name if task.assignee else "Unassigned",
            "assignment_date": task.assignment_date.isoformat() if task.assignment_date else None,
            "due_date": task.due_date.isoformat(),
        }

    def _task_fingerprint_row(self, task: Task) -> dict:
        return {
            "id": task.id,
            "status": task.status.value,
            "assignee_id": task.assignee_id,
            "assignment_date": task.assignment_date.isoformat() if task.assignment_date else None,
            "due_date": task.due_date.isoformat(),
            "points": task.points_value,
            "updated_at": task.updated_at.isoformat(),
        }

    def _capacity_for_day(self, *, user_id: int, date_value: date) -> int | None:
        capacity_row = self.db.get(UserDailyCapacity, user_id)
        if capacity_row is None:
            return None
        override = self.db.get(UserDailyCapacityOverride, {"user_id": user_id, "override_date": date_value})
        return capacity_row.daily_capacity_points + (override.extra_capacity_points if override else 0)

    def _day_points(self, *, user_id: int, date_value: date, exclude_task_ids: list[int] | set[int] | None = None) -> int:
        stmt = select(func.coalesce(func.sum(Task.points_value), 0)).where(
            Task.assignee_id == user_id,
            Task.assignment_date == date_value,
        )
        exclude_values = list(exclude_task_ids or [])
        if exclude_values:
            stmt = stmt.where(Task.id.not_in(exclude_values))
        return int(self.db.scalar(stmt) or 0)

    def _make_room_candidates(
        self,
        *,
        user_id: int,
        assignment_date: date,
        viewer: User,
        exclude_task_ids: set[int],
    ) -> list[dict]:
        stmt = (
            select(Task)
            .where(
                Task.assignee_id == user_id,
                Task.assignment_date == assignment_date,
                Task.status != TaskStatus.COMPLETED,
                Task.recurrence_parent_id.is_(None),
            )
            .order_by(Task.status == TaskStatus.IN_PROGRESS, Task.due_date.desc(), Task.points_value.desc(), Task.id.asc())
        )
        if exclude_task_ids:
            stmt = stmt.where(Task.id.not_in(list(exclude_task_ids)))
        candidates = []
        reserved_points: dict[tuple[int, date], int] = defaultdict(int)
        for task in self.db.scalars(stmt).all():
            if not self._can_move_task_in_planner(task=task, viewer=viewer):
                continue
            suggested_date = self._suggest_move_out_date(
                task=task,
                start_date=assignment_date + timedelta(days=1),
                exclude_task_ids={*exclude_task_ids, task.id},
                reserved_points=reserved_points,
            )
            if suggested_date and task.assignee_id is not None:
                reserved_points[(task.assignee_id, suggested_date)] += task.points_value
            row = self._planner_task_summary(task)
            row["suggested_date"] = suggested_date.isoformat() if suggested_date else None
            row["is_in_progress"] = task.status == TaskStatus.IN_PROGRESS
            candidates.append(row)
        return candidates

    def _suggest_move_out_date(
        self,
        *,
        task: Task,
        start_date: date,
        exclude_task_ids: set[int],
        reserved_points: dict[tuple[int, date], int] | None = None,
    ) -> date | None:
        if task.assignee_id is None:
            return None
        candidate = max(start_date, date.today())
        for _ in range(60):
            if not self._move_schedule_block(user_id=task.assignee_id, date_value=candidate):
                capacity = self._capacity_for_day(user_id=task.assignee_id, date_value=candidate)
                if capacity is not None:
                    points = self._day_points(
                        user_id=task.assignee_id,
                        date_value=candidate,
                        exclude_task_ids=exclude_task_ids,
                    )
                    reserved = (reserved_points or {}).get((task.assignee_id, candidate), 0)
                    if points + reserved + task.points_value <= capacity:
                        return candidate
            candidate = date.fromordinal(candidate.toordinal() + 1)
        return None
    def _increase_extra_capacity_points(self, *, user_id: int, date_value: date, extra_points: int) -> None:
        if extra_points <= 0:
            raise ValueError("Extra capacity must be positive.")
        capacity_row = self.db.get(UserDailyCapacity, user_id)
        if capacity_row is None:
            raise ValueError("Daily capacity is not configured.")

        override = self.db.get(UserDailyCapacityOverride, {"user_id": user_id, "override_date": date_value})
        if override:
            override.extra_capacity_points += extra_points
            self.db.add(override)
            return

        self.db.add(
            UserDailyCapacityOverride(
                user_id=user_id,
                override_date=date_value,
                extra_capacity_points=extra_points,
            )
        )

    @staticmethod
    def _can_move_task_in_planner(*, task: Task, viewer: User) -> bool:
        return bool(viewer.is_active and (viewer.is_admin or viewer.approval_status == "approved"))

    def _move_schedule_block(self, *, user_id: int, date_value: date) -> dict | None:
        away_period = self.db.scalar(
            select(UserAwayPeriod).where(
                UserAwayPeriod.user_id == user_id,
                UserAwayPeriod.start_date <= date_value,
                UserAwayPeriod.end_date >= date_value,
            )
        )
        if away_period:
            return {
                "type": "away",
                "message": f"marked away ({away_period.note or 'Away'}).",
            }

        preference = self.db.get(UserSchedulingPreference, user_id)
        if preference is None:
            return None
        _key, column, label = SchedulingService.WEEKDAY_FIELDS[date_value.weekday()]
        if not getattr(preference, column):
            return {
                "type": "preference",
                "message": f"{label} is unavailable.",
            }
        return None

    @staticmethod
    def _range_schedule_block(
        *,
        preference: UserSchedulingPreference | None,
        away_periods: list[UserAwayPeriod],
        date_value: date,
    ) -> dict | None:
        for period in away_periods:
            if period.start_date <= date_value <= period.end_date:
                return {"type": "away", "message": period.note or "Away"}

        if preference is None:
            return None
        _key, column, label = SchedulingService.WEEKDAY_FIELDS[date_value.weekday()]
        if not getattr(preference, column):
            return {"type": "preference", "message": f"{label} unavailable"}
        return None

    @staticmethod
    def _capacity_tone(*, is_past: bool, member_rows: list[dict], remaining: int | None) -> str:
        if is_past:
            return "past"
        if any(row["schedule_block"] for row in member_rows):
            return "blocked"
        if remaining is None:
            return "unset"
        if remaining < 0:
            return "over"
        if remaining == 0:
            return "full"
        if remaining <= 2:
            return "near"
        return "open"
