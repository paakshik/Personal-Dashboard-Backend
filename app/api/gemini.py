import os
import shutil
import uuid
from datetime import datetime, timezone
import google.genai as genai
from google.genai import types
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.config import DATA_DIR, logger, sentry_sdk
from app.dependencies import create_ws_ticket, get_current_user, WS_TICKET_EXPIRY_SECONDS
from app.db_store import list_chat_messages, clear_chat_messages, list_conversations, get_conversation_messages, delete_conversation
from app.utils.gemini_helper import save_chat_message, gather_user_context, describe_gemini_error, create_gemini_client
from typing import Dict, Any, List, Optional

router = APIRouter(prefix="/dashboard/gemini", tags=["Gemini AI"])


@router.post("/upload")
def upload_to_gemini(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)) -> Dict[str, str]:
    temp_path = None
    try:
        safe_filename = os.path.basename(file.filename or "upload")
        temp_path = DATA_DIR / f"temp_{uuid.uuid4()}_{safe_filename}"
        with open(temp_path, "wb") as target:
            shutil.copyfileobj(file.file, target)
        gemini_file = genai.upload_file(path=temp_path, display_name=safe_filename)
        save_chat_message("system", f"Uploaded file: {safe_filename} (ID: {gemini_file.name})", current_user["id"], gemini_file.name)
        return {"status": "success", "file_id": gemini_file.name, "filename": safe_filename, "uploaded_by": current_user["email"], "user_id": current_user["id"]}
    except Exception as exc:
        logger.error("Gemini upload failed", exc_info=True)
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=500, detail="File upload failed") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/history")
def get_user_history(current_user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    return list_chat_messages(current_user["id"])


@router.delete("/history")
def clear_user_history(current_user: dict = Depends(get_current_user)) -> Dict[str, str]:
    count = clear_chat_messages(current_user["id"])
    return {"status": "cleared", "message": f"Cleared {count} messages for user {current_user['email']}"}


@router.get("/conversations")
def list_user_conversations(current_user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """List the authenticated user's AI conversations (id, title, message count, last timestamp)."""
    return list_conversations(current_user["id"])


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Return all messages of one conversation, chronological order, user-scoped."""
    return get_conversation_messages(current_user["id"], conversation_id)


@router.post("/conversations")
def create_conversation(current_user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """Start a new conversation for the authenticated user. Returns the conversation id."""
    conversation_id = str(uuid.uuid4())
    persist_chat_message("system", "Conversation started", current_user["id"], conversation_id=conversation_id)
    return {"conversation_id": conversation_id, "user_id": current_user["id"]}


@router.delete("/conversations/{conversation_id}")
def delete_user_conversation(conversation_id: str, current_user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """Delete one conversation belonging to the authenticated user."""
    count = delete_conversation(current_user["id"], conversation_id)
    return {"status": "deleted", "message": f"Deleted {count} messages for conversation {conversation_id}"}


@router.post("/ws-ticket")
def get_gemini_ws_ticket(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Issue a short-lived single-use WebSocket ticket for the Gemini AI stream.

    The ticket is bound to the authenticated user and expires after 5 minutes.
    It is consumed (invalidated) on the first successful WebSocket connection.
    No bearer token appears in the WebSocket URL.
    """
    ticket_id = create_ws_ticket(current_user["id"], current_user.get("email", ""))
    return {
        "ticket": ticket_id,
        "expires_in_seconds": WS_TICKET_EXPIRY_SECONDS,
        "single_use": True,
    }


@router.post("/briefing")
async def generate_briefing(current_user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """
    Generate a one-shot AI daily briefing for the authenticated user's Home page.

    Aggregates the user's real data (calendar, tasks, emails, projects, commands)
    via gather_user_context (each optional integration is skipped if unavailable),
    builds a briefing prompt, and calls Gemini non-streaming. Returns { briefing, timestamp }.
    """
    try:
        client = create_gemini_client()
    except RuntimeError as exc:
        logger.error("Gemini not configured: %s", exc)
        raise HTTPException(status_code=503, detail="Gemini is not configured on the backend. Set GEMINI_API_KEY and redeploy.") from exc

    try:
        context = await gather_user_context(current_user)
    except Exception as exc:
        # gather_user_context already skips failing optional sources; a total failure
        # here is unexpected but must not crash the Home page.
        logger.error("Failed to gather user context for briefing: %s", exc, exc_info=True)
        sentry_sdk.capture_exception(exc)
        context = "User: " + current_user.get("email", "unknown") + "\n\nNo contextual data is available right now."

    instruction = (
        "You are Nexus AI, the user's dashboard command center. "
        f"Current time: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. "
        f"User: {current_user.get('name', 'User')}.\n\n"
        "Write a short, friendly daily briefing (2-4 sentences) based on the user's context below. "
        "Include a gentle prioritization suggestion. Keep it encouraging and concise. "
        "If something is not listed, say you do not have it.\n\n"
        f"{context}"
    )

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[instruction],
        )
    except Exception as exc:
        error_message = describe_gemini_error(exc)
        logger.error("Gemini briefing generation failed (%s): %s", type(exc).__name__, exc, exc_info=True)
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=502, detail=error_message) from exc

    briefing = (response.text or "").strip() or "No briefing was returned."
    return {
        "briefing": briefing,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
