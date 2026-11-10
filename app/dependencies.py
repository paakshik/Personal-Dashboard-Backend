from typing import Any, Dict, Optional
from fastapi import Depends, HTTPException, Query, WebSocket, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError
from app.config import SECRET_KEY, ALGORITHM, logger, sentry_sdk
from app.db_store import find_user, is_session_active

security = HTTPBearer()


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
