import os
import shutil
import uuid
import google.genai as genai
from fastapi import APIRouter, UploadFile, File, \
    Depends, HTTPException
from app.config import (DATA_DIR,
                        CHAT_HISTORY_FILE,logger,sentry_sdk)
from app.dependencies import get_current_user
from app.utils.file_ops import read_json_file , write_json_file
from typing import Dict, Any,   List
from app.utils.gemini_helper import save_chat_message


router = APIRouter(prefix="/dashboard/gemini", tags=["Gemini AI"])


# api endpoint for uploading the file on gemini also the jwt is verified.
@router.post("/upload")
def upload_to_gemini(
        file: UploadFile = File(...),
        current_user: dict = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Upload a file to Google Gemini AI for processing and storage.

    This endpoint accepts a file upload, saves it temporarily, uploads it to Google Gemini's
    file storage system, and records the upload in the user's chat history. The Gemini file ID
    is stored for future reference when using the file in AI conversations.

    Process:
    1. Validate Gemini API key is configured
    2. Save uploaded file to temporary storage with UUID for security
    3. Upload file to Gemini using Google's Generative AI SDK
    4. Clean up temporary file
    5. Record upload event in user's chat history for tracking
    6. Return file metadata including Gemini file ID

    Args:
        file (UploadFile): The file to upload, provided as multipart/form-data
        current_user (dict): Authenticated user information from JWT token,
            containing at least 'id' and 'email' keys

    Returns:
        Dict[str, str]: Dictionary containing:
            - status: "success" on successful upload
            - file_id: The Gemini-assigned file identifier for API references
            - filename: Original filename
            - uploaded_by: Email of the user who uploaded the file
            - user_id: User's unique identifier

    Raises:
        HTTPException: 500 - If Gemini API key is not configured
        HTTPException: 500 - If any error occurs during file processing or upload
        HTTPException: 401 - If user is not authenticated (handled by get_current_user dependency)
    """
    temp_path = None
    try:
        temp_path = DATA_DIR / f"temp_{uuid.uuid4()}_{file.filename}"
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        gemini_file = genai.upload_file(path=temp_path, display_name=file.filename)
        os.remove(temp_path)

        save_chat_message(
            role="system",  # Or "user" or "upload"
            text=f"Uploaded file: {file.filename} (ID: {gemini_file.name})",
            user_id=current_user["id"],
            attachment_id=gemini_file.name  # Store the Gemini file ID
        )

        return {
            "status": "success",
            "file_id": gemini_file.name,
            "filename": file.filename,
            "uploaded_by": current_user["email"],
            "user_id": current_user["id"]
        }

    except Exception as e:
        logger.error(
            f"Upload failed for user {current_user.get('email', 'unknown')}: {e}",
            exc_info=True)
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug("Cleaned up temp file after error")
            except Exception as cleanup_error:
                logger.warning(
                    f"Failed to cleanup temp file {temp_path}: {cleanup_error}")
                sentry_sdk.capture_message(f"Failed to cleanup temp file {temp_path}: {cleanup_error}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
def get_user_history(
        current_user: dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Get chat history ONLY for current user.

    Args:
        current_user: Authenticated user dict containing 'id'

    Returns:
        List of chat message dictionaries for current user
    """
    try:
        user_id = current_user["id"]
        all_history = read_json_file(CHAT_HISTORY_FILE)

        # Handle the new dictionary format: {user_id: [messages]}
        if isinstance(all_history, dict):
            return all_history.get(user_id, [])

        return []

    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="Failed to retrieve chat history")


@router.delete("/history")
def clear_user_history(
        current_user: dict = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Clear chat history ONLY for current user.

    Removes all chat messages belonging to the authenticated user while
    preserving other users' chat histories.

    Args:
        current_user: Authenticated user dict containing 'id' and 'email'

    Returns:
        Dictionary with status and confirmation message

    Raises:
        HTTPException: 500 - If an error occurs during processing
    """
    try:
        user_id = current_user["id"]
        all_history = read_json_file(CHAT_HISTORY_FILE)

        # 1. Handle the new dictionary format: {user_id: [messages]}
        if isinstance(all_history, dict):
            if user_id in all_history:
                messages_removed = len(all_history[user_id])

                # Clear the user's specific history array
                all_history[user_id] = []
                write_json_file(CHAT_HISTORY_FILE, all_history)

                logger.debug(
                    f"Cleared {messages_removed} messages for user {current_user['email']}")
                return {
                    "status": "cleared",
                    "message": f"Cleared {messages_removed} messages for user {current_user['email']}"
                }

            return {
                "status": "cleared",
                "message": f"No history found for user {current_user['email']}"
            }

        # 2. Fallback logic for legacy list format (just in case)
        if isinstance(all_history, list):
            other_users_history = [
                msg for msg in all_history
                if msg.get("user_id") != user_id
            ]
            messages_removed = len(all_history) - len(other_users_history)

            write_json_file(CHAT_HISTORY_FILE, other_users_history)
            logger.debug(
                f"Updated chat history file, remaining messages: {len(other_users_history)}")

            return {
                "status": "cleared",
                "message": f"Cleared {messages_removed} messages for user {current_user['email']}"
            }

        # 3. Handle corrupted/unknown format
        logger.warning("Chat history file is neither a dict nor a list")
        sentry_sdk.capture_message("Chat history file is an invalid format",
                                   level="warning")
        return {
            "status": "error",
            "message": "Invalid chat history format"
        }

    except Exception as e:
        logger.error(f"Failed to clear history: {e}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="Failed to clear chat history")
