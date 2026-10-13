import uuid

from app.utils.file_ops import read_json_file,write_json_file
from typing import Optional
import asyncio
import google.genai as genai
from fastapi import  WebSocket
from app.config import logger,sentry_sdk,CHAT_HISTORY_FILE
from datetime import datetime, timezone
from app.utils.google_services_calender_helper import fetch_upcoming_events, get_google_calendar_service
from app.utils.google_services_gmail_helper import get_gmail_service,fetch_email_body
from app.api.todoist import get_todoist_tasks
from typing import Dict, Any,List

def save_chat_message(
        role: str,
        text: str,
        user_id: str,
        attachment_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Save chat message with user association.

    Structure: {user_id: [messages]} where each message has:
        - id: UUID
        - role: "user" or "assistant" or "system"
        - text: Message content
        - timestamp: ISO format UTC time
        - attachment_id: Optional (only for user messages)

    Args:
        role: "user", "assistant", or "system"
        text: Message content
        user_id: Owner of the message (REQUIRED for multi-user apps)
        attachment_id: Optional file attachment ID (only for user messages)

    Returns:
        Dict containing the saved message with metadata
    """
    history = read_json_file(CHAT_HISTORY_FILE)

    if not isinstance(history, dict):
        if isinstance(history, list):
            logger.warning(
                "Migrating chat history from old list format to new dict format")

            sentry_sdk.capture_message("Migrating chat history from old list format "
                                       "to new dict format",level="warning")
            new_history = {}
            for msg in history:
                uid = msg.get("user_id", "unknown")
                if uid not in new_history:
                    new_history[uid] = []
                msg_copy = msg.copy()
                if "user_id" in msg_copy:
                    del msg_copy["user_id"]
                new_history[uid].append(msg_copy)
            history = new_history
            logger.info(f"Migrated {len(history)} users' chat history to new format")
        else:
            logger.warning("Chat history corrupted or invalid, starting fresh")
            sentry_sdk.capture_message("Chat history corrupted or invalid, starting "
                                       "fresh",level="warning")
            history = {}

    if user_id not in history:
        logger.debug(f"Creating new chat history for user {user_id}")
        history[user_id] = []

    # Create message with metadata
    new_message = {
        "id": str(uuid.uuid4()),
        "role": role,
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Add attachment info if provided
    if attachment_id and role == "user":
        new_message["attachment_id"] = attachment_id
        logger.debug(f"Added attachment {attachment_id} to user message")

    # Add to user's message history
    history[user_id].append(new_message)

    # Keep only last 100 messages per user (not total)
    if len(history[user_id]) > 100:
        removed_count = len(history[user_id]) - 100
        history[user_id] = history[user_id][-100:]
        logger.debug(f"Trimmed {removed_count} old messages for user {user_id}")

    # Write back to file
    success = write_json_file(CHAT_HISTORY_FILE, history)

    if success:
        logger.debug(
            f"Saved {role} message for user {user_id}, total: {len(history[user_id])}")
    else:
        logger.error(f"Failed to save chat message for user {user_id}")
        sentry_sdk.capture_message(f"Failed to save chat message for user {user_id}",
                                   level="error")
    return new_message

def should_enable_search(prompt: str) -> bool:
    """Determine if query needs internet search."""
    search_keywords = [
        # Time-sensitive
        "current", "today", "now", "latest", "recent", "update",
        "breaking", "live", "right now",

        # Information types
        "news", "weather", "forecast", "temperature",
        "stock", "price", "market", "crypto",
        "score", "results", "game", "match",

        # Question types
        "what is", "who is", "where is", "when did",
        "how to", "how much", "how many",

        # Current events
        "2024", "this year", "this month", "this week",

        # Factual
        "fact", "statistic", "data", "research", "study"
    ]

    prompt_lower = prompt.lower()

    # Also check for question marks
    has_question = "?" in prompt

    return has_question or any(keyword in prompt_lower for keyword in search_keywords)


async def gather_user_context(current_user: Dict[str, Any]) -> str:
    """
    Asynchronously gathers personal context from Google and Todoist services.

    Uses asyncio.to_thread to offload synchronous, blocking network calls
    (Google API execution) to a separate thread pool, preventing the
    WebSocket event loop from freezing.

    Args:
        current_user (Dict[str, Any]): The authenticated user's profile data.

    Returns:
        str: A formatted string containing the user's latest tasks, events, and emails.
    """
    user_email: str = current_user.get("email", "unknown")
    user_id: str = current_user.get("id", "unknown")

    # Add breadcrumb for debugging if a subsequent step fails
    sentry_sdk.add_breadcrumb(
        category="ai_context",
        message=f"Gathering context for {user_email}",
        level="info"
    )

    try:
        tasks = await asyncio.to_thread(get_todoist_tasks,current_user)
        cal_service = get_google_calendar_service(current_user)
        gmail_service = get_gmail_service(current_user)
        if tasks and isinstance(tasks, list):
            task_list = [f"- {t.get('content', str(t))}" if isinstance(t,
                                                                       dict) else f"- {str(t)}"
                         for t in tasks]
            formatted_tasks = "\n".join(task_list)
        else:
            formatted_tasks = "No pending tasks"

        calendar_events = await asyncio.to_thread(fetch_upcoming_events, cal_service,
                                    90)
        formatted_calendar = "\n".join(
            [f"- {e.get('start', {}).get('dateTime', 'All Day')}: {e.get('summary')}"
             for e in calendar_events]) if calendar_events else "No events."
        email_context  =[]
        gmail_results = await asyncio.to_thread(
            lambda: gmail_service.users().messages().list(userId='me',
                                                          maxResults=50).execute()
        )
        emails = gmail_results.get('messages', [])
        for message in emails:
            body = await fetch_email_body(gmail_service, message['id'])

            # Get metadata for the header
            meta = await asyncio.to_thread(lambda msg=message: gmail_service.users(

            ).messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['Subject', 'From', 'Date']).execute())

            headers = meta.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'),
                           'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'),
                          'Unknown')
            date = next((h['value'] for h in headers if h['name'] == 'Date'),
                        'Unknown Date')
            email_context.append(f"DATE: {date}\nFROM: {sender}\nSUBJECT: {subject}\nCONTENT: {body[:1000]}\n---")
        formatted_emails = "\n".join(email_context) if email_context else "No recent emails."

        logger.info(f"Context successfully gathered for User: {user_id}")

        return f"""User Context for {user_email}:📅 Calendar: {str(formatted_calendar)[:5000] if calendar_events else 'No upcoming events'}
✅ Tasks: {formatted_tasks[:5000] if tasks else 'No pending tasks'}📧 Emails: {formatted_emails[:5000] if emails else 'No recent emails'}
"""

    except Exception as e:
        logger.warning(f"Context gathering failed for {user_email}: {str(e)}")
        sentry_sdk.capture_exception(e)
        return "⚠️ Personal context temporarily unavailable due to a service connection error."

async def process_ai_attachment(
    attachment_id: str,
    websocket: WebSocket
) -> Optional[Any]:
    """
    Retrieves and prepares an uploaded file for the Gemini model from Google's File Manager.

    This helper provides real-time feedback to the user via the WebSocket while
    fetching the metadata for a previously uploaded file.

    Args:
        attachment_id (str): The unique resource name of the file in Gemini's system.
        websocket (WebSocket): The active connection to send status updates to.

    Returns:
        Optional[Any]: The Gemini File object if successful, None otherwise.
    """
    try:
        await websocket.send_text("[📎 Processing attachment...]")
        client = genai.Client()
        return client.files.get(name=attachment_id)
    except Exception as e:
        logger.error(f"Attachment retrieval failed: {e}")
        sentry_sdk.capture_exception(e)
        await websocket.send_text(f"[⚠️ Attachment error: {str(e)}]")
        return None


async def stream_gemini_response(
    websocket: WebSocket,
    model: Any,
    message_parts: List[Any],
    config:Any
) -> str:
    """
    Streams the response from Gemini back to the client and returns the full text for history.

    Handles edge cases such as empty chunks, safety filter triggers, and
    yielding control to the event loop to ensure WebSocket heartbeat stability.

    Args:
        websocket (WebSocket): The active connection to stream text to.
        model (Any): The initialized GenerativeModel instance.
        message_parts (List[Any]): Content parts (text, images, files) for the model.
        config(Any): Configuration object for the client.
    Returns:
        str: The concatenated string of the entire AI response.
    """
    full_response = ""
    client = genai.Client()
    try:
        response_stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=message_parts,
            config=config
        )

        async for chunk in response_stream:
            if chunk.text:
                await websocket.send_text(chunk.text)
                full_response += chunk.text
                await asyncio.sleep(0.01)

        return full_response
    except Exception as e:
        logger.error(f"Streaming failed: {e}")
        await websocket.send_text(f"\n[⚠️ Error generating response: {str(e)}]")
        return full_response