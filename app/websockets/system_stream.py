import asyncio
from typing import Any, Dict
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from app.config import logger
from app.dependencies import get_current_user_ws
from app.services.system_data_store import system_data_store

router = APIRouter(tags=["System Monitoring"])


@router.websocket("/dashboard/system/vitals/stream")
async def stream_system_vitals(
    websocket: WebSocket,
    current_user: Dict[str, Any] = Depends(get_current_user_ws),
) -> None:
    """Stream backend host vitals to an authenticated dashboard client."""
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(await system_data_store.get_vitals())
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        logger.info("System-vitals WebSocket disconnected for user %s", current_user["id"])
