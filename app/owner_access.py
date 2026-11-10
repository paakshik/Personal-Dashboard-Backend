from fastapi import Depends, HTTPException, WebSocket, status
from app.config import DASHBOARD_OWNER_EMAIL
from app.dependencies import get_current_user, get_current_user_ws


def is_server_owner(user: dict) -> bool:
    owner_email = (DASHBOARD_OWNER_EMAIL or "").strip().casefold()
    verified_email = str(user.get("email") or "").strip().casefold()
    return bool(owner_email and verified_email and verified_email == owner_email)


def require_server_owner(user: dict = Depends(get_current_user)) -> dict:
    if not DASHBOARD_OWNER_EMAIL:
        raise HTTPException(status_code=503, detail="Server Information is not configured")
    if not is_server_owner(user):
        raise HTTPException(status_code=403, detail="Server Information is restricted to the owner")
    return user


async def require_server_owner_ws(websocket: WebSocket, user: dict = Depends(get_current_user_ws)) -> dict:
    if not DASHBOARD_OWNER_EMAIL or not is_server_owner(user):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=403, detail="Server Information is restricted to the owner")
    return user
