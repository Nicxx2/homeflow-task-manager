from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.enums import EffortLevel, TaskStatus
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.services.auth_service import AuthService
from backend.app.services.recurring_task_service import RecurringTaskService
from backend.app.services.task_service import TaskService
from backend.app.services.workload_service import WorkloadService


class AppAssistantService:
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

        effort = self._extract_effort(query)
        due_today = self._is_due_today_query(query)
        assigned_today = self._is_assigned_today_query(query)
        only_unassigned = self._is_unassigned_query(query)
        status_filter = self._extract_status(query)

        if "most capacity" in query or "most room" in query:
            return self._most_capacity_response()

        if effort and self._is_assign_me_query(query):
            return self._assign_me_response(
                effort,
                due_today=due_today,
                only_unassigned=only_unassigned,
                status_filter=status_filter,
            )

        if effort and self._is_capacity_query(query):
            return self._capacity_for_effort_response(effort)

        if self._is_task_query(query):
            return self._list_tasks_response(
                effort=effort,
                only_unassigned=only_unassigned,
                due_today=due_today,
                assigned_today=assigned_today,
                status_filter=status_filter,
            )

        return self._help_response()

    def assign_self_to_task(self, *, task_id: int, assignment_date: date) -> dict:
        task = self.task_service.get_task(task_id)
        if not task:
            return {"ok": False, "reply": "That task no longer exists."}

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
                "What tasks are due today?",
                "What unassigned tasks are due today?",
                "What tasks are assigned to me today?",
                "Who has the most capacity left?",
                "Add me to any low task available",
            ],
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
    ) -> dict:
        tasks = self.task_service.get_tasks(only_unassigned=only_unassigned if only_unassigned else None)
        tasks = self._filter_tasks(
            tasks,
            effort=effort,
            due_today=due_today,
            assigned_today=assigned_today,
            status_filter=status_filter,
        )

        items = [self._task_item(task) for task in tasks[:8]]
        label_parts = []
        if status_filter is not None:
            label_parts.append(status_filter.value.replace("_", " "))
        if effort is not None:
            label_parts.append(effort.value)
        if only_unassigned:
            label_parts.append("unassigned")
        elif assigned_today:
            label_parts.append("assigned to you today")
        if due_today:
            label_parts.append("due today")
        label = " ".join(label_parts).strip()

        if not items:
            return {
                "reply": f"I could not find any {label + ' ' if label else ''}tasks right now.",
                "suggestions": ["What tasks are due today?", "Who has the most capacity left?"],
                "items": [],
            }

        return {
            "reply": f"I found {len(items)} {label + ' ' if label else ''}task{'s' if len(items) != 1 else ''}.",
            "suggestions": ["What unassigned tasks are due today?", "Who has enough capacity for one medium task?"],
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
            capacity = self.workload.get_user_capacity(member.id)
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
            capacity = self.workload.get_user_capacity(member.id)
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
    ) -> dict:
        candidates = self.task_service.get_tasks(only_unassigned=True)
        candidates = self._filter_tasks(
            candidates,
            effort=effort,
            due_today=due_today,
            assigned_today=False,
            status_filter=status_filter,
        )
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
            assignee_label = task.assignee.full_name

        item = {
            "title": task.title,
            "meta": f"{task.effort_level.value} | {task.points_value} pts | due {task.due_date} | {assignee_label}",
        }

        if task.assignee_id is None:
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
    ) -> list[Task]:
        filtered = tasks
        if effort is not None:
            filtered = [task for task in filtered if task.effort_level == effort]
        if due_today:
            today = date.today()
            filtered = [task for task in filtered if task.due_date == today]
        if assigned_today:
            today = date.today()
            filtered = [
                task
                for task in filtered
                if task.assignee_id == self.user.id and task.assignment_date == today
            ]
        if status_filter is not None:
            filtered = [task for task in filtered if task.status == status_filter]
        return filtered

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
        return any(flag in query for flag in ("available", "unassigned", "open"))

    @staticmethod
    def _is_task_query(query: str) -> bool:
        return any(flag in query for flag in ("task", "tasks", "due today", "today", "assigned to me", "unassigned"))

    @staticmethod
    def _extract_status(query: str) -> TaskStatus | None:
        if "in progress" in query:
            return TaskStatus.IN_PROGRESS
        if "completed" in query or "done" in query:
            return TaskStatus.COMPLETED
        if "pending" in query:
            return TaskStatus.PENDING
        return None

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
