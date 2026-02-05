
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from fastapi import HTTPException
from app.config import (
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI, SCOPES,
    ACCESS_TOKEN_EXPIRE_MINUTES,SECRET_KEY, TOKENS_FILE,ALGORITHM,logger,sentry_sdk
)
from jose import jwt
from datetime import datetime, timedelta,timezone
from typing import Optional, Dict, Any


def get_google_flow() -> Flow:
    """
    Initialize and return a Google OAuth 2.0 flow instance.

    This flow object is used to:
    1. Generate Google login URLs
    2. Exchange authorization codes for access tokens
    3. Manage the OAuth 2.0 authorization process

    Returns:
        google_auth_oauthlib.flow.Flow: Configured OAuth flow instance

    Raises:
        ValueError: If required environment variables are missing
    """
    return Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [GOOGLE_REDIRECT_URI],
            }
        },
        scopes=SCOPES,
    )


def get_user_google_creds(user_id: str) -> Credentials:
    """
    Retrieve and automatically refresh Google credentials for a user.

    Flow:
    1. Get user's stored tokens from tokens.json
    2. Create Google Credentials object
    3. Automatically refresh if access token expired
    4. Save refreshed token back to file

    Args:
        user_id: The user's unique ID (UUID)

    Returns:
        Credentials: Google API credentials ready for API calls

    Raises:
        HTTPException: 401 if no Google account linked or token refresh fails
    """

    from app.utils.file_ops import read_json_file, write_json_file
    all_tokens = read_json_file(TOKENS_FILE)
    user_tokens = all_tokens.get(user_id)

    if not user_tokens or not user_tokens.get("access_token"):
        logger.error(f"No Google credentials for user {user_id}")

        raise HTTPException(
            status_code=401,
            detail="Google authentication required. Please connect your Google account."
        )

    creds = Credentials(
        token=user_tokens["access_token"],
        refresh_token=user_tokens.get("refresh_token"),
        token_uri=user_tokens.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=user_tokens.get("client_id"),
        client_secret=user_tokens.get("client_secret"),
        scopes=user_tokens.get("scopes")
    )


    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleRequest())
            # Update storage with new access token
            user_tokens["access_token"] = creds.token
            all_tokens[user_id] = user_tokens
            write_json_file(TOKENS_FILE, all_tokens)
        except Exception:
            logger.error(f"Credentials expired for user {user_id} but no refresh token available")
            sentry_sdk.capture_exception(extra={
                "user_id": user_id,
                "has_refresh_token": bool(creds.refresh_token)
            })
            raise HTTPException(status_code=401, detail="Google session expired for "
                                                        "the user")
    return creds

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a signed JWT access token with expiration.

    This token is used for authenticating users to your app (not Google).

    Args:
        data: Dictionary of claims to include in the token (e.g., {"sub": "user_id"})
        expires_delta: Custom expiration time. If None, uses ACCESS_TOKEN_EXPIRE_MINUTES

    Returns:
        str: JWT token string that can be sent to clients

    """
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta
        else timedelta(ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
