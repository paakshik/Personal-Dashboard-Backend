from typing import Optional, Dict, Any, List
import asyncio
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from app.config import logger, sentry_sdk
from app.db_store import save_chat_message as persist_chat_message, list_projects, list_commands
from app.utils.google_services_calender_helper import fetch_upcoming_events, get_google_calendar_service
from app.utils.google_services_gmail_helper import get_gmail_service, fetch_email_body
from app.api.todoist import get_todoist_tasks

# Saved command text can contain tokens or paths, and this context is sent to the
# AI provider. Leave this False unless you want NVIDIA to see the command text.
INCLUDE_COMMAND_TEXT = False


def save_chat_message(
    role: str,
    text: str,
    user_id: str,
    attachment_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a chat message, including attachment and conversation binding."""
    return persist_chat_message(
        role,
        text,
        user_id,
        attachment_id=attachment_id,
        conversation_id=conversation_id,
    )


def persist_conversation_message(
    role: str,
    text: str,
    user_id: str,
    attachment_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> bool:
    """Persist a chat message and return failure without masking model errors."""
    try:
        save_chat_message(role, text, user_id, attachment_id, conversation_id)
        return True
    except Exception as exc:
        logger.error("Chat message persistence failed (%s)", type(exc).__name__)
        sentry_sdk.capture_exception(exc)
        return False


# ---------- Context formatting ----------

def _fmt_events(events: List[Dict[str, Any]]) -> str:
    if not events:
        return "No upcoming events"
    lines = []
    for event in events[:40]:
        start = event.get("start", {})
        when = start.get("dateTime") or start.get("date") or "unknown time"
        lines.append(f"- {when}: {event.get('summary', 'No title')}")
    return "\n".join(lines)


def _fmt_tasks(tasks: List[Dict[str, Any]]) -> str:
    if not tasks:
        return "No pending tasks"
    return "\n".join(f"- {task.get('content', task)}" for task in tasks[:40])


def _fmt_projects(projects: List[Dict[str, Any]]) -> str:
    if not projects:
        return "No projects"
    lines = []
    for project in projects[:25]:
        details = [
            project.get("status"),
            f"{project.get('progress')}% done" if project.get("progress") is not None else None,
            f"priority {project['priority']}" if project.get("priority") else None,
            project.get("category"),
        ]
        line = f"- {project.get('name', 'Untitled')} [{', '.join(d for d in details if d)}]"
        technologies = project.get("technologies") or []
        if technologies:
            line += f" tech: {', '.join(str(t) for t in technologies[:8])}"
        description = (project.get("description") or "").strip().replace("\n", " ")[:200]
        if description:
            line += f" - {description}"
        lines.append(line)
    return "\n".join(lines)


def _fmt_commands(commands: List[Dict[str, Any]]) -> str:
    if not commands:
        return "No saved commands"
    lines = []
    for command in commands[:25]:
        line = f"- {command.get('name', 'Unnamed')}"
        if command.get("category"):
            line += f" ({command['category']})"
        tags = command.get("tags") or []
        if tags:
            line += f" tags: {', '.join(str(t) for t in tags[:6])}"
        description = (command.get("description") or "").strip().replace("\n", " ")[:150]
        if description:
            line += f" - {description}"
        if INCLUDE_COMMAND_TEXT and command.get("command"):
            line += f" | runs: {command['command'][:120]}"
        lines.append(line)
    return "\n".join(lines)


async def _load_source(label: str, loader, *args):
    """Run a blocking loader in a thread. A failing source is skipped, not fatal.

    Returns (data, error) where data is the loader result (or None on failure)
    and error is a human-readable message (or None on success).
    """
    try:
        return await asyncio.to_thread(loader, *args), None
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        logger.warning("Context source '%s' failed: %s", label, message)
        sentry_sdk.capture_exception(exc)
        return None, message


async def gather_user_context(current_user: Dict[str, Any]) -> str:
    email = current_user.get("email", "unknown")
    user_id = current_user.get("id", "unknown")

    def load_calendar():
        service = get_google_calendar_service(current_user)
        return fetch_upcoming_events(service, 30)

    def load_emails():
        service = get_gmail_service(current_user)
        listing = service.users().messages().list(userId="me", maxResults=5).execute()
        snippets = []
        for message in listing.get("messages", []):
            metadata = service.users().messages().get(
                userId="me", id=message["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = metadata.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No subject")
            snippets.append(f"- {subject}: {metadata.get('snippet', '')}")
        return snippets

    # All sources load at the same time, and each one can fail on its own.
    (tasks, tasks_error), (events, events_error), (emails, emails_error), (
        projects,
        projects_error,
    ), (commands, commands_error) = await asyncio.gather(
        _load_source("tasks", get_todoist_tasks, current_user),
        _load_source("calendar", load_calendar),
        _load_source("gmail", load_emails),
        _load_source("projects", list_projects, user_id),
        _load_source("commands", list_commands, user_id),
    )

    def section(title: str, body: str, available: bool, limit: int, error: str | None = None) -> str:
        if not available:
            return f"{title}: {error or 'Unavailable right now'}"[:limit]
        return f"{title}:\n{body}"[:limit]

    parts = [
        f"User: {email}",
        "Use the data below when it is relevant. If something is not listed, say you do not have it.",
        section("Upcoming calendar (next 30 days)", _fmt_events(events or []), events is not None, 3000, events_error),
        section("Open tasks", _fmt_tasks(tasks or []), tasks is not None, 3000, tasks_error),
        section("Recent emails", "\n".join(emails or []) or "No recent emails", emails is not None, 2000, emails_error),
        section("Projects", _fmt_projects(projects or []), projects is not None, 4000, projects_error),
        section("Saved commands", _fmt_commands(commands or []), commands is not None, 2500, commands_error),
    ]
    return "\n\n".join(parts)


async def _safe_send(websocket: WebSocket, payload: Dict[str, Any]) -> bool:
    """Send JSON to the client. Returns False if the socket is already closed."""
    try:
        await websocket.send_json(payload)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


