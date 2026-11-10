from typing import Optional, Dict, Any, List
import asyncio
import google.genai as genai
from fastapi import WebSocket
from app.config import logger, sentry_sdk, GEMINI_API_KEY
from app.db_store import save_chat_message as persist_chat_message
from app.utils.google_services_calender_helper import fetch_upcoming_events, get_google_calendar_service
from app.utils.google_services_gmail_helper import get_gmail_service, fetch_email_body
from app.api.todoist import get_todoist_tasks


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


async def process_ai_attachment(attachment_id: str, websocket: WebSocket):
    try:
        client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else genai.Client()
        return client.files.get(name=attachment_id)
    except Exception as exc:
        logger.error("Gemini attachment retrieval failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        await websocket.send_json({"type": "error", "message": "Could not retrieve uploaded attachment"})
        return None


async def stream_gemini_response(websocket: WebSocket, model: Any, message_parts: List[Any], config: Any) -> str:
    full_response = ""
    try:
        client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else genai.Client()
        stream = await client.aio.models.generate_content_stream(model=model, contents=message_parts, config=config)
        async for chunk in stream:
            if chunk.text:
                await websocket.send_json({"type": "chunk", "text": chunk.text})
                full_response += chunk.text
                await asyncio.sleep(0)
        return full_response
    except Exception as exc:
        logger.error("Gemini response streaming failed", exc_info=True)
        sentry_sdk.capture_exception(exc)
        await websocket.send_json({"type": "error", "message": "AI response generation failed"})
        return full_response
