import os
import shutil
import uuid
import google.genai as genai
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.config import DATA_DIR, logger, sentry_sdk
from app.dependencies import create_ws_ticket, get_current_user, WS_TICKET_EXPIRY_SECONDS
from app.db_store import list_chat_messages, clear_chat_messages
from app.utils.gemini_helper import save_chat_message
from typing import Dict, Any, List

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
