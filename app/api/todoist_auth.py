import base64
import hashlib
import secrets
import threading
import time
from typing import Any, Dict, Tuple
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import (
    FRONTEND_URL,
    TODOIST_AUTH_URL,
    TODOIST_CLIENT_ID,
    TODOIST_CLIENT_SECRET,
    TODOIST_REDIRECT_URI,
    TODOIST_SCOPES,
    TODOIST_STATE_TTL_SECONDS,
    logger,
)
from app.dependencies import get_current_user
from app.db_store import delete_todoist_credential, get_todoist_credential

# Router for Todoist OAuth 2.0 authorization-code flow (per-user connection).
router = APIRouter(prefix="/dashboard/todoist/auth", tags=["Todoist Auth"])

# Thread-safe, in-memory OAuth state store.
# state -> {"user_id": str, "code_verifier": str, "created_at": float}
# One-time-use, TTL-bound, bound to the internal user_id (not email).
_OAUTH_STATE: Dict[str, Dict[str, Any]] = {}
_OAUTH_STATE_LOCK = threading.Lock()


def _todoist_configured() -> bool:
    """True only when the backend has the OAuth client credentials and callback URI."""
    return bool(TODOIST_CLIENT_ID and TODOIST_CLIENT_SECRET and TODOIST_REDIRECT_URI)


def _cleanup_expired_state(now: float) -> None:
    """Remove expired state entries from the store."""
    with _OAUTH_STATE_LOCK:
        expired = [
            state
            for state, entry in _OAUTH_STATE.items()
            if now - entry.get("created_at", 0) > TODOIST_STATE_TTL_SECONDS
        ]
        for state in expired:
            _OAUTH_STATE.pop(state, None)


def _create_oauth_state(user_id: str) -> Tuple[str, str]:
    """Generate OAuth state + PKCE code challenge, bind to the internal user_id.

    Stores the code_verifier in the thread-safe TTL store keyed by state so the
    callback can validate PKCE later. The state is one-time-use and expires after
    TODOIST_STATE_TTL_SECONDS.

    Returns (state, code_challenge).
    """
    now = time.time()
    _cleanup_expired_state(now)

    # Cryptographically secure, unpredictable OAuth state.
    state = secrets.token_urlsafe(32)
    # PKCE code verifier + SHA256 base64url code challenge.
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    with _OAUTH_STATE_LOCK:
        _OAUTH_STATE[state] = {
            "user_id": user_id,
            "code_verifier": code_verifier,
            "created_at": now,
        }

    return state, code_challenge


@router.get("/login")
def login_todoist(current_user: dict = Depends(get_current_user)) -> RedirectResponse:
    """Start the Todoist OAuth authorization-code flow for the logged-in user.

    Requires a valid JWT (get_current_user). Generates a cryptographically secure
    OAuth state and a PKCE code_verifier/code_challenge, binds them to the
    current user's id in a thread-safe TTL store, and redirects the browser to
    Todoist's authorization URL.
    """
    if not _todoist_configured():
        raise HTTPException(status_code=503, detail="Todoist OAuth not configured")

    user_id = current_user["id"]
    state, code_challenge = _create_oauth_state(user_id)

    params = {
        "client_id": TODOIST_CLIENT_ID,
        "scope": TODOIST_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "redirect_uri": TODOIST_REDIRECT_URI,
    }
    auth_url = f"{TODOIST_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url=auth_url, status_code=302)


@router.post("/start")
def start_todoist_oauth(current_user: dict = Depends(get_current_user)):
    """Initiate the Todoist OAuth authorization-code flow for the logged-in user.

    Requires a valid dashboard JWT. Returns a JSON authorization URL so the
    frontend can authenticate first (the Axios request interceptor attaches the
    JWT) and then navigate the browser to Todoist. Never returns the client
    secret, access token, refresh token, or PKCE verifier.
    """
    if not _todoist_configured():
        raise HTTPException(status_code=503, detail="Todoist OAuth not configured")

    user_id = current_user["id"]
    state, code_challenge = _create_oauth_state(user_id)

    params = {
        "client_id": TODOIST_CLIENT_ID,
        "scope": TODOIST_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "redirect_uri": TODOIST_REDIRECT_URI,
    }
    auth_url = f"{TODOIST_AUTH_URL}?{urlencode(params)}"
    return {
        "authorization_url": auth_url,
        "expires_in_seconds": TODOIST_STATE_TTL_SECONDS,
    }


def _handle_todoist_callback(request: Request) -> RedirectResponse:
    """Shared secure callback logic for Todoist OAuth.

    Validates the OAuth state (exists, not expired, one-time-use), retrieves the
    state-bound internal user_id, exchanges the authorization code for tokens
    (including the PKCE code_verifier), and persists the credentials against that
    user_id. Redirects back to the frontend with ?todoist=connected or
    ?todoist=error.

    This is reached via Todoist's external redirect, so it does not require a
    fresh dashboard JWT; authentication relies on the original securely bound,
    one-time OAuth state.
    """
    if not _todoist_configured():
        raise HTTPException(status_code=503, detail="Todoist OAuth not configured")

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing authorization code or state")

    now = time.time()

    # One-time-use: pop/remove the state entry as soon as it is read.
    with _OAUTH_STATE_LOCK:
        entry = _OAUTH_STATE.pop(state, None)

    if entry is None:
        raise HTTPException(status_code=400, detail="OAuth session expired or invalid")
    if now - entry.get("created_at", 0) > TODOIST_STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="OAuth session expired")

    user_id = entry.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="OAuth session missing user binding")

    # Exchange the authorization code for tokens. Client secret and code_verifier
    # are sent only in this backend-to-Todoist request; neither is ever logged or
    # returned to the frontend. PKCE requires code_verifier when S256 was used.
    token_payload = {
        "client_id": TODOIST_CLIENT_ID,
        "client_secret": TODOIST_CLIENT_SECRET,
        "code": code,
        "redirect_uri": TODOIST_REDIRECT_URI,
        "code_verifier": entry["code_verifier"],
    }
    try:
        token_response = requests.post(TODOIST_TOKEN_URL, data=token_payload, timeout=15)
        token_response.raise_for_status()
        tokens = token_response.json()
    except requests.RequestException as exc:
        # Never log the authorization code or any token values.
        logger.error("Todoist token exchange failed: %s", exc)
        return RedirectResponse(url=f"{FRONTEND_URL}?todoist=error", status_code=302)

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token:
        logger.error("Todoist token exchange returned no access token")
        return RedirectResponse(url=f"{FRONTEND_URL}?todoist=error", status_code=302)

    # Fetch the Todoist user profile to map the Todoist user ID to this
    # dashboard user. Needed for webhook event routing.
    todoist_user_id = None
    try:
        profile_resp = requests.get(
            "https://api.todoist.com/api/v1/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if profile_resp.status_code == 200:
            todoist_user_id = profile_resp.json().get("id")
    except requests.RequestException:
        # Non-fatal: webhook mapping won't work, but the connection is still valid.
        pass

    # Persist tokens for the state-bound user via db_store CRUD.
    # Lazy import so this module loads even before db_store defines the function.
    from app.db_store import save_todoist_credential

    save_todoist_credential(
        user_id,
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "todoist_user_id": todoist_user_id,
        },
    )

    return RedirectResponse(url=f"{FRONTEND_URL}?todoist=connected", status_code=302)


@router.get("/callback")
def callback_todoist(request: Request) -> RedirectResponse:
    """Handle Todoist's OAuth redirect after the user authorizes the app.

    Delegates to the shared secure callback logic so both the
    /dashboard/todoist/auth/callback and /integrations/todoist/callback paths
    invoke identical behavior.
    """
    return _handle_todoist_callback(request)


@router.get("/connection-status")
def connection_status(current_user: dict = Depends(get_current_user)):
    """Return whether the current user has connected their Todoist account.

    Only returns a boolean flag — never tokens or credential details.
    """
    credential = get_todoist_credential(current_user["id"])
    return {"connected": bool(credential)}


@router.post("/disconnect")
def disconnect_todoist(current_user: dict = Depends(get_current_user)):
    """Revoke and delete the current user's Todoist credentials.

    After this, the user's Todoist tasks will no longer be accessible until
    they reconnect via the OAuth flow.
    """
    deleted = delete_todoist_credential(current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="No Todoist connection found")
    return {"message": "Todoist disconnected successfully"}
