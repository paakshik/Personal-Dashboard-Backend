import threading
import time
import uuid
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Query, WebSocket, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError
from app.config import SECRET_KEY, ALGORITHM, logger, sentry_sdk
from app.db_store import find_user, is_session_active

security = HTTPBearer()

# WebSocket short-lived single-use ticket store (in-memory, thread-safe)
# ticket_id -> {"user_id": str, "email": str, "used": bool, "expires_at": float}
_WS_TICKETS: Dict[str, Dict[str, Any]] = {}
_WS_TICKETS_LOCK = threading.Lock()

WS_TICKET_EXPIRY_SECONDS = 5 * 60  # 5 minutes


def create_ws_ticket(user_id: str, email: str) -> str:
    """Generate a short-lived single-use WebSocket ticket for an authenticated owner."""
    ticket_id = str(uuid.uuid4())
    expires_at = time.time() + WS_TICKET_EXPIRY_SECONDS
    with _WS_TICKETS_LOCK:
        _WS_TICKETS[ticket_id] = {
            "user_id": user_id,
            "email": email,
            "used": False,
            "expires_at": expires_at,
        }
    return ticket_id


def consume_ws_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    """Validate and consume (invalidate) a WebSocket ticket. Returns ticket data or None."""
    with _WS_TICKETS_LOCK:
        ticket = _WS_TICKETS.get(ticket_id)
        if not ticket:
            return None
        if ticket.get("used"):
            return None
        if time.time() > ticket.get("expires_at", 0):
            _WS_TICKETS.pop(ticket_id, None)
            return None
        ticket["used"] = True
        return ticket


def cleanup_expired_tickets() -> None:
    """Remove expired tickets from the store."""
    now = time.time()
    with _WS_TICKETS_LOCK:
        expired = [tid for tid, t in _WS_TICKETS.items() if t.get("expires_at", 0) < now]
        for tid in expired:
            _WS_TICKETS.pop(tid, None)


def _verify_token_logic(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        if not is_session_active(user_id):
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        user = find_user(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {"id": user_id, "email": user.get("email"), "name": user.get("name", "User")}
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except JWTError as exc:
        logger.warning("Invalid JWT: %s", exc)
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=401, detail="Invalid authentication token")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    return _verify_token_logic(credentials.credentials)


async def get_current_user_ws(websocket: WebSocket, token: str = Query(...)) -> Dict[str, Any]:
    try:
        return _verify_token_logic(token)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise


async def get_current_user_ws_ticket(websocket: WebSocket, ticket: str = Query(...)) -> Dict[str, Any]:
    """Authenticate a WebSocket connection using a short-lived single-use ticket."""
    ticket_data = consume_ws_ticket(ticket)
    if not ticket_data:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=403, detail="Invalid or expired WebSocket ticket")
    user_id = ticket_data["user_id"]
    if not is_session_active(user_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    user = find_user(user_id)
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(status_code=401, detail="User not found")
    return {"id": user_id, "email": user.get("email"), "name": user.get("name", "User")}
