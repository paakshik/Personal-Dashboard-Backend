from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from fastapi import HTTPException
from jose import jwt
from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, SCOPES, ACCESS_TOKEN_EXPIRE_MINUTES, SECRET_KEY, ALGORITHM, logger, sentry_sdk
from app.db_store import get_credential, save_credential


def get_google_flow(*, state: Optional[str] = None, code_verifier: Optional[str] = None, autogenerate_code_verifier: bool = True) -> Flow:
    return Flow.from_client_config({"web": {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [GOOGLE_REDIRECT_URI]}}, scopes=SCOPES, state=state, code_verifier=code_verifier, autogenerate_code_verifier=autogenerate_code_verifier)


def get_user_google_creds(user_id: str) -> Credentials:
    tokens = get_credential(user_id)
    if not tokens or not tokens.get("access_token"):
        raise HTTPException(status_code=401, detail="Google authentication required. Please connect your Google account.")
    creds = Credentials(token=tokens["access_token"], refresh_token=tokens.get("refresh_token"), token_uri=tokens.get("token_uri", "https://oauth2.googleapis.com/token"), client_id=tokens.get("client_id"), client_secret=tokens.get("client_secret"), scopes=tokens.get("scopes"))
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            save_credential(user_id, {"access_token": creds.token, "refresh_token": creds.refresh_token})
        except Exception as exc:
            logger.error("Google credential refresh failed for user %s", user_id)
            sentry_sdk.capture_exception(exc)
            raise HTTPException(status_code=401, detail="Google session expired for the user") from exc
    return creds


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    payload.update({"exp": datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
