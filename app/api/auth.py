import uuid
from jose import jwt
import oauthlib.oauth2
from datetime import datetime, timedelta ,timezone
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from googleapiclient.discovery import build
from typing import Dict, Any , Union  ,List
from app.config import (
    GOOGLE_CLIENT_ID, GOOGLE_REDIRECT_URI, USERS_FILE, TOKENS_FILE,
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, FRONTEND_URL,logger,sentry_sdk
)
from app.utils.file_ops import read_json_file, write_json_file
from app.services.google_auth import get_google_flow
from app.dependencies import get_current_user
# Router for all authentication endpoints
router = APIRouter(prefix="/dashboard/auth/google", tags=["Authentication"])

# it  initiates the Google login process (asks for permission)
@router.get("/login")
def login_google() -> Dict[str, str]:
    """
    Initiate Google OAuth2 login flow.

    Returns:
        Dict[str, str]: Dictionary containing the authorization URL


    Raises:
        HTTPException: If there's an error creating the authorization URL
    """
    try:
        flow = get_google_flow()
        flow.redirect_uri = GOOGLE_REDIRECT_URI
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"
        )
        return {"auth_url": auth_url}
    except Exception as e:
        logger.error(str(e))
        sentry_sdk.capture_exception(e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback", response_model=None)
def callback_google(request: Request) -> Union[RedirectResponse, JSONResponse]:
    """
    Handle Google OAuth2 callback after user authorizes the app.

    This endpoint:
    1. Receives authorization code from Google
    2. Exchanges code for access/refresh tokens
    3. Gets user info from Google API
    4. Creates or updates user in local database
    5. Stores Google tokens for API access
    6. Generates JWT for frontend authentication
    7. Redirects back to frontend with JWT

    Args:
        request: FastAPI Request object containing the authorization code in query params

    Returns:
        Union[RedirectResponse, JSONResponse]:
            - RedirectResponse: Redirects to frontend with JWT token on success
            - JSONResponse: Returns error details if authentication fails

    Raises:
        HTTPException: 400 if authorization code is missing
        HTTPException: 500 if any step in the OAuth flow fails
    """
    code = request.query_params.get("code")
    if not code:
        logger.error("Google OAuth callback received without authorization code")
        error = RuntimeError("Google OAuth callback received without authorization code")
        sentry_sdk.capture_exception(error)
        raise HTTPException(status_code=400, detail="Missing authorization code")
    try:
        logger.info("Processing Google OAuth callback")
        flow = get_google_flow()
        flow.redirect_uri = GOOGLE_REDIRECT_URI

        logger.debug(f"Using redirect URI: {GOOGLE_REDIRECT_URI}")

        # Custom client to allow scope changes during callback
        class ScopeTolerantClient(oauthlib.oauth2.WebApplicationClient):
            def __init__(self, client_id, **kwargs):
                super().__init__(client_id, **kwargs)
                self.allowed_scope_change = True

        flow.oauth2session._client = ScopeTolerantClient(client_id=GOOGLE_CLIENT_ID)

        # Exchange authorization code for tokens
        logger.debug("Exchanging authorization code for tokens")
        flow.fetch_token(authorization_response=str(request.url))
        creds = flow.credentials

        # Get User Info from Google
        logger.debug("Fetching user info from Google API")
        service = build("oauth2", "v2", credentials=creds)
        user_info = service.userinfo().get().execute()
        google_id = user_info["id"]
        email = user_info["email"]
        logger.info(f"Google user authenticated: {email} (ID: {google_id})")

        # Find or Create User in database
        users:List[Dict[str, Any]] = read_json_file(USERS_FILE)
        user = next((u for u in users if u.get("google_id") == google_id), None)

        if not user:
            # Create new user
            user_id = str(uuid.uuid4())
            user = {
                "id": user_id,
                "google_id": google_id,
                "email": email,
                "name": user_info.get("name", "User"),
                "picture": user_info.get("picture", ""),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            users.append(user)
            write_json_file(USERS_FILE, users)
            logger.info(f"Created new user: {email} with ID: {user_id}")
        else:
            # Existing user
            # understand why this gives error
            user_id = user["id"]
            logger.info(f"Existing user logged in: {email}.")

        # Store Google tokens for API access
        all_tokens = read_json_file(TOKENS_FILE)
        existing_refresh = all_tokens.get(user_id, {}).get("refresh_token")

        all_tokens[user_id] = {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token if creds.refresh_token else existing_refresh,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": creds.scopes
        }
        write_json_file(TOKENS_FILE, all_tokens)
        logger.debug(f"Stored Google tokens for user: {user_id}")

        # Generate JWT for Frontend authentication
        expiration = datetime.now(timezone.utc) + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        app_token = jwt.encode(
            {
                "sub": user_id,
                "email": email,
                "exp": expiration
            },
            SECRET_KEY,
            algorithm=ALGORITHM
        )
        logger.info(f"Generated JWT token for user {email}, expires at {expiration}")

        # Redirect back to frontend with JWT
        redirect_url = f"{FRONTEND_URL}?token={app_token}"
        logger.debug(f"Redirecting to frontend: {redirect_url}")

        return RedirectResponse(
            url=redirect_url,
            status_code=302
        )

    except Exception as e:
        logger.error(f"Google OAuth callback failed: {e}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Authentication failed: {str(e)}"}
        )

# this is used to verify your jwt token if  it  is correct
@router.get("/verify")
def verify_token_endpoint(
        current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Verify if the JWT token is valid and return user information.

    Args:
        current_user: User information extracted from valid JWT token
                     via the get_current_user dependency

    Returns:
        Dict with validation status and user information
        Example: {"valid": True, "user": {"id": "123", "email": "user@example.com"}}

    Raises:
        HTTPException: 401 if token is invalid/expired (handled by get_current_user)
    """
    return {"valid": True, "user": current_user}

# endpoint for logging users out
@router.post("/logout")
def logout(
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Logout user by removing their tokens.

    Args:
        current_user: User information from valid JWT token

    Returns:
        Success message

    Raises:
        HTTPException: 401 if token is invalid/expired
    """
    user_id = current_user["id"]
    all_tokens = read_json_file(TOKENS_FILE)
    if user_id in all_tokens:
        del all_tokens[user_id]
        write_json_file(TOKENS_FILE, all_tokens)
    return {"message": "Logged out successfully"}