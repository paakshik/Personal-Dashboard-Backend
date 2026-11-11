import threading

import requests
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.config import logger, sentry_sdk
from app.db_store import get_todoist_credential, save_todoist_credential
from app.utils.token_expiry import todoist_expires_at
from app.models import TaskItem, TodoistTaskResponse
from typing import Dict, Any, List, Optional

router = APIRouter(prefix="/dashboard/todoist", tags=["Todoist"])
API_URL = "https://api.todoist.com/api/v1/tasks"

# Per-user locks for refresh-token rotation concurrency safety.
# Ensures concurrent requests for the same user don't both attempt a refresh.
_refresh_locks: Dict[str, threading.Lock] = {}
_refresh_locks_lock = threading.Lock()


def _get_refresh_lock(user_id: str) -> threading.Lock:
    with _refresh_locks_lock:
        if user_id not in _refresh_locks:
            _refresh_locks[user_id] = threading.Lock()
        return _refresh_locks[user_id]


def _build_headers(access_token: str, json_content: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers


def _get_credential_or_403(user_id: str) -> dict:
    credential = get_todoist_credential(user_id)
    if not credential:
        raise HTTPException(status_code=401, detail="Todoist not connected; reconnect_required")
    return credential


def _delete_todoist_credential(user_id: str) -> None:
    """Delete stored Todoist credential for a user so they must reconnect."""
    try:
        from app.db_store import delete_todoist_credential
        delete_todoist_credential(user_id)
    except Exception as exc:
        logger.error("Failed to delete Todoist credential for user %s: %s", user_id, exc)
        sentry_sdk.capture_exception(exc)


def _refresh_access_token(credential: dict) -> dict:
    """Call the Todoist token endpoint to rotate the access token.

    Returns a new tokens dict containing a fresh access_token and (on rotation)
    a new refresh_token. Both are passed to the caller for persistent storage.
    """
    from app.config import TODOIST_CLIENT_ID, TODOIST_CLIENT_SECRET, TODOIST_TOKEN_URL

    client_id = credential.get("client_id") or TODOIST_CLIENT_ID
    client_secret = TODOIST_CLIENT_SECRET
    refresh_token = credential.get("refresh_token")

    if not client_id or not client_secret or not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Todoist credentials cannot be refreshed; reconnect_required",
        )

    try:
        response = requests.post(
            TODOIST_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
        )
        if response.status_code == 400:
            logger.warning("Todoist refresh token rejected (HTTP 400); body=%s", response.text[:500])
            raise HTTPException(
                status_code=401,
                detail="Todoist token rejected: 400; reconnect_required",
            )
        response.raise_for_status()
        data = response.json()
    except HTTPException:
        raise
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Todoist token refresh failed")
        raise HTTPException(status_code=502, detail="Todoist token refresh failed") from exc

    # Token rotation: Todoist may issue a new refresh_token alongside the new
    # access_token. Keep the old refresh_token if none is returned.
    new_access_token = data.get("access_token")
    if not isinstance(new_access_token, str) or not new_access_token:
        logger.error("Todoist refresh response did not contain an access token")
        raise HTTPException(status_code=502, detail="Todoist refresh response was invalid; please reconnect")
    new_refresh_token = data.get("refresh_token") or refresh_token
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_uri": credential.get("token_uri"),
        "client_id": client_id,
        "scopes": credential.get("scopes", []),
        "expires_at": todoist_expires_at(data.get("expires_in")),
    }


def _todoist_request(method: str, url: str, user_id: str, json_content: bool = False,
                     json_body: Optional[dict] = None, params: Optional[dict] = None):
    """Make a Todoist API request using the user's decrypted access token.

    On a 401 (expired access token), performs refresh-token rotation once under
    a per-user lock and retries the request with the new access token.
    If the refresh itself fails (invalid/expired refresh token), deletes the
    stored credential and returns 401 with reconnect_required so the frontend
    can ask the user to reconnect.
    """
    credential = _get_credential_or_403(user_id)
    access_token = credential["access_token"]

    def attempt(token: str) -> requests.Response:
        return requests.request(
            method,
            url,
            headers=_build_headers(token, json_content=json_content),
            json=json_body,
            params=params,
            timeout=15,
        )

    response = attempt(access_token)

    if response.status_code in (401, 403):
        logger.warning("Todoist API rejected request (HTTP %s) for user %s; body=%s",
                       response.status_code, user_id, response.text[:500])
        original_access_token = access_token
        lock = _get_refresh_lock(user_id)
        with lock:
            # Another in-flight request may already have rotated this user's token.
            credential = get_todoist_credential(user_id)
            if not credential:
                _delete_todoist_credential(user_id)
                raise HTTPException(status_code=401, detail="Todoist not connected; reconnect_required")
            if credential["access_token"] == original_access_token:
                try:
                    new_tokens = _refresh_access_token(credential)
                except HTTPException as exc:
                    # Refresh failed: refresh token invalid/expired. Delete credential and require reconnect.
                    _delete_todoist_credential(user_id)
                    raise HTTPException(
                        status_code=401,
                        detail=f"Todoist token rejected: {exc.status_code}; reconnect_required",
                    ) from exc
                saved = save_todoist_credential(user_id, new_tokens)
                if not saved:
                    _delete_todoist_credential(user_id)
                    raise HTTPException(status_code=401, detail="Todoist refreshed credentials could not be saved; reconnect_required")
                access_token = new_tokens["access_token"]
            else:
                access_token = credential["access_token"]
        response = attempt(access_token)

        if response.status_code in (401, 403):
            # Still rejected after refresh: credential is unusable.
            _delete_todoist_credential(user_id)
            logger.warning("Todoist credential still rejected after refresh (HTTP %s); deleted for user %s",
                           response.status_code, user_id)
            raise HTTPException(
                status_code=401,
                detail=f"Todoist token rejected: {response.status_code}; reconnect_required",
            )

        # Cleanup: drop this user's refresh-lock entry once the refresh is done so
        # the in-memory _refresh_locks dict does not grow unboundedly over time.
        with _refresh_locks_lock:
            _refresh_locks.pop(user_id, None)

    return response


@router.get("/status")
def get_todoist_status(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Return whether the current user has a stored Todoist access token."""
    credential = get_todoist_credential(current_user["id"])
    return {"connected": bool(credential and credential.get("access_token"))}


@router.get("", response_model=List[TodoistTaskResponse])
@router.get("/tasks", response_model=List[TodoistTaskResponse])
def get_todoist_tasks(current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = _todoist_request("GET", API_URL, current_user["id"])
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            logger.error("Todoist task response was not valid JSON")
            raise HTTPException(status_code=502, detail="Todoist returned an invalid task response") from exc
        if isinstance(payload, list):
            tasks = payload
        elif isinstance(payload, dict):
            tasks = payload.get("results", payload.get("tasks"))
            if tasks is None and isinstance(payload.get("items"), list):
                tasks = payload["items"]
        else:
            raise HTTPException(status_code=502, detail="Todoist returned an invalid task response")
        if not isinstance(tasks, list):
            raise HTTPException(status_code=502, detail="Todoist returned an invalid task list")
        return [
            {
                "id": task.get("id"),
                "content": task.get("content"),
                "description": task.get("description") or "",
                "project_id": task.get("project_id"),
                "due": task.get("due"),
                "labels": task.get("labels") or [],
                "priority": task.get("priority", 1),
                "is_completed": bool(task.get("is_completed", task.get("is_complete", False))),
            }
            for task in tasks
            if isinstance(task, dict)
        ]
    except HTTPException:
        raise
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Todoist fetch failed")
        raise HTTPException(status_code=502, detail="Failed to fetch Todoist tasks") from exc


@router.get("/tasks/search", response_model=List[TodoistTaskResponse])
def search_todoist_tasks(q: Optional[str] = None, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = _todoist_request(
            "GET",
            "https://api.todoist.com/api/v1/tasks/filter",
            current_user["id"],
            params={"query": f"search: {q}"} if q else {},
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return payload.get("results", [])
        raise HTTPException(status_code=502, detail="Todoist returned an invalid task response")
    except HTTPException:
        raise
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Todoist search failed")
        raise HTTPException(status_code=502, detail="Todoist search failed") from exc


@router.post("", status_code=201)
@router.post("/tasks", status_code=201)
def add_todoist_task(task: TaskItem, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = _todoist_request(
            "POST",
            API_URL,
            current_user["id"],
            json_content=True,
            json_body=task.model_dump(exclude_unset=True),
        )
        response.raise_for_status()
        return response.json()
    except HTTPException:
        raise
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Failed to create Todoist task")
        raise HTTPException(status_code=502, detail="Failed to create Todoist task") from exc


@router.post("/tasks/{task_id}")
def update_todoist_task(task_id: str, task: TaskItem, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = _todoist_request(
            "POST",
            f"{API_URL}/{task_id}",
            current_user["id"],
            json_content=True,
            json_body=task.model_dump(exclude_unset=True),
        )
        response.raise_for_status()
        return response.json()
    except HTTPException:
        raise
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Failed to update Todoist task")
        raise HTTPException(status_code=502, detail="Failed to update Todoist task") from exc


@router.post("/tasks/{task_id}/complete")
def complete_todoist_task(task_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = _todoist_request(
            "POST",
            f"{API_URL}/{task_id}/close",
            current_user["id"],
        )
        response.raise_for_status()
        return {"status": "success", "task_id": task_id}
    except HTTPException:
        raise
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Could not complete Todoist task")
        raise HTTPException(status_code=502, detail="Could not complete Todoist task") from exc


@router.delete("/tasks/{task_id}")
def delete_todoist_task(task_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = _todoist_request(
            "DELETE",
            f"{API_URL}/{task_id}",
            current_user["id"],
        )
        response.raise_for_status()
        return {"status": "deleted", "task_id": task_id}
    except HTTPException:
        raise
    except requests.RequestException as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("Failed to delete Todoist task")
        raise HTTPException(status_code=502, detail="Failed to delete Todoist task") from exc
