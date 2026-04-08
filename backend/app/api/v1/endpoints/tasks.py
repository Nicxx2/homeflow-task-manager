from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.task import TaskAssignRequest, TaskCreate, TaskRead, TaskUpdate
from backend.app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.create_unassigned_task(payload, user)
    return task


@router.get("", response_model=list[TaskRead])
def list_tasks(
    only_unassigned: bool | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = TaskService(db)
    tasks = service.get_tasks(only_unassigned=only_unassigned)
    if user.is_admin:
        return tasks
    return [task for task in tasks if task.created_by_id == user.id]


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not user.is_admin and task.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    return task


@router.put("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = TaskService(db)
    task = service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not user.is_admin and task.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    return service.update_task(task, payload)


@router.post("/{task_id}/assign", response_model=TaskRead)
def assign_task(
    task_id: int,
    payload: TaskAssignRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_service = TaskService(db)
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if not user.is_admin and task.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")

    success, validation = task_service.assign_task_with_validation(
        task,
        assignee_id=payload.assignee_id,
        assignment_date=payload.assignment_date,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=validation)
    return task
