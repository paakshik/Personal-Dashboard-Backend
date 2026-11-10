import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import WebSocket, WebSocketDisconnect, Depends, APIRouter
from google.genai import types
from app.config import logger, sentry_sdk, GEMINI_API_KEY
from app.dependencies import get_current_user_ws_ticket
from app.utils.gemini_helper import should_enable_search, save_chat_message, gather_user_context, process_ai_attachment
from app.utils.ai_tools import run_agent_turn

router = APIRouter(prefix="/dashboard/gemini", tags=["Gemini AI"])


@router.websocket("/stream")
async def websocket_ai_stream(websocket: WebSocket, current_user: Dict[str, Any] = Depends(get_current_user_ws_ticket)) -> Any:
    await websocket.accept()
    user_id = current_user["id"]
    try:
        while True:
            data = await websocket.receive_json()
            prompt = str(data.get("prompt", "")).strip()
            attachment_id = data.get("attachment_id")
            conversation_id = data.get("conversation_id")
            if not conversation_id:
                conversation_id = str(uuid.uuid4())
            if not prompt and not attachment_id:
                await websocket.send_json({"type": "error", "message": "A prompt or attachment is required"})
                continue
            if not GEMINI_API_KEY:
                await websocket.send_json({"type": "error", "message": "Gemini is not configured. Set GEMINI_API_KEY in the Render backend environment and redeploy."})
                continue
            context = await gather_user_context(current_user)
            instruction = f"You are Nexus AI, the user's dashboard command center. Current time: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. User: {current_user.get('name', 'User')}.\n\n{context}"
            parts = [prompt or "Analyze the attached file."]
            if attachment_id:
                attachment = await process_ai_attachment(attachment_id, websocket)
                if attachment is None:
                    continue
                parts.append(attachment)
            search_tools = [types.Tool(google_search=types.GoogleSearch())] if should_enable_search(prompt) else []
            config = types.GenerateContentConfig(system_instruction=instruction, tools=search_tools)
            await websocket.send_json({"type": "start"})
            save_chat_message("user", prompt or "Analyze the attached file.", user_id, attachment_id, conversation_id)
            response = await run_agent_turn(websocket, "gemini-2.5-flash", parts, config, current_user)
            if response:
                save_chat_message("assistant", response, user_id, conversation_id=conversation_id)
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        logger.info("AI WebSocket disconnected for user %s", user_id)
    except Exception as exc:
        logger.error("AI WebSocket failed (%s): %s", type(exc).__name__, exc, exc_info=True)
        sentry_sdk.capture_exception(exc)
        try:
            await websocket.send_json({"type": "error", "message": "AI command center failed. Check backend logs for the underlying tool or Gemini error."})
        except Exception:
            pass
