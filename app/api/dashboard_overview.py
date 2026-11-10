import requests
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from googleapiclient.discovery import build

from app.config import TODOIST_TOKEN, logger, sentry_sdk
from app.dependencies import get_current_user
from app.db_store import list_chat_messages, list_projects
from app.services.google_auth import get_user_google_creds


router = APIRouter(prefix="/dashboard/overview", tags=["Dashboard Overview"])

TODOIST_API_URL = "https://api.todoist.com/api/v1/tasks"
RECENT_LIMIT = 5


def _google_creds_or_none(user_id: str):
    """Return Google credentials for the user, or None if not connected.

    Swallows the 401 that ``get_user_google_creds`` raises when the account
    is not linked so the overview can degrade gracefully per-section.
    """
    try:
        return get_user_google_creds(user_id)
    except HTTPException:
        return None


def _summary_task(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": task.get("id"),
        "content": task.get("content", ""),
        "priority": task.get("priority", 1),
        "is_completed": task.get("is_completed", False),
        "due": task.get("due"),
    }


def _summary_event(event: Dict[str, Any]) -> Dict[str, Any]:
    start = event.get("start") or {}
    return {
        "id": event.get("id"),
        "title": event.get("summary", "No Title"),
        "start": start.get("dateTime", start.get("date")),
        "link": event.get("htmlLink", ""),
    }


def _summary_email(message: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": message.get("id"),
        "subject": message.get("subject", "(No Subject)"),
        "sender": message.get("sender", "Unknown Sender"),
        "snippet": message.get("snippet", ""),
    }


def _summary_project(project: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": project.get("id"),
        "name": project.get("name", ""),
        "status": project.get("status", ""),
        "progress": project.get("progress", 0),
    }


def _summary_history(message: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": message.get("id"),
        "role": message.get("role"),
        "text": message.get("text", ""),
        "timestamp": message.get("timestamp"),
    }


@router.get("")
def get_dashboard_overview(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Return an aggregated summary of the user's dashboard data.

    Each section reports a count plus a small list of recent items so the
    home page can render stat tiles without calling every detail endpoint.
    Sections degrade independently (zero count, empty list) when a service is
    not configured or unreachable; a failure in one section never breaks the
    others. Uses regular user authentication (get_current_user) because this
    endpoint surfaces the current user's own data, not server-level info.
    """
    user_id = current_user.get("id", "unknown")

    # ---------- Tasks (Todoist) ----------
    task_count = 0
    recent_tasks: List[Dict[str, Any]] = []
    if TODOIST_TOKEN:
        try:
            resp = requests.get(TODOIST_API_URL, headers={"Authorization": f"Bearer {TODOIST_TOKEN}"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                tasks = data.get("results", [])
            elif isinstance(data, list):
                tasks = data
            else:
                tasks = []
            task_count = len(tasks)
            recent_tasks = [_summary_task(t) for t in tasks[:RECENT_LIMIT]]
        except Exception as exc:
            logger.error("Overview: todoist fetch failed for user %s: %s", user_id, exc)
            sentry_sdk.capture_exception(exc)

    # ---------- Events (Google Calendar) ----------
    event_count = 0
    recent_events: List[Dict[str, Any]] = []
    creds = _google_creds_or_none(user_id)
    if creds:
        try:
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            end = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat().replace("+00:00", "Z")
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=now,
                    timeMax=end,
                    maxResults=250,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = result.get("items", [])
            event_count = len(events)
            recent_events = [_summary_event(e) for e in events[:RECENT_LIMIT]]
        except Exception as exc:
            logger.error("Overview: calendar fetch failed for user %s: %s", user_id, exc)
            sentry_sdk.capture_exception(exc)

    # ---------- Emails (Gmail) ----------
    unread_email_count = 0
    recent_emails: List[Dict[str, Any]] = []
    if creds:
        try:
            gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
            result = (
                gmail.users()
                .messages()
                .list(userId="me", q="is:unread", maxResults=RECENT_LIMIT)
                .execute()
            )
            messages = result.get("messages", [])
            unread_email_count = int(result.get("resultSizeEstimate", 0) or 0)
            enriched: List[Dict[str, Any]] = []
            for msg in messages[:RECENT_LIMIT]:
                try:
                    meta = (
                        gmail.users()
                        .messages()
                        .get(userId="me", id=msg["id"], format="metadata")
                        .execute()
                    )
                    headers = meta.get("payload", {}).get("headers", [])
                    subject = next(
                        (h["value"] for h in headers if h.get("name") == "Subject"),
                        "(No Subject)",
                    )
                    sender = next(
                        (h["value"] for h in headers if h.get("name") == "From"),
                        "Unknown Sender",
                    )
                    enriched.append(
                        {
                            "id": msg["id"],
                            "subject": subject,
                            "sender": sender,
                            "snippet": meta.get("snippet", ""),
                        }
                    )
                except Exception:
                    continue
            recent_emails = enriched
        except Exception as exc:
            logger.error("Overview: gmail fetch failed for user %s: %s", user_id, exc)
            sentry_sdk.capture_exception(exc)

    # ---------- Projects (database) ----------
    project_count = 0
    recent_projects: List[Dict[str, Any]] = []
    try:
        projects = list_projects(user_id) or []
        project_count = len(projects)
        recent_projects = [_summary_project(p) for p in projects[:RECENT_LIMIT]]
    except Exception as exc:
        logger.error("Overview: projects fetch failed for user %s: %s", user_id, exc)
        sentry_sdk.capture_exception(exc)

    # ---------- Gemini history (database) ----------
    recent_history: List[Dict[str, Any]] = []
    try:
        history = list_chat_messages(user_id) or []
        recent_history = [_summary_history(m) for m in history[-RECENT_LIMIT:]]
    except Exception as exc:
        logger.error("Overview: history fetch failed for user %s: %s", user_id, exc)
        sentry_sdk.capture_exception(exc)

    return {
        "tasks": {"count": task_count, "recent": recent_tasks},
        "events": {"count": event_count, "recent": recent_events},
        "emails": {"unread_count": unread_email_count, "recent": recent_emails},
        "projects": {"count": project_count, "recent": recent_projects},
        "history": {"count": len(recent_history), "recent": recent_history},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
