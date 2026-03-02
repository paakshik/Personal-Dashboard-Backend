import requests
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.config import TODOIST_TOKEN,logger,sentry_sdk
from app.models import TaskItem
from typing import Dict,Any,List
from app.models import TodoistTaskResponse

router = APIRouter(prefix="/dashboard/todoist", tags=["Todoist"])
API_URL = "https://api.todoist.com/api/v1/tasks"


@router.get("/tasks", response_model=List[TodoistTaskResponse])
def get_todoist_tasks(
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Fetches active tasks from the Todoist account configured on the server.

    This endpoint proxies a request to the official Todoist REST API using the
    server-side API token.

    Args:
        current_user (Dict[str, Any]): The authenticated user (injected by dependency).

    Returns:
        List[Dict[str, Any]]: A list of task objects from Todoist. Returns an empty list
                              if the token is missing or an error occurs.
    """
    try:
        headers = get_todoist_headers()
        resp = requests.get(API_URL, headers=headers)
        resp.raise_for_status()

        tasks = resp.json().get("results", [])
        logger.info(f"Fetched {len(tasks)} tasks for {current_user.get('email')}")
        return tasks
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Todoist tasks: {e}")
        sentry_sdk.capture_exception(e)
        return []
    except Exception as e:
        logger.critical(f"Unexpected error in get_todoist: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return []


@router.post("/tasks")
def add_todoist_task(
        task: TaskItem,
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Creates a new task in the Admin's Todoist account.

    This endpoint accepts a task payload, sanitizes it, and sends it to the
    Todoist REST API using the server-side `TODOIST_TOKEN`.

    Args:
        task (TaskItem): The Pydantic model containing task details (content, description, etc.).
        current_user (Dict[str, Any]): The authenticated user.

    Returns:
        Dict[str, Any]: The created task object returned by Todoist.

    Raises:
        HTTPException(500): If the request to Todoist fails.
    """
    try:
        headers = get_todoist_headers(json_content=True)
        payload = task.model_dump(exclude_unset=True)

        resp = requests.post(API_URL, headers=headers, json=payload)
        resp.raise_for_status()

        data = resp.json()
        logger.info(
            f"Task created via Todoist API by {current_user.get('email')}: {data.get('id')}")
        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"Todoist Creation Failed: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="Failed to create task in Todoist")

    except Exception as e:
        logger.critical(f"Unexpected error in add_todoist_task: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=f"Unexpected error in add_todoist_task: {e}")

@router.post("/tasks/{task_id}")
def update_todoist_task(
    task_id: str,
    task: TaskItem,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Updates an existing task in Todoist.

    This endpoint sends a specific task ID and the new data to the Todoist API.
    It uses 'exclude_none=True' to ensure we only update fields that
    actually have data, preserving the others.

    Args:
        task_id (str): The ID of the task to update (from the URL).
        task (TaskItem): The new task details.
        current_user (Dict[str, Any]): The authenticated user.

    Returns:
        Dict[str, Any]: The updated task object from Todoist.

    Raises:
        HTTPException(500): If the update fails or the task ID is invalid.
    """
    try:
        headers = get_todoist_headers(json_content=True)
        payload = task.model_dump(exclude_unset=True)
        update_url = f"{API_URL}/{task_id}"
        resp = requests.post(update_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Task {task_id} updated by {current_user.get('email')}")
        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"Todoist Update Failed for {task_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="Failed to update task")

    except Exception as e:
        logger.critical(f"Unexpected error in update_task: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=f"Unexpected error in update_task: {e}")


@router.post("/tasks/{task_id}/complete")
def complete_todoist_task(
        task_id: str,
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Marks a Todoist task as completed (closed).

    This endpoint hits the Todoist '/close' endpoint for a specific task ID.
    No request body is required as the ID is handled in the URL path.

    Args:
        task_id (str): The unique ID of the task to be completed.
        current_user (Dict[str, Any]): The authenticated user performing the action.

    Returns:
        Dict[str, Any]: A confirmation status and the ID of the completed task.

    Raises:
        HTTPException(500): If the Todoist API returns an error or is unreachable.
    """
    try:
        headers = get_todoist_headers()
        complete_url = f"{API_URL}/{task_id}/close"

        # 3. External API Request
        # Todoist requires a POST for closing, even with an empty body
        resp = requests.post(complete_url, headers=headers)
        resp.raise_for_status()

        logger.info(
            f"Task {task_id} marked as completed by {current_user.get('email')}")

        return {
            "status": "success",
            "message": "Task completed",
            "task_id": task_id
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to complete Todoist task {task_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500,
                            detail="Could not complete task in Todoist")

    except Exception as e:
        logger.critical(f"Unexpected error in complete_todoist_task: {e}",
                        exc_info=True)
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=f"Unexpected error in complete_todoist_task: {e}")

@router.delete("/tasks/{task_id}")
def delete_todoist_task(
    task_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Permanently deletes a task from the configured Todoist account.

    This endpoint accepts a task ID and sends a DELETE request to the Todoist API.
    If successful, the task is permanently removed and cannot be recovered.

    Args:
        task_id (str): The unique ID of the task to delete.
        current_user (Dict[str, Any]): The authenticated user requesting the deletion.

    Returns:
        Dict[str, str]: A confirmation message containing the deleted task ID.

    Raises:
        HTTPException(500): If the Todoist API fails or the task ID is invalid.
    """
    try:
        headers = get_todoist_headers()

        delete_url = f"{API_URL}/{task_id}"

        resp = requests.delete(delete_url, headers=headers)
        resp.raise_for_status()

        logger.info(f"Task {task_id} deleted by {current_user.get('email')}")

        # You requested to return a JSON status, so we return a Dict
        return {
            "status": "deleted",
            "task_id": task_id
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to delete Todoist task {task_id}: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="Failed to delete task in Todoist")

    except Exception as e:
        logger.critical(f"Unexpected error in delete_todoist_task: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="Internal Server Error")

def get_todoist_headers(json_content: bool = False) -> Dict[
    str, str]:
    """
    Constructs the standard HTTP headers required for Todoist API requests.

    This function handles authentication via Bearer token and optionally sets
    the Content-Type for JSON payloads. It includes safety checks to ensure
    critical authentication data is present before attempting a request.

    Args:
        json_content (bool, optional): If True, adds 'Content-Type: application/json'
                                       to the headers. Defaults to False.

    Returns:
        Dict[str, str]: A dictionary containing the standard headers.

    Raises:
        ValueError: If the provided token is missing or empty. This error is
                    also captured by Sentry and logged before raising.
    """
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {TODOIST_TOKEN}"
    }
    if json_content:
        headers["Content-Type"] = "application/json"
    return headers