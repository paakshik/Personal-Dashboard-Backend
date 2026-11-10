"""Todoist Webhook endpoint with HMAC-SHA256 verification.

Verifies incoming webhook deliveries from Todoist, maps the Todoist user ID
to the internal dashboard user, and processes task/project events with
idempotency and per-user isolation.
"""

import hashlib
import hmac
import json
import threading
import time
from typing import Any, Dict, Set

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.todoist_auth import _handle_todoist_callback
from app.config import TODOIST_CLIENT_SECRET, logger, sentry_sdk
from app.db_store import get_todoist_credential_by_todoist_user_id

router = APIRouter(prefix="/integrations/todoist", tags=["Todoist Webhooks"])

# In-memory idempotency store: delivery_id -> processed timestamp
# Delivery IDs older than 24 hours are swept.
_PROCESSED_DELIVERIES: Dict[str, float] = {}
_PROCESSED_DELIVERIES_LOCK = threading.Lock()
_DELIVERY_TTL_SECONDS = 24 * 60 * 60  # 24 hours

# Supported Todoist webhook event prefixes
SUPPORTED_EVENT_PREFIXES = ("item", "project", "section", "note")


def _cleanup_old_deliveries(now: float) -> None:
    """Remove delivery IDs older than the TTL from the idempotency store."""
    with _PROCESSED_DELIVERIES_LOCK:
        expired = [
            did for did, ts in _PROCESSED_DELIVERIES.items()
            if now - ts > _DELIVERY_TTL_SECONDS
        ]
        for did in expired:
            _PROCESSED_DELIVERIES.pop(did, None)


def _is_duplicate_delivery(delivery_id: str) -> bool:
    """Return True if this delivery_id was already processed (idempotency)."""
    with _PROCESSED_DELIVERIES_LOCK:
        if delivery_id in _PROCESSED_DELIVERIES:
            return True
        _PROCESSED_DELIVERIES[delivery_id] = time.time()
        return False


def _verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Verify the X-Todoist-Hmac-SHA256 signature using HMAC-SHA256.

    The signature is computed over the exact raw request body using the
    application Client Secret. Comparison uses hmac.compare_digest to
    avoid timing attacks.
    """
    if not signature:
        return False
    if not TODOIST_CLIENT_SECRET:
        logger.error("Todoist webhook verification skipped: CLIENT_SECRET not configured")
        return False
    expected = hmac.new(
        TODOIST_CLIENT_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _process_event(event: dict, user_id: str) -> None:
    """Process a single Todoist webhook event for the given internal user.

    Events are processed in isolation per user. Task and project events are
    supported; unknown event types are logged and ignored.
    """
    event_name = event.get("event_name", "")
    event_data = event.get("event_data", {}) or {}

    # Only process supported event prefixes
    prefix = event_name.split(":")[0] if ":" in event_name else event_name
    if prefix not in SUPPORTED_EVENT_PREFIXES:
        logger.info("Webhook: ignoring unsupported event %s for user %s", event_name, user_id)
        return

    logger.info(
        "Webhook: processing event %s for user %s (data keys: %s)",
        event_name, user_id, list(event_data.keys())[:5],
    )

    # Fetch authoritative current data from Todoist where necessary.
    # For item:added/updated/deleted, the event_data contains the item.
    # For project events, the event_data contains the project.
    # The frontend/backend can refetch the full task list on next sync.
    #
    # No credential values are logged here.

    try:
        sentry_sdk.capture_event({
            "message": f"Todoist webhook event: {event_name}",
            "level": "info",
            "tags": {
                "event_name": event_name,
                "user_id": user_id,
            },
            "extra": {
                "event_data_keys": list(event_data.keys()) if isinstance(event_data, dict) else None,
            },
        })
    except Exception:
        pass


@router.post("/webhook")
async def todoist_webhook(
    request: Request,
    x_todoist_hmac_sha256: str = Header(default=None, alias="X-Todoist-Hmac-SHA256"),
) -> JSONResponse:
    """Handle incoming Todoist webhook deliveries.

    Verifies the HMAC-SHA256 signature, checks delivery idempotency, maps the
    Todoist user ID to the internal dashboard user, and dispatches the event
    for processing. Returns 200 on acceptance, 400/401 on rejection.
    """
    now = time.time()
    _cleanup_old_deliveries(now)

    # Read the raw body for signature verification.
    raw_body = await request.body()

    # 1. Verify HMAC-SHA256 signature
    if not _verify_signature(raw_body, x_todoist_hmac_sha256):
        logger.warning("Webhook: invalid HMAC signature, rejecting delivery")
        return JSONResponse(
            status_code=401,
            content={"error": "invalid signature"},
        )

    # 2. Parse the JSON payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("Webhook: invalid JSON payload, rejecting delivery")
        return JSONResponse(
            status_code=400,
            content={"error": "invalid JSON"},
        )

    if not isinstance(payload, dict):
        logger.warning("Webhook: payload is not a JSON object, rejecting delivery")
        return JSONResponse(
            status_code=400,
            content={"error": "invalid payload"},
        )

    # 3. Idempotency — reject duplicate deliveries
    delivery_id = payload.get("delivery_id") or payload.get("event_id")
    if delivery_id:
        if _is_duplicate_delivery(str(delivery_id)):
            logger.info("Webhook: duplicate delivery %s, skipping", delivery_id)
            return JSONResponse(
                status_code=200,
                content={"status": "duplicate", "delivery_id": str(delivery_id)},
            )

    # 4. Identify the internal user through the Todoist user ID mapping
    todoist_user_id = payload.get("user_id")
    if not todoist_user_id:
        logger.warning("Webhook: no Todoist user_id in payload, rejecting")
        return JSONResponse(
            status_code=400,
            content={"error": "missing user_id"},
        )

    credential = get_todoist_credential_by_todoist_user_id(str(todoist_user_id))
    if not credential:
        logger.warning(
            "Webhook: no dashboard user mapped to Todoist user %s", todoist_user_id
        )
        return JSONResponse(
            status_code=404,
            content={"error": "unknown Todoist account"},
        )

    internal_user_id = credential["user_id"]

    # 5. Process the event in isolation for this user
    try:
        _process_event(payload, internal_user_id)
    except Exception as exc:
        logger.error("Webhook: event processing failed for user %s: %s", internal_user_id, exc)
        sentry_sdk.capture_exception(exc)
        # Still return 200 so Todoist doesn't redeliver a poison event.
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": str(exc)[:200]},
        )

    return JSONResponse(
        status_code=200,
        content={"status": "ok", "delivery_id": str(delivery_id) if delivery_id else None},
    )


@router.get("/callback")
async def todoist_callback_alias(request: Request):
    """Callback alias at /integrations/todoist/callback matching the registered redirect URI.

    Delegates to the shared _handle_todoist_callback so the same secure logic
    serves both /dashboard/todoist/auth/callback and this alias.
    """
    return _handle_todoist_callback(request)