from google import genai
from google.genai import types
from fastapi import  WebSocket, WebSocketDisconnect,Depends,APIRouter
from app.config import (logger,sentry_sdk)
from app.dependencies import get_current_user_ws
from datetime import datetime, timezone
from typing import Dict, Any
from app.utils.gemini_helper import (should_enable_search,save_chat_message,
                                     gather_user_context,process_ai_attachment,stream_gemini_response)

router = APIRouter(prefix="/dashboard/gemini", tags=["Gemini AI"])

@router.websocket("/stream")
async def websocket_ai_stream(
    websocket: WebSocket,
    current_user: Dict[str, Any] = Depends(get_current_user_ws)
) -> Any:
    """
    Maintains a persistent bidirectional AI chat session via WebSockets.

    This orchestrator handles the real-time loop: receiving prompts, gathering
    user-specific context (Gmail/Calendar), invoking the Gemini LLM with
    streaming, and persisting the conversation to the database.

    Args:
        websocket (WebSocket): The active connection instance.
        current_user (Dict[str, Any]): The authenticated user injected via WS-compatible dependency.

    Returns:
        None: Continues until client disconnect or critical error.
    """
    await websocket.accept()
    user_id = current_user.get("id")
    user_email = current_user.get("email", "unknown")

    try:
        while True:
            # 1. RECEIVE USER INPUT
            data = await websocket.receive_json()
            user_prompt = data.get("prompt", "").strip()
            attachment_id = data.get("attachment_id")

            if not user_prompt: continue

            # 2. PREPARE CONTEXT & SYSTEM PROMPT
            context = await gather_user_context(current_user)
            system_instruction = f"""
            You are Nexus AI Assistant.
            Current Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
            User: {current_user.get('name', 'User')}
            PERSONAL CONTEXT: {context}
            """

            # 3. HANDLE ATTACHMENTS & TOOLS
            message_parts = [user_prompt]
            if attachment_id:
                file = await process_ai_attachment(attachment_id, websocket)
                if file: message_parts.append(file)
            tools = [types.Tool(google_search=types.GoogleSearch())]\
                if should_enable_search(user_prompt) else []
            if tools:
                await websocket.send_text("[🔍 Searching...]")

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=tools
            )
            full_ai_text = await stream_gemini_response(websocket,
                                                        "gemini-2.5-flash",
                                                        message_parts,config)

            save_chat_message("user", user_prompt, user_id, attachment_id)
            save_chat_message("assistant", full_ai_text, user_id)
            await websocket.send_text("[✓]")

    except WebSocketDisconnect:
        logger.info(f"WebSocket closed: {user_email}")
    except Exception as e:
        logger.error(f"Critical WebSocket failure: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)