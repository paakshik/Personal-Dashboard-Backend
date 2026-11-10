import threading

import requests
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.config import logger, sentry_sdk
from app.db_store import get_todoist_credential, save_todoist_credential
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
        raise HTTPException(status_code=403, detail="Todoist not connected")
    return credential


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
            status_code=403,
            detail="Todoist credentials cannot be refreshed; please reconnect",
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
            raise HTTPException(
                status_code=403,
                detail="Todoist refresh token invalid; please reconnect",
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
    new_refresh_token = data.get("refresh_token") or refresh_token
    return {
        "access_token": data.get("access_token"),
        "refresh_token": new_refresh_token,
        "token_uri": credential.get("token_uri"),
        "client_id": client_id,
        "scopes": credential.get("scopes", []),
        "expires_at": data.get("expires_in"),
    }


def _todoist_request(method: str, url: str, user_id: str, json_content: bool = False,
                     json_body: Optional[dict] = None, params: Optional[dict] = None):
    """Make a Todoist API request using the user's decrypted access token.

    On a 401 (expired access token), performs refresh-token rotation once under
    a per-user lock and retries the request with the new access token.
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

    if response.status_code == 401:
        lock = _get_refresh_lock(user_id)
        with lock:
            # Re-fetch: another request may have already refreshed this user's tokens.
            credential = get_todoist_credential(user_id)
            if not credential:
                raise HTTPException(status_code=403, detail="Todoist not connected")
            new_tokens = _refresh_access_token(credential)
            save_todoist_credential(user_id, new_tokens)
            access_token = new_tokens["access_token"]
        response = attempt(access_token)

        # Cleanup: drop this user's refresh-lock entry once the refresh is done so
        # the in-memory _refresh_locks dict does not grow unboundedly over time.
        with _refresh_locks_lock:
            _refresh_locks.pop(user_id, None)

    return response


@router.get("", response_model=List[TodoistTaskResponse])
@router.get("/tasks", response_model=List[TodoistTaskResponse])
def get_todoist_tasks(current_user: Dict[str, Any] = Depends(get_current_user)):
    try:
        response = _todoist_request("GET", API_URL, current_user["id"])
        response.raise_for_status()
        return response.json().get("results", [])
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
        return response.json().get("results", [])
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
