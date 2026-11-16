import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from fastapi import WebSocket, WebSocketDisconnect, Depends, APIRouter
from app.config import logger, sentry_sdk, NVIDIA_API_KEY
from app.dependencies import get_current_user_ws_ticket
from app.utils.ai_context import persist_conversation_message, gather_user_context
from app.utils.nvidia_agent import run_nvidia_turn

router = APIRouter(prefix="/dashboard/gemini", tags=["AI"])


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
            if not NVIDIA_API_KEY:
                await websocket.send_json({"type": "error", "message": "Set NVIDIA_API_KEY on the backend and restart to use Nemotron."})
                continue
            if attachment_id:
                await websocket.send_json({"type": "error", "message": "Nemotron chat currently supports text only. Remove the attachment and send again."})
                continue
            context = await gather_user_context(current_user)
            instruction = f"You are Nexus AI, the user's dashboard command center. Current time: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}. User: {current_user.get('name', 'User')}.\n\n{context}"
            await websocket.send_json({"type": "start", "conversation_id": conversation_id})
            user_saved = await asyncio.to_thread(
                persist_conversation_message,
                "user",
                prompt or "Analyze the attached file.",
                user_id,
                attachment_id,
                conversation_id,
            )
            if not user_saved:
                await websocket.send_json({
                    "type": "error",
                    "message": "Your message could not be saved. No AI response was generated; please retry.",
                    "conversation_id": conversation_id,
                })
                continue

            response = await run_nvidia_turn(websocket, prompt, instruction, current_user)
            if response:
                assistant_saved = await asyncio.to_thread(
                    persist_conversation_message,
                    "assistant",
                    response,
                    user_id,
                    None,
                    conversation_id,
                )
                if not assistant_saved:
                    await websocket.send_json({
                        "type": "persistence_error",
                        "message": "The AI reply was generated but could not be saved to conversation history.",
                        "conversation_id": conversation_id,
                    })
            await websocket.send_json({"type": "done", "conversation_id": conversation_id})
    except WebSocketDisconnect:
        logger.info("AI WebSocket disconnected for user %s", user_id)
    except Exception as exc:
        logger.error("AI WebSocket failed (%s): %s", type(exc).__name__, exc, exc_info=True)
        sentry_sdk.capture_exception(exc)
        try:
            await websocket.send_json({"type": "error", "message": "AI command center failed. Check backend logs for the underlying tool or provider error."})
        except Exception:
            pass
