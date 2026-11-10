import requests
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.config import TODOIST_TOKEN, logger, sentry_sdk
from app.models import TaskItem, TodoistTaskResponse
from typing import Dict, Any, List, Optional

router = APIRouter(prefix="/dashboard/todoist", tags=["Todoist"])
API_URL = "https://api.todoist.com/api/v1/tasks"


def get_todoist_headers(json_content: bool = False):
    if not TODOIST_TOKEN:
        raise HTTPException(status_code=503, detail="Todoist integration is not configured")
    headers = {"Authorization": f"Bearer {TODOIST_TOKEN}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


@router.get("", response_model=List[TodoistTaskResponse])
@router.get("/tasks", response_model=List[TodoistTaskResponse])
def get_todoist_tasks(current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = requests.get(API_URL, headers=get_todoist_headers(), timeout=15)
        response.raise_for_status()
        return response.json().get("results", [])
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Todoist fetch failed: %s", exc)
        return []


@router.get("/tasks/search", response_model=List[TodoistTaskResponse])
def search_todoist_tasks(q: Optional[str] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = requests.get("https://api.todoist.com/api/v1/tasks/filter", headers=get_todoist_headers(), params={"query": f"search: {q}"} if q else {}, timeout=15)
        response.raise_for_status()
        return response.json().get("results", [])
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=502, detail="Todoist search failed") from exc


@router.post("", status_code=201)
@router.post("/tasks", status_code=201)
def add_todoist_task(task: TaskItem, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = requests.post(API_URL, headers=get_todoist_headers(True), json=task.model_dump(exclude_unset=True), timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=502, detail="Failed to create Todoist task") from exc


@router.post("/tasks/{task_id}")
def update_todoist_task(task_id: str, task: TaskItem, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = requests.post(f"{API_URL}/{task_id}", headers=get_todoist_headers(True), json=task.model_dump(exclude_unset=True), timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=502, detail="Failed to update Todoist task") from exc


@router.post("/tasks/{task_id}/complete")
def complete_todoist_task(task_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = requests.post(f"{API_URL}/{task_id}/close", headers=get_todoist_headers(), timeout=15)
        response.raise_for_status()
        return {"status": "success", "task_id": task_id}
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=502, detail="Could not complete Todoist task") from exc


@router.delete("/tasks/{task_id}")
def delete_todoist_task(task_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = requests.delete(f"{API_URL}/{task_id}", headers=get_todoist_headers(), timeout=15)
        response.raise_for_status()
        return {"status": "deleted", "task_id": task_id}
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=502, detail="Failed to delete Todoist task") from exc
