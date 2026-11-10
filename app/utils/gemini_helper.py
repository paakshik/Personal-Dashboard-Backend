from typing import Optional, Dict, Any, List
import asyncio
import google.genai as genai
from google.genai import types
from fastapi import WebSocket
from app.config import logger, sentry_sdk, GEMINI_API_KEY
from app.db_store import save_chat_message as persist_chat_message
from app.utils.google_services_calender_helper import fetch_upcoming_events, get_google_calendar_service
from app.utils.google_services_gmail_helper import get_gmail_service, fetch_email_body
from app.api.todoist import get_todoist_tasks


def create_gemini_client():
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(api_version="v1beta"),
    )


def save_chat_message(role: str, text: str, user_id: str, attachment_id: Optional[str] = None) -> Dict[str, Any]:
    return persist_chat_message(role, text, user_id, attachment_id)


def should_enable_search(prompt: str) -> bool:
    terms = ("current", "today", "now", "latest", "recent", "news", "weather", "stock", "price", "market", "score", "results", "what is", "who is", "where is", "when did", "how to", "how much", "how many", "this year", "this month", "this week", "research", "study")
    lowered = prompt.lower()
    return "?" in prompt or any(term in lowered for term in terms)


async def gather_user_context(current_user: Dict[str, Any]) -> str:
    email = current_user.get("email", "unknown")
    user_id = current_user.get("id", "unknown")
    try:
        tasks = await asyncio.to_thread(get_todoist_tasks, current_user)
        cal_service = get_google_calendar_service(current_user)
        gmail_service = get_gmail_service(current_user)
        calendar_events = await asyncio.to_thread(fetch_upcoming_events, cal_service, 90)
        task_text = "\n".join(f"- {t.get('content', t)}" for t in tasks) if tasks else "No pending tasks"
        calendar_text = "\n".join(f"- {e.get('start', {}).get('dateTime', 'All Day')}: {e.get('summary')}" for e in calendar_events) if calendar_events else "No events"
        gmail_results = await asyncio.to_thread(lambda: gmail_service.users().messages().list(userId="me", maxResults=10).execute())
        messages = gmail_results.get("messages", [])
        snippets = []
        for message in messages:
            metadata = await asyncio.to_thread(lambda msg=message: gmail_service.users().messages().get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"]).execute())
            headers = metadata.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
            snippets.append(f"{subject}: {metadata.get('snippet', '')}")
        email_text = "\n".join(snippets)[:2000]
        return f"User {email}\nUpcoming calendar:\n{calendar_text[:3000]}\nTasks:\n{task_text[:3000]}\nRecent email subjects:\n{email_text}"
    except Exception as exc:
        logger.warning("Personal context failed for %s: %s", email, exc)
        sentry_sdk.capture_exception(exc)
        return f"User {email}; personal integrations are currently unavailable."


def describe_gemini_error(exc: Exception) -> str:
    """Return actionable, non-secret Gemini error guidance for the chat client."""
    text = str(exc).lower()
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (401, 403) or "api key" in text or "permission_denied" in text or "unauthenticated" in text:
        return "Gemini rejected the backend API key. Check GEMINI_API_KEY in the Render backend environment and confirm the key has Gemini API access."
    if code == 429 or "resource_exhausted" in text or "quota" in text:
        return "Gemini API quota or rate limit reached. Check the Gemini project quota and billing, then retry."
    if code == 404 or "not_found" in text:
        return "The configured Gemini model or API resource was not found. Check the model name and API access."
    if code and int(code) >= 500:
        return "Gemini is temporarily unavailable. Please retry in a moment."
    return "Gemini could not generate a response. Check the Render backend logs and GEMINI_API_KEY configuration."


async def process_ai_attachment(attachment_id: str, websocket: WebSocket):
    if not GEMINI_API_KEY:
        await websocket.send_json({"type": "error", "message": "Gemini is not configured on the backend. Add GEMINI_API_KEY to the Render backend environment and redeploy."})
        return None
    try:
        client = create_gemini_client()
        return client.files.get(name=attachment_id)
    except Exception as exc:
        logger.error("Gemini attachment retrieval failed (%s)", type(exc).__name__, exc_info=True)
        sentry_sdk.capture_exception(exc)
        await websocket.send_json({"type": "error", "message": describe_gemini_error(exc)})
        return None


async def stream_gemini_response(websocket: WebSocket, model: Any, message_parts: List[Any], config: Any) -> str:
    if not GEMINI_API_KEY:
        await websocket.send_json({"type": "error", "message": "Gemini is not configured on the backend. Add GEMINI_API_KEY to the Render backend environment and redeploy."})
        return ""
    full_response = ""
    try:
        client = create_gemini_client()
        stream = await client.aio.models.generate_content_stream(model=model, contents=message_parts, config=config)
        async for chunk in stream:
            if chunk.text:
                await websocket.send_json({"type": "chunk", "text": chunk.text})
                full_response += chunk.text
                await asyncio.sleep(0)
        return full_response
    except Exception as exc:
        error_message = describe_gemini_error(exc)
        logger.error("Gemini response streaming failed (%s): %s", type(exc).__name__, exc, exc_info=True)
        sentry_sdk.capture_exception(exc)
        await websocket.send_json({"type": "error", "message": error_message})
        return full_response
