import uuid
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.dependencies import get_current_user
from app.db_store import list_projects, get_project as db_get_project, save_project, delete_project as db_delete_project
from app.config import logger, sentry_sdk
from app.models import ProjectItem, ProjectInDB, ProjectsDashboardResponse

router = APIRouter(prefix="/dashboard/projects", tags=["Projects"])


def _payload(project):
    data = project.model_dump()
    data["links"] = data.get("links") or {}
    return data


@router.get("", response_model=ProjectsDashboardResponse)
def get_dashboard_projects(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    projects = list_projects(current_user["id"])
    total = len(projects)
    return {"projects": projects, "stats": {
        "total": total,
        "inProgress": sum(p["status"] in ("in-progress", "in_progress") for p in projects),
        "completed": sum(p["status"] == "completed" for p in projects),
        "planning": sum(p["status"] == "planning" for p in projects),
        "avgProgress": round(sum(p["progress"] for p in projects) / total) if total else 0,
    }}


@router.post("", response_model=ProjectInDB, status_code=201)
def create_project(project: ProjectItem, current_user: dict = Depends(get_current_user)):
    return save_project(current_user["id"], _payload(project))


@router.put("/{project_id}", response_model=ProjectInDB)
def update_project(project_id: str, project: ProjectItem, current_user: dict = Depends(get_current_user)):
    updated = save_project(current_user["id"], _payload(project), project_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated


@router.delete("/{project_id}")
def remove_project(project_id: str, current_user: dict = Depends(get_current_user)):
    deleted = db_delete_project(current_user["id"], project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": deleted["id"], "project_name": deleted["name"]}


@router.get("/search")
def search_projects(q: Optional[str] = Query(None), status: Optional[str] = None, category: Optional[str] = None, priority: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    projects = list_projects(current_user["id"])
    if q:
        term = q.casefold()
        projects = [p for p in projects if term in p["name"].casefold() or term in p["description"].casefold() or any(term in str(t).casefold() for t in p["technologies"])]
    if status:
        projects = [p for p in projects if p["status"] == status]
    if category:
        projects = [p for p in projects if p["category"] == category]
    if priority:
        projects = [p for p in projects if p["priority"] == priority]
    return {"projects": projects, "count": len(projects), "filters": {"search": q, "status": status, "category": category, "priority": priority}}


@router.get("/{project_id}", response_model=ProjectInDB)
def get_project(project_id: str, current_user: dict = Depends(get_current_user)):
    project = db_get_project(current_user["id"], project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
