from fastapi import Depends, HTTPException, Query, WebSocket, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, ExpiredSignatureError
from typing import Dict, Any, Optional

from app.config import (
    SECRET_KEY,
    ALGORITHM,
    TOKENS_FILE,
    USERS_FILE,
    logger,
    sentry_sdk
)
from app.utils.file_ops import read_json_file

# Only for HTTP routes (Drive, Calendar, etc.)
security = HTTPBearer()


def _verify_token_logic(token: str) -> Dict[str, Any]:
    """
    Core authentication logic that validates a JWT token and retrieves the user.

    This internal helper acts as the single source of truth for auth. It is agnostic
    to the transport layer (works for both HTTP Headers and WebSocket URLs).

    Args:
        token (str): The raw JWT token string to validate.

    Returns:
        Dict[str, Any]: A dictionary containing the authenticated user's details:
            {
                "id": str,
                "email": str,
                "name": str
            }

    Raises:
        HTTPException(401): If the token is invalid, expired, or the user
                           session is no longer active.
    """
    try:
        # 1. Decode Token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")

        if not user_id:
            logger.warning("Auth failed: JWT token missing 'sub' claim")
            sentry_sdk.capture_message("Auth failed: JWT token missing 'sub' claim",
                                       level="warning")
            raise HTTPException(status_code=401, detail="Invalid token payload")

        # 2. Check Session (Force Logout support)
        all_tokens = read_json_file(TOKENS_FILE)
        if str(user_id) not in all_tokens:
            logger.info(f"Auth failed: Session expired or revoked for user {user_id}")
            raise HTTPException(status_code=401,
                                detail="Session expired. Please log in again.")

        # 3. Get User Profile
        users = read_json_file(USERS_FILE)
        user = next((u for u in users if str(u.get("id")) == str(user_id)), None)

        if not user:
            # CRITICAL: This shouldn't happen if the token is valid.
            # It means we have a 'phantom' user. Alert the engineering team.
            error_msg = f"Critical Data Inconsistency: Valid token found for non-existent user_id {user_id}"
            logger.critical(error_msg)
            sentry_sdk.capture_message(error_msg, level="error")
            raise HTTPException(status_code=401, detail="User not found")

        return {
            "id": user_id,
            "email": user.get("email"),
            "name": user.get("name", "User")
        }

    except ExpiredSignatureError:
        logger.debug("Auth failed: Token has expired")
        raise HTTPException(status_code=401, detail="Token expired")

    except JWTError as e:
        logger.warning(f"Auth failed: Malformed or invalid token - {str(e)}")
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    except Exception as e:
        # Catch-all for unexpected filesystem or logic errors
        logger.error(f"Auth System Error: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail="Authentication system error")

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    return _verify_token_logic(credentials.credentials)


# --- 2. WebSocket Dependency (Use this for Chat) ---
async def get_current_user_ws(
    websocket: WebSocket,
    token: str = Query(..., description="Token from URL query param")
) -> Dict[str, Any]:
    try:
        return _verify_token_logic(token)
    except HTTPException:
        # WebSockets must fail by CLOSING the connection, not sending 401
        logger.warning("WebSocket Auth Failed: Closing connection")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise

