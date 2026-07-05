import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.services.orchestrator import AIOrchestratorService
from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.services.auth_service import AuthService
from backend.app.services.recurring_task_service import RecurringTaskService
from backend.app.services.task_service import TaskService
from backend.app.services.workload_service import WorkloadService


@dataclass(frozen=True)
class _DateFilter:
    value: date
    field: str = "either"


@dataclass(frozen=True)
class _MemberFilter:
    user: User | None = None
    unassigned: bool = False
    ambiguous_names: tuple[str, ...] = ()


class AppAssistantService:
    _MONTHS = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }

    def __init__(self, db: Session, *, user: User):
        self.db = db
        self.user = user
        self.task_service = TaskService(db)
        self.workload = WorkloadService(db)

    def respond(self, message: str, context_items: list[dict] | None = None) -> dict:
        RecurringTaskService(self.db).sync()
        query = " ".join(message.lower().split())
        if not query:
            return self._help_response()

        reference_response = self._context_reference_response(query=query, context_items=context_items or [])
        if reference_response is not None:
            return reference_response

        if self._is_unsupported_write_query(query):
            return self._unsupported_action_response()

        effort = self._extract_effort(query)
        due_today = self._is_due_today_query(query)
        assigned_today = self._is_assigned_today_query(query)
        status_filter = self._extract_status(query)
        active_only = self._active_only(query=query, status_filter=status_filter)
        overdue = self._is_overdue_query(query)
        date_filter = self._extract_date_filter(query)
        if "most capacity" in query or "most room" in query:
            return self._most_capacity_response()

        if effort and self._is_capacity_query(query) and not self._is_assign_me_query(query):
            return self._capacity_for_effort_response(effort)

        member_filter = self._resolve_member_filter(query)
        if member_filter.ambiguous_names:
            return {
                "reply": "I found more than one matching member. Use the full name so I pick the right one.",
                "suggestions": [f"Show tasks for {name}" for name in member_filter.ambiguous_names[:3]],
                "items": [],
            }

        only_unassigned = self._is_unassigned_query(query) or member_filter.unassigned
        assignee_id = member_filter.user.id if member_filter.user else None
        personal_only = not (only_unassigned or assignee_id is not None or self._is_team_scope_query(query))

        if effort and self._is_assign_me_query(query):
            return self._assign_me_response(
                effort,
                due_today=due_today,
                only_unassigned=only_unassigned,
                status_filter=status_filter,
                date_filter=date_filter,
                active_only=active_only,
            )

        if self._is_task_query(query) or effort or status_filter or date_filter or assignee_id or only_unassigned or overdue:
            return self._list_tasks_response(
                effort=effort,
                only_unassigned=only_unassigned,
                due_today=due_today,
                assigned_today=assigned_today,
                status_filter=status_filter,
                date_filter=date_filter,
                assignee_id=assignee_id,
                overdue=overdue,
                active_only=active_only,
                personal_only=personal_only,
            )

        ai_response = self._ai_intent_response(message=message, query=query)
        if ai_response is not None:
            return ai_response

        return self._help_response()

    def assign_self_to_task(self, *, task_id: int, assignment_date: date) -> dict:
        task = self.task_service.get_task(task_id)
        if not task:
            return {"ok": False, "reply": "That task no longer exists."}

        if task.status == TaskStatus.COMPLETED:
            return {"ok": False, "reply": "Completed tasks cannot be assigned."}

        if task.assignee_id and task.assignee_id != self.user.id:
            return {"ok": False, "reply": "That task is already assigned to someone else."}

        validation = self.workload.validate_assignment(
            user_id=self.user.id,
            date_value=assignment_date,
            task_points=task.points_value,
            exclude_task_id=task.id,
        )
        if not validation["valid"]:
            next_date = validation.get("next_available_date")
            if next_date:
                return {
                    "ok": False,
                    "reply": f"{validation['message']} Next available date: {next_date}.",
                }
            return {"ok": False, "reply": validation["message"]}

        self.task_service.assign_task(task, assignee_id=self.user.id, assignment_date=assignment_date)
        return {
            "ok": True,
            "reply": f"Assigned '{task.title}' to you for {assignment_date.isoformat()}.",
        }

    def _help_response(self) -> dict:
        return {
            "reply": "I can help with task and capacity questions inside this app only.",
            "suggestions": [
                "List low tasks",
                "Show my tasks today",
                "Show overdue tasks",
                "What unassigned tasks are due today?",
                "Who has the most capacity left?",
                "Add me to any low task available",
            ],
            "items": [],
        }

    def _unsupported_action_response(self) -> dict:
        return {
            "reply": "I can search and prepare safe self-assignments here. Use Planner or the task form for moves and new tasks so capacity checks and confirmations stay protected.",
            "suggestions": ["Show overdue tasks", "List unassigned low tasks", "Who has the most capacity left?"],
            "items": [],
        }

    def _list_tasks_response(
        self,
        *,
        effort: EffortLevel | None,
        only_unassigned: bool,
        due_today: bool,
        assigned_today: bool,
        status_filter: TaskStatus | None,
        date_filter: _DateFilter | None,
        assignee_id: int | None,
        overdue: bool,
        active_only: bool,
        personal_only: bool,
    ) -> dict:
        tasks = self.task_service.get_tasks(only_unassigned=only_unassigned if only_unassigned else None)
        if personal_only:
            tasks = [task for task in tasks if task.created_by_id == self.user.id or task.assignee_id == self.user.id]
        tasks = self._filter_tasks(
            tasks,
            effort=effort,
            due_today=due_today,
            assigned_today=assigned_today,
            status_filter=status_filter,
            date_filter=date_filter,
            assignee_id=assignee_id,
            overdue=overdue,
            active_only=active_only,
        )
        tasks = self._sort_tasks(tasks, prioritize_personal=personal_only)

        items = [self._task_item(task) for task in tasks[:8]]
        label = self._task_label(
            effort=effort,
            only_unassigned=only_unassigned,
            due_today=due_today,
            assigned_today=assigned_today,
            status_filter=status_filter,
            date_filter=date_filter,
            assignee_id=assignee_id,
            overdue=overdue,
            active_only=active_only,
        )

        if not items:
            return {
                "reply": f"I could not find any {label + ' ' if label else ''}tasks right now.",
                "suggestions": ["Show overdue tasks", "What tasks are due today?", "Who has the most capacity left?"],
                "items": [],
            }

        reply = f"I found {len(items)} {label + ' ' if label else ''}task{'s' if len(items) != 1 else ''}."
        if status_filter == TaskStatus.COMPLETED and date_filter is not None:
            reply += " Completion date is not stored, so I matched due/planned dates."

        return {
            "reply": reply,
            "suggestions": ["Show my tasks today", "List unassigned low tasks", "Who has enough capacity for one medium task?"],
            "items": items,
        }

    def _context_reference_response(self, *, query: str, context_items: list[dict]) -> dict | None:
        if not context_items or not self._is_assign_me_query(query):
            return None

        referenced = self._resolve_context_item(query=query, context_items=context_items)
        if referenced is None:
            if self._mentions_context_reference(query):
                return {
                    "reply": "I could not tell which task you meant. Say first or second, or use the button on the task card.",
                    "suggestions": ["Assign me to the first one", "Assign me to the second one"],
                    "items": [],
                }
            return None

        action = referenced.get("action")
        if not action or action.get("type") != "assign_self":
            return {
                "reply": f"'{referenced.get('title', 'That task')}' is not available for self-assignment from here.",
                "suggestions": ["What unassigned tasks are due today?", "List low tasks"],
                "items": [],
            }

        return {
            "reply": f"I found the task you meant. Confirm below if you want me to assign '{referenced.get('title', 'this task')}' to you.",
            "suggestions": ["Assign me to the first one", "What unassigned tasks are due today?"],
            "items": [referenced],
        }

    def _capacity_for_effort_response(self, effort: EffortLevel) -> dict:
        points = self._points_for_effort(effort)
        today = date.today()
        eligible = []
        for member in self._member_users():
            current = self.workload.get_daily_points(user_id=member.id, date_value=today)
            capacity = self.workload.get_user_capacity(member.id, date_value=today)
            if capacity is None:
                continue
            remaining = capacity - current
            if remaining >= points:
                eligible.append(
                    {
                        "title": member.full_name,
                        "meta": f"{remaining} pts left today | capacity {capacity}",
                    }
                )

        if not eligible:
            return {
                "reply": f"No visible member has enough room today for one {effort.value} task ({points} pts).",
                "suggestions": ["Who has the most capacity left?", "List low tasks"],
                "items": [],
            }

        return {
            "reply": f"These members have enough capacity today for one {effort.value} task ({points} pts).",
            "suggestions": ["Who has the most capacity left?", "List high tasks"],
            "items": eligible,
        }

    def _most_capacity_response(self) -> dict:
        today = date.today()
        items = []
        for member in self._member_users():
            current = self.workload.get_daily_points(user_id=member.id, date_value=today)
            capacity = self.workload.get_user_capacity(member.id, date_value=today)
            remaining = None if capacity is None else capacity - current
            items.append(
                {
                    "title": member.full_name,
                    "meta": (
                        "Capacity not set"
                        if remaining is None
                        else f"{remaining} pts left today | used {current} of {capacity}"
                    ),
                    "remaining": -999999 if remaining is None else remaining,
                }
            )

        ranked = sorted(items, key=lambda item: item["remaining"], reverse=True)
        visible = [{"title": item["title"], "meta": item["meta"]} for item in ranked[:5]]
        if not visible:
            return {
                "reply": "No visible members are available for capacity comparison.",
                "suggestions": ["List low tasks"],
                "items": [],
            }

        top = visible[0]
        return {
            "reply": f"{top['title']} currently has the most capacity left.",
            "suggestions": ["Who has enough capacity for one high task?", "List low tasks"],
            "items": visible,
        }

    def _assign_me_response(
        self,
        effort: EffortLevel,
        *,
        due_today: bool,
        only_unassigned: bool,
        status_filter: TaskStatus | None,
        date_filter: _DateFilter | None,
        active_only: bool,
    ) -> dict:
        candidates = self.task_service.get_tasks(only_unassigned=True)
        candidates = self._filter_tasks(
            candidates,
            effort=effort,
            due_today=due_today,
            assigned_today=False,
            status_filter=status_filter,
            date_filter=date_filter,
            assignee_id=None,
            overdue=False,
            active_only=active_only,
        )
        candidates = self._sort_tasks(candidates, prioritize_personal=True)
        if not candidates:
            return {
                "reply": f"There are no matching unassigned {effort.value} tasks available right now.",
                "suggestions": ["What unassigned tasks are due today?", "List medium tasks"],
                "items": [],
            }

        prepared = [self._task_item(task) for task in candidates]
        actionable = [item for item in prepared if item.get("action")]
        if actionable:
            choice = actionable[0]
            return {
                "reply": "I found an unassigned task you can take. Confirm below if you want me to assign it to you.",
                "suggestions": ["List low tasks", "Who has the most capacity left?"],
                "items": [choice],
            }

        return {
            "reply": "I found matching tasks, but none fit your current capacity automatically.",
            "suggestions": ["Who has the most capacity left?", "List low tasks"],
            "items": prepared[:5],
        }

    def _task_item(self, task: Task) -> dict:
        assignee_label = "Unassigned"
        if task.assignee:
            if task.assignee_id == self.user.id:
                assignee_label = "You"
            elif task.assignee.show_in_member_lists or self.user.is_admin:
                assignee_label = task.assignee.full_name
            else:
                assignee_label = "Hidden member"

        meta_parts = [
            task.status.value.replace("_", " "),
            task.effort_level.value,
            f"{task.points_value} pts",
            f"due {task.due_date}",
        ]
        if task.assignment_date:
            meta_parts.append(f"planned {task.assignment_date}")
        meta_parts.append(assignee_label)

        item = {
            "title": task.title,
            "meta": " | ".join(meta_parts),
        }

        if task.assignee_id is None and task.status != TaskStatus.COMPLETED:
            action = self._self_assign_action(task)
            if action is not None:
                item["action"] = action

        return item

    def _self_assign_action(self, task: Task) -> dict | None:
        target_date = task.due_date if task.due_date >= date.today() else date.today()
        validation = self.workload.validate_assignment(
            user_id=self.user.id,
            date_value=target_date,
            task_points=task.points_value,
            exclude_task_id=task.id,
        )

        if validation["valid"]:
            action_date = target_date
            label = f"Assign to me ({action_date.isoformat()})"
        elif validation.get("next_available_date"):
            action_date = date.fromisoformat(validation["next_available_date"])
            label = f"Assign to me on {action_date.isoformat()}"
        else:
            return None

        return {
            "type": "assign_self",
            "label": label,
            "task_id": task.id,
            "assignment_date": action_date.isoformat(),
        }

    def _filter_tasks(
        self,
        tasks: list[Task],
        *,
        effort: EffortLevel | None,
        due_today: bool,
        assigned_today: bool,
        status_filter: TaskStatus | None,
        date_filter: _DateFilter | None,
        assignee_id: int | None,
        overdue: bool,
        active_only: bool,
    ) -> list[Task]:
        filtered = tasks
        today = date.today()
        if effort is not None:
            filtered = [task for task in filtered if task.effort_level == effort]
        if due_today:
            filtered = [task for task in filtered if task.due_date == today]
        if assigned_today:
            filtered = [
                task
                for task in filtered
                if task.assignee_id == self.user.id and task.assignment_date == today
            ]
        if date_filter is not None:
            filtered = [task for task in filtered if self._matches_date_filter(task, date_filter)]
        if assignee_id is not None:
            filtered = [task for task in filtered if task.assignee_id == assignee_id]
        if overdue:
            filtered = [task for task in filtered if self._is_task_overdue(task, today=today)]
        if status_filter is not None:
            filtered = [task for task in filtered if task.status == status_filter]
        elif active_only:
            filtered = [task for task in filtered if task.status != TaskStatus.COMPLETED]
        return filtered

    def _sort_tasks(self, tasks: list[Task], *, prioritize_personal: bool) -> list[Task]:
        today = date.today()

        def key(task: Task) -> tuple:
            planned = task.assignment_date or task.due_date
            ownership_bucket = 0
            if prioritize_personal:
                ownership_bucket = 0 if task.created_by_id == self.user.id or task.assignee_id == self.user.id else 1
            if self._is_task_overdue(task, today=today):
                bucket = 0
            elif planned == today or task.due_date == today:
                bucket = 1
            elif planned > today:
                bucket = 2
            else:
                bucket = 3
            if prioritize_personal:
                return (ownership_bucket, bucket, planned, task.due_date, task.title.lower(), task.id)
            return (ownership_bucket, bucket, planned, task.due_date, -task.id, task.title.lower())

        return sorted(tasks, key=key)

    def _task_label(
        self,
        *,
        effort: EffortLevel | None,
        only_unassigned: bool,
        due_today: bool,
        assigned_today: bool,
        status_filter: TaskStatus | None,
        date_filter: _DateFilter | None,
        assignee_id: int | None,
        overdue: bool,
        active_only: bool,
    ) -> str:
        label_parts = []
        if status_filter is not None:
            label_parts.append(status_filter.value.replace("_", " "))
        elif active_only:
            label_parts.append("active")
        if effort is not None:
            label_parts.append(effort.value)
        if only_unassigned:
            label_parts.append("unassigned")
        elif assigned_today:
            label_parts.append("assigned to you today")
        elif assignee_id is not None:
            member = self.db.get(User, assignee_id)
            if member:
                label_parts.append(f"for {member.full_name}")
        if overdue:
            label_parts.append("overdue")
        if due_today:
            label_parts.append("due today")
        elif date_filter is not None:
            field_label = {
                "due": "due on",
                "assignment": "planned on",
                "either": "due/planned on",
            }.get(date_filter.field, "on")
            label_parts.append(f"{field_label} {date_filter.value.isoformat()}")
        return " ".join(label_parts).strip()

    def _ai_intent_response(self, *, message: str, query: str) -> dict | None:
        if not self._could_use_ai_intent(query):
            return None

        visible_members = self._member_users()
        raw = AIOrchestratorService(self.db).parse_assistant_intent(
            message=message,
            visible_members=[member.full_name for member in visible_members],
            today=date.today().isoformat(),
        )
        if not isinstance(raw, dict):
            return None

        try:
            confidence = float(raw.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.65:
            return None

        intent = str(raw.get("intent") or "").strip().lower()
        if intent == "unsupported_action":
            return self._unsupported_action_response()
        if intent == "capacity":
            effort = self._effort_from_value(raw.get("capacity_effort") or raw.get("effort"))
            return self._capacity_for_effort_response(effort) if effort else self._most_capacity_response()
        if intent != "list_tasks":
            return None

        effort = self._effort_from_value(raw.get("effort"))
        status_filter = self._status_from_value(raw.get("status"))
        raw_status = str(raw.get("status") or "active").strip().lower()
        active_only = status_filter is None and raw_status in {"active", "open", "none", ""}
        date_filter = self._date_filter_from_ai(raw)
        member_filter = self._member_filter_from_ai(raw, visible_members=visible_members)
        if member_filter.ambiguous_names:
            return None

        return self._list_tasks_response(
            effort=effort,
            only_unassigned=member_filter.unassigned,
            due_today=False,
            assigned_today=False,
            status_filter=status_filter,
            date_filter=date_filter,
            assignee_id=member_filter.user.id if member_filter.user else None,
            overdue=False,
            active_only=active_only,
            personal_only=not (member_filter.unassigned or member_filter.user is not None),
        )

    @staticmethod
    def _resolve_context_item(query: str, context_items: list[dict]) -> dict | None:
        actionable = [item for item in context_items if item.get("action", {}).get("type") == "assign_self"]
        if not actionable:
            return None

        index = AppAssistantService._extract_reference_index(query)
        if index is not None:
            return actionable[index] if 0 <= index < len(actionable) else None

        if AppAssistantService._mentions_context_reference(query) and len(actionable) == 1:
            return actionable[0]

        return None

    def _member_users(self) -> list[User]:
        return list(
            self.db.scalars(
                select(User)
                .where(
                    User.is_active.is_(True),
                    User.approval_status == AuthService.APPROVAL_APPROVED,
                    User.show_in_member_lists.is_(True),
                )
                .order_by(User.full_name.asc())
            ).all()
        )

    def _points_for_effort(self, effort: EffortLevel) -> int:
        tasks = self.task_service.get_tasks()
        for task in tasks:
            if task.effort_level == effort:
                return task.points_value
        return self.task_service._points_for_level(effort)

    def _resolve_member_filter(self, query: str) -> _MemberFilter:
        if self._is_unassigned_query(query):
            return _MemberFilter(unassigned=True)
        if any(flag in query for flag in ("assigned to me", "my tasks", "my task", "for me", "mine")):
            return _MemberFilter(user=self.user)

        normalized_query = self._normalize_text(query)
        visible_members = self._member_users()
        full_matches = [
            member
            for member in visible_members
            if self._normalize_text(member.full_name) and self._normalize_text(member.full_name) in normalized_query
        ]
        if full_matches:
            unique = {member.id: member for member in full_matches}
            if len(unique) == 1:
                return _MemberFilter(user=next(iter(unique.values())))
            return _MemberFilter(ambiguous_names=tuple(member.full_name for member in unique.values()))

        token_matches = []
        for member in visible_members:
            name_parts = [part for part in self._normalize_text(member.full_name).split() if len(part) >= 3]
            if any(self._query_targets_name_token(normalized_query, part) for part in name_parts):
                token_matches.append(member)

        unique = {member.id: member for member in token_matches}
        if len(unique) == 1:
            return _MemberFilter(user=next(iter(unique.values())))
        if len(unique) > 1:
            return _MemberFilter(ambiguous_names=tuple(member.full_name for member in unique.values()))
        return _MemberFilter()

    @staticmethod
    def _query_targets_name_token(normalized_query: str, token: str) -> bool:
        reserved = {
            "active",
            "assigned",
            "available",
            "capacity",
            "completed",
            "done",
            "due",
            "high",
            "late",
            "low",
            "medium",
            "open",
            "overdue",
            "planned",
            "pending",
            "scheduled",
            "task",
            "tasks",
            "today",
            "tomorrow",
            "unassigned",
        }
        if token in reserved:
            return False
        target_phrases = (
            f"for {token}",
            f"to {token}",
            f"by {token}",
            f"member {token}",
            f"person {token}",
        )
        return any(phrase in normalized_query for phrase in target_phrases)

    def _member_filter_from_ai(self, raw: dict, *, visible_members: list[User]) -> _MemberFilter:
        value = raw.get("assignee")
        if value is None:
            return _MemberFilter()
        normalized = self._normalize_text(str(value))
        if normalized in {"", "any", "all", "everyone"}:
            return _MemberFilter()
        if normalized in {"me", "myself", "mine"}:
            return _MemberFilter(user=self.user)
        if normalized == "unassigned":
            return _MemberFilter(unassigned=True)
        matches = [member for member in visible_members if self._normalize_text(member.full_name) == normalized]
        if len(matches) == 1:
            return _MemberFilter(user=matches[0])
        return _MemberFilter()

    def _date_filter_from_ai(self, raw: dict) -> _DateFilter | None:
        raw_date = raw.get("date")
        if not raw_date:
            return None
        try:
            parsed = date.fromisoformat(str(raw_date))
        except ValueError:
            return None
        field = str(raw.get("date_field") or "either").strip().lower()
        if field not in {"due", "assignment", "either"}:
            field = "either"
        return _DateFilter(value=parsed, field=field)

    def _extract_date_filter(self, query: str) -> _DateFilter | None:
        parsed = self._extract_date_value(query)
        if parsed is None:
            return None
        query_words = set(self._normalize_text(query).split())
        if query_words & {"planned", "assigned", "scheduled", "schedule"}:
            field = "assignment"
        elif "due" in query_words:
            field = "due"
        else:
            field = "either"
        return _DateFilter(value=parsed, field=field)

    def _extract_date_value(self, query: str) -> date | None:
        today = date.today()
        if "day after tomorrow" in query:
            return today + timedelta(days=2)
        if "tomorrow" in query:
            return today + timedelta(days=1)
        if "yesterday" in query:
            return today - timedelta(days=1)
        if "today" in query or "today's" in query or "todays" in query:
            return today

        iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", query)
        if iso_match:
            try:
                return date.fromisoformat(iso_match.group(1))
            except ValueError:
                return None

        slash_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", query)
        if slash_match:
            day = int(slash_match.group(1))
            month = int(slash_match.group(2))
            year = int(slash_match.group(3)) if slash_match.group(3) else today.year
            if year < 100:
                year += 2000
            try:
                return date(year, month, day)
            except ValueError:
                return None

        day_month = re.search(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+(20\d{2}))?\b",
            query,
        )
        if day_month:
            day = int(day_month.group(1))
            month = self._MONTHS[day_month.group(2)]
            year = int(day_month.group(3)) if day_month.group(3) else today.year
            try:
                return date(year, month, day)
            except ValueError:
                return None

        month_day = re.search(
            r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(20\d{2}))?\b",
            query,
        )
        if month_day:
            month = self._MONTHS[month_day.group(1)]
            day = int(month_day.group(2))
            year = int(month_day.group(3)) if month_day.group(3) else today.year
            try:
                return date(year, month, day)
            except ValueError:
                return None

        return None

    @staticmethod
    def _matches_date_filter(task: Task, date_filter: _DateFilter) -> bool:
        if date_filter.field == "due":
            return task.due_date == date_filter.value
        if date_filter.field == "assignment":
            return task.assignment_date == date_filter.value
        return task.due_date == date_filter.value or task.assignment_date == date_filter.value

    @staticmethod
    def _is_task_overdue(task: Task, *, today: date) -> bool:
        if task.status == TaskStatus.COMPLETED:
            return False
        return task.due_date < today or (task.assignment_date is not None and task.assignment_date < today)

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    @staticmethod
    def _effort_from_value(value: object) -> EffortLevel | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        for effort in EffortLevel:
            if effort.value == normalized:
                return effort
        return None

    @staticmethod
    def _status_from_value(value: object) -> TaskStatus | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower().replace(" ", "_")
        if normalized in {"active", "open", "any", "all"}:
            return None
        for status_item in TaskStatus:
            if status_item.value == normalized:
                return status_item
        return None

    @staticmethod
    def _extract_effort(query: str) -> EffortLevel | None:
        if "high" in query:
            return EffortLevel.HIGH
        if "medium" in query:
            return EffortLevel.MEDIUM
        if "low" in query:
            return EffortLevel.LOW
        return None

    @staticmethod
    def _is_capacity_query(query: str) -> bool:
        return "capacity" in query or "room" in query or "available" in query

    @staticmethod
    def _is_assign_me_query(query: str) -> bool:
        return "add me" in query or "assign me" in query or "pick up" in query

    @staticmethod
    def _is_due_today_query(query: str) -> bool:
        if "today" not in query:
            return False
        if any(flag in query for flag in ("assigned to me", "my tasks", "my task", "for me")):
            return False
        return any(flag in query for flag in ("due", "expected", "for today", "today's", "todays", "today"))

    @staticmethod
    def _is_assigned_today_query(query: str) -> bool:
        return "today" in query and any(
            flag in query
            for flag in ("assigned to me", "my tasks", "my task", "for me")
        )

    @staticmethod
    def _is_unassigned_query(query: str) -> bool:
        return any(flag in query for flag in ("unassigned", "available task", "available tasks", "open task", "open tasks"))

    @staticmethod
    def _is_overdue_query(query: str) -> bool:
        return any(flag in query for flag in ("overdue", "late", "past due"))

    @staticmethod
    def _is_task_query(query: str) -> bool:
        return any(
            flag in query
            for flag in (
                "task",
                "tasks",
                "due today",
                "today",
                "assigned to me",
                "unassigned",
                "show",
                "find",
                "list",
                "search",
                "planned",
                "scheduled",
                "overdue",
            )
        )

    @staticmethod
    def _extract_status(query: str) -> TaskStatus | None:
        if "in progress" in query:
            return TaskStatus.IN_PROGRESS
        if "not done" in query or "not completed" in query:
            return None
        if "completed" in query or "done" in query:
            return TaskStatus.COMPLETED
        if "pending" in query:
            return TaskStatus.PENDING
        return None

    @staticmethod
    def _active_only(*, query: str, status_filter: TaskStatus | None) -> bool:
        if status_filter is not None:
            return False
        if "include completed" in query or "with completed" in query:
            return False
        return True

    @staticmethod
    def _is_unsupported_write_query(query: str) -> bool:
        if AppAssistantService._is_assign_me_query(query):
            return False
        normalized_words = set(AppAssistantService._normalize_text(query).split())
        task_words = {"task", "tasks", "chore", "chores", "job", "jobs"}
        write_verbs = {"create", "add", "make", "move", "reschedule", "schedule", "delete", "remove", "edit", "change"}
        if normalized_words & task_words and normalized_words & write_verbs:
            return True
        write_markers = (
            "create task",
            "create a task",
            "new task",
            "add task",
            "add a task",
            "move task",
            "move this task",
            "reschedule",
            "delete task",
            "remove task",
            "edit task",
            "change task",
        )
        return any(marker in query for marker in write_markers)

    @staticmethod
    def _could_use_ai_intent(query: str) -> bool:
        if len(query.split()) < 3:
            return False
        return any(flag in query for flag in ("task", "tasks", "capacity", "room", "show", "find", "which", "who", "what"))

    @staticmethod
    def _is_team_scope_query(query: str) -> bool:
        normalized = AppAssistantService._normalize_text(query)
        return any(marker in normalized for marker in ("team", "everyone", "everybody", "all tasks", "all members", "shared"))

    @staticmethod
    def _extract_reference_index(query: str) -> int | None:
        ordered_markers = (
            (0, ("first", "1st", "number 1", "task 1")),
            (1, ("second", "2nd", "number 2", "task 2")),
            (2, ("third", "3rd", "number 3", "task 3")),
        )
        for index, markers in ordered_markers:
            if any(marker in query for marker in markers):
                return index
        return None

    @staticmethod
    def _mentions_context_reference(query: str) -> bool:
        return any(marker in query for marker in ("this", "that", "first", "second", "third", "1st", "2nd", "3rd"))
