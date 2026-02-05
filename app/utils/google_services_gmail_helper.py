import base64
from typing import Any, Dict
from fastapi import Depends, HTTPException, status
from googleapiclient.discovery import build
from app.config import logger, sentry_sdk
from app.dependencies import get_current_user
from app.services.google_auth import get_user_google_creds


def get_gmail_service(
        current_user: Dict[str, Any] = Depends(get_current_user)
) -> Any:
    """
    Dependency helper to initialize an authenticated Gmail API service.

    This function verifies the user's Google credentials and builds the
    Gmail 'v1' service object. It handles error reporting via Sentry and
    logging for connection failures.

    Args:
        current_user (Dict[str, Any]): The authenticated user from the session.

    Returns:
        Any: An authorized Google API Discovery Resource for Gmail.

    Raises:
        HTTPException: 400 if credentials are missing.
        HTTPException: 500 if the service fails to build.
    """
    user_id = current_user.get("id")

    # 1. Verify Identity & Credentials
    creds = get_user_google_creds(user_id)

    if not creds:
        logger.warning(f"Gmail Auth Failed: No credentials found for user {user_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gmail is not connected. Please link your Google account."
        )
    try:
        service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error(f"❌ Failed to build Gmail service for user {user_id}: {str(e)}",
                     exc_info=True)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect to the Gmail service."
        )


def get_email_body(payload: Dict[str, Any]) -> str:
    """
    Recursively extracts and decodes the email body from a Gmail message payload.

    This function prioritizes HTML content for a better UI experience but falls
    back to plain text if HTML is unavailable. It handles URL-safe Base64 decoding
    and multipart MIME structures.

    Args:
        payload (Dict[str, Any]): The 'payload' dictionary from a Gmail message object.

    Returns:
        str: The decoded string content of the email, or a fallback message.
    """
    try:
        # 1. Handle Multipart Messages (recursive check)
        if 'parts' in payload:
            parts = payload['parts']
            html_content = None
            plain_content = None

            for part in parts:
                mime_type = part.get('mimeType')

                # If this part has its own sub-parts, recurse deeper
                if 'parts' in part:
                    recursive_result = get_email_body(part)
                    if recursive_result and "Could not decode" not in recursive_result:
                        return recursive_result

                # Extract data if available
                data = part.get('body', {}).get('data')
                if not data:
                    continue

                # Decode the content
                decoded_data = base64.urlsafe_b64decode(data).decode('utf-8',
                                                                     errors='ignore')

                if mime_type == 'text/html':
                    html_content = decoded_data
                elif mime_type == 'text/plain':
                    plain_content = decoded_data

            return html_content or plain_content or "Empty message body."

        # 2. Handle Simple (Non-multipart) Messages
        else:
            data = payload.get('body', {}).get('data')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

    except Exception as e:
        logger.error(f"Failed to decode email body: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return "Error: Could not decode this email's content."

    return "No content available for this message."