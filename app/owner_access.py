from fastapi import Depends, HTTPException, WebSocket, status
from app.config import DASHBOARD_OWNER_EMAIL
from app.dependencies import get_current_user, get_current_user_ws, get_current_user_ws_ticket


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
    """Deprecated: bearer-token WebSocket auth. Prefer require_server_owner_ws_ticket."""
    if not DASHBOARD_OWNER_EMAIL:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=503, detail="Server Information is not configured")
    if not is_server_owner(user):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=403, detail="Server Information is restricted to the owner")
    return user


async def require_server_owner_ws_ticket(websocket: WebSocket, user: dict = Depends(get_current_user_ws_ticket)) -> dict:
    """Owner-gated WebSocket auth using a short-lived single-use ticket (no bearer token in URL)."""
    if not DASHBOARD_OWNER_EMAIL:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=503, detail="Server Information is not configured")
    if not is_server_owner(user):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=403, detail="Server Information is restricted to the owner")
    return user
